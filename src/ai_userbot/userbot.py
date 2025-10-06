from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
import pytz

from telethon import TelegramClient, events, types, errors
from telethon.tl.types import Message, Chat, User
from telethon.tl.functions.channels import JoinChannelRequest
# MessageId is not directly available, we'll use message.id instead
from telethon.tl.functions import contacts

from .config import AppConfig
from .llm import LLMClient, LLMRequest
from .database import ChatDatabase, ChatInfo, MessageContext
from .persona import PersonaManager
from .promoted_bot_context import get_bot_context, get_relevant_features, generate_natural_mention
from .chat_rules import ChatRulesAnalyzer

log = logging.getLogger(__name__)


class UserBot:
    """Telegram userbot that acts as a real person in chats"""
    
    def __init__(self, config: AppConfig, llm: LLMClient, db: ChatDatabase):
        self.config = config
        self.llm = llm
        self.db = db
        self.persona = PersonaManager(config.persona)
        self.rules_analyzer = ChatRulesAnalyzer()
        
        # Telethon client
        self.client = TelegramClient(
            session=config.telegram.session_name,
            api_id=config.telegram.api_id,
            api_hash=config.telegram.api_hash,
        )
        
        # State tracking
        self.active_chats: Set[int] = set()
        self.last_message_time: Dict[int, float] = {}
        self.messages_per_hour: Dict[int, List[float]] = {}
        self.is_typing: Dict[int, bool] = {}
        self.chat_rules_cache: Dict[int, Dict[str, bool]] = {}  # Cache analyzed rules
        
        # Setup handlers
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup message handlers"""
        # Handle messages in groups and personal messages
        @self.client.on(events.NewMessage(chats=None, incoming=True))
        async def on_message(event: events.NewMessage.Event):
            if event.is_group:
                await self._handle_group_message(event)
            elif self.config.policy.respond_to_personal_messages and not event.is_group:
                await self._handle_personal_message(event)

        # Handle when bot is added to a new chat
        @self.client.on(events.ChatAction)
        async def on_chat_action(event: events.ChatAction.Event):
            if event.user_added and event.user_id == (await self.client.get_me()).id:
                log.info(f"Bot was added to chat {event.chat_id}")
                await self._handle_new_chat_joined(event.chat_id)
            elif event.user_kicked and event.user_id == (await self.client.get_me()).id:
                log.info(f"Bot was removed from chat {event.chat_id}")
                await self._handle_chat_left(event.chat_id)

    async def _handle_personal_message(self, event: events.NewMessage.Event):
        """Handle personal messages (DMs)"""
        if not self.config.policy.respond_to_personal_messages:
            return

        message = event.message
        sender = await event.get_sender()

        # Check hourly limit for personal messages
        if not await self._check_personal_hourly_limit(sender.id):
            return

        # Store message context
        await self.db.add_message_context(
            chat_id=0,  # Personal messages don't have chat_id
            user_id=sender.id if sender else 0,
            username=sender.username if sender and hasattr(sender, 'username') else "",
            message_text=message.text or "",
            timestamp=message.date
        )

        # Check if we should respond (simplified logic for personal messages)
        if await self._should_respond_to_personal(sender, message):
            # Simulate human-like typing
            await self._simulate_human_behavior(0, message)  # 0 for personal

            # Generate response
            response = await self._generate_personal_response(message)

            if response:
                try:
                    await self.client.send_message(sender.id, response)

                    # Log the response
                    await self.db.log_message(
                        chat_id=0,
                        user_id=0,
                        message_text=response,
                        is_bot_message=True
                    )

                except Exception as e:
                    log.error(f"Error sending personal response: {e}")

    async def _should_respond_to_personal(self, sender, message) -> bool:
        """Determine if we should respond to a personal message"""
        # Don't respond to our own messages
        if sender and sender.id == (await self.client.get_me()).id:
            return False

        # Simple relevance check - respond to most messages
        text = message.text or ""
        if len(text.strip()) < 3:  # Too short
            return False

        # Check for forbidden terms
        for term in self.config.policy.forbidden_terms:
            if term.lower() in text.lower():
                return False

        return True

    async def _check_personal_hourly_limit(self, user_id: int) -> bool:
        """Check if we've reached the hourly limit for personal messages to this user"""
        current_time = datetime.now()
        hour_start = current_time.replace(minute=0, second=0, microsecond=0)

        # Get messages sent to this user in the last hour
        recent_messages = await self.db.get_personal_messages_since(user_id, hour_start)

        return len(recent_messages) < self.config.policy.max_personal_replies_per_hour

    async def _generate_personal_response(self, message) -> Optional[str]:
        """Generate response to personal message"""
        try:
            context = f"Пользователь написал: {message.text or ''}"

            response = await self.llm.generate_response(
                system_prompt=f"Ты {self.persona.name}, {self.persona.age} лет. {self.persona.bio}. Общайся естественно и дружелюбно.",
                user_message=context,
                chat_context={"is_personal": True}
            )

            if response:
                # Add human-like variations
                response = self._add_human_variations(response)

            return response

        except Exception as e:
            log.error(f"Error generating personal response: {e}")
            return None
    
    async def start(self):
        """Start the userbot"""
        # Connect to Telegram with existing session
        await self.client.connect()
        log.info("UserBot started successfully")

        # Load previously active chats from database
        active_chats = await self.db.get_active_chats()
        self.active_chats = {chat.chat_id for chat in active_chats}

        # Start background tasks
        asyncio.create_task(self._chat_discovery_loop())
        asyncio.create_task(self._cleanup_old_messages())
        asyncio.create_task(self._activity_scheduler())
    
    async def stop(self):
        """Stop the userbot"""
        await self.client.disconnect()
        log.info("UserBot stopped")

    async def _handle_new_chat_joined(self, chat_id: int):
        """Handle when bot is added to a new chat"""
        try:
            # Get chat info
            chat = await self.client.get_entity(chat_id)
            if not chat:
                return

            # Check if chat meets criteria
            if not self._is_suitable_chat(chat):
                log.info(f"Chat {chat_id} doesn't meet criteria, leaving")
                await self.client.delete_dialog(chat_id)
                return

            # Analyze chat rules
            try:
                pinned = await self._get_pinned_messages(chat_id)
                rules = self.rules_analyzer.analyze_chat_rules(chat, pinned)
                self.chat_rules_cache[chat_id] = rules
            except Exception as e:
                log.warning(f"Could not analyze rules for chat {chat_id}: {e}")
                rules = {}

            # Add to database
            await self.db.add_chat(
                chat_id=chat_id,
                title=getattr(chat, 'title', 'Unknown'),
                username=getattr(chat, 'username', None),
                members_count=getattr(chat, 'participants_count', 0),
                is_active=True
            )

            self.active_chats.add(chat_id)
            log.info(f"Successfully joined chat: {getattr(chat, 'title', 'Unknown')}")

        except Exception as e:
            log.error(f"Error handling new chat {chat_id}: {e}")

    async def _handle_chat_left(self, chat_id: int):
        """Handle when bot leaves a chat"""
        self.active_chats.discard(chat_id)
        await self.db.deactivate_chat(chat_id)
        log.info(f"Left chat {chat_id}")

    def _is_suitable_chat(self, chat) -> bool:
        """Check if chat meets our criteria"""
        # Must be a group/supergroup
        if not hasattr(chat, 'megagroup') and not (hasattr(chat, 'broadcast') and not chat.broadcast):
            return False

        # Must be joinable
        if not getattr(chat, 'is_joinable', True):
            return False

        # Check against forbidden terms in title/description
        title = getattr(chat, 'title', '').lower()
        description = getattr(chat, 'about', '').lower()
        username = getattr(chat, 'username', '').lower()

        chat_text = f"{title} {description} {username}"

        for term in self.config.policy.forbidden_terms:
            if term.lower() in chat_text:
                return False

        # Check if it's a relevant chat based on keywords
        relevant_keywords = [
            "женск", "девушк", "мамочк", "подруг", "мам", "женщин",
            "бали", "таиланд", "путешеств", "travel", "тур",
            "москва", "мск", "спб", "питер", "россия"
        ]

        relevant_count = sum(1 for keyword in relevant_keywords if keyword in chat_text)
        if relevant_count > 0:
            return True

        # Also accept chats with reasonable size (not too small, not too large)
        participants_count = getattr(chat, 'participants_count', 0)
        if 50 <= participants_count <= 50000:  # Reasonable size range
            return True

        return False

    def _generate_search_variations(self, keyword: str) -> List[str]:
        """Generate search variations for better chat discovery"""
        variations = []

        # Add common prefixes and suffixes
        prefixes = ["чат", "группа", "клуб", "сообщество", "форум"]
        suffixes = ["обсуждения", "дискуссии", "разговоры", "чат"]

        for prefix in prefixes:
            variations.append(f"{prefix} {keyword}")

        for suffix in suffixes:
            variations.append(f"{keyword} {suffix}")

        # Add location-based variations for travel keywords
        if keyword.lower() in ["бали", "таиланд", "путешествия", "travel"]:
            locations = ["россия", "москва", "спб", "питер"]
            for location in locations:
                variations.append(f"{keyword} {location}")
                variations.append(f"{location} {keyword}")

        # Add variations for women's chats
        if keyword.lower() in ["женск", "девушк", "мамочк"]:
            categories = ["путешествия", "туризм", "отдых", "досуг"]
            for category in categories:
                variations.append(f"{keyword} {category}")

        # Remove duplicates and limit
        variations = list(set(variations))
        return variations[:10]  # Limit to prevent too many searches

    async def _get_pinned_messages(self, chat_id: int):
        """Get pinned messages from a chat"""
        try:
            async for message in self.client.iter_messages(chat_id, limit=5):
                if message.pinned:
                    return [message]
        except Exception as e:
            log.warning(f"Could not get pinned messages for chat {chat_id}: {e}")
        return []
    
    def _get_chat_category(self, chat_title: str) -> str:
        """Determine chat category based on title"""
        title_lower = chat_title.lower() if chat_title else ""
        
        for category, keywords in self.config.telegram.chat_categories.items():
            if any(keyword in title_lower for keyword in keywords):
                return category
        
        return "general"
    
    def _is_active_time(self) -> bool:
        """Check if current time is within active hours"""
        tz = pytz.timezone(self.config.policy.timezone)
        now = datetime.now(tz)
        current_hour = now.hour
        
        # Check if it's sleep time
        wake_up = self.config.policy.active_hours["wake_up"]
        sleep_time = self.config.policy.active_hours["sleep_time"]
        
        if sleep_time < wake_up:  # Sleep crosses midnight
            if current_hour >= sleep_time or current_hour < wake_up:
                # Night time - small chance to respond (like woke up for baby)
                return random.random() < self.config.policy.night_messages_probability
            return True
        
        # Normal day
        if current_hour < wake_up or current_hour >= sleep_time:
            # Night time - small chance
            return random.random() < self.config.policy.night_messages_probability
        
        # Weekend check
        if now.weekday() >= 5:  # Saturday or Sunday
            if random.random() < self.config.policy.weekend_activity_multiplier:
                return True
            return False
        
        return True
    
    async def _handle_group_message(self, event: events.NewMessage.Event):
        """Handle incoming group messages"""
        message = event.message
        chat_id = message.chat_id

        # Skip if chat is not in our active list
        if chat_id not in self.active_chats:
            return

        # Check if we're in active hours
        if not self._is_active_time():
            log.debug(f"Skipping message - outside active hours")
            return

        # Store message context for future reference
        sender = await event.get_sender()
        await self.db.add_message_context(
            chat_id=chat_id,
            user_id=sender.id if sender else 0,
            username=sender.username if sender and hasattr(sender, 'username') else "",
            message_text=message.text or "",
            timestamp=message.date
        )

        # Check if we should respond
        should_respond = await self._should_respond(chat_id, message)
        if not should_respond:
            return

        # Check hourly message limit for this chat
        if not await self._check_hourly_limit(chat_id):
            log.debug(f"Hourly limit reached for chat {chat_id}")
            return

        # Simulate typing with random delay
        await self._simulate_human_behavior(chat_id, message)

        # Generate response
        response = await self._generate_response(chat_id, message)
        if not response:
            return

        # Send response
        try:
            await self.client.send_message(chat_id, response)

            # Update tracking
            now = time.time()
            self.last_message_time[chat_id] = now

            # Track hourly messages
            if chat_id not in self.messages_per_hour:
                self.messages_per_hour[chat_id] = []
            self.messages_per_hour[chat_id].append(now)

            # Log interaction
            await self.db.log_bot_message(
                chat_id=chat_id,
                message_text=response,
                includes_promotion=self.config.promoted_bot.username in response or self.config.promoted_bot.name in response
            )

        except FloodWait as e:
            log.warning(f"FloodWait for {e.seconds} seconds in chat {chat_id}")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            log.error(f"Error sending message to chat {chat_id}: {e}")

    async def _should_respond(self, chat_id: int, message) -> bool:
        """Decide if bot should respond to the message"""
        # Check rate limits
        if not self._check_rate_limits(chat_id):
            return False

        # Check forbidden terms
        if message.text and any(term.lower() in message.text.lower() for term in self.config.policy.forbidden_terms):
            return False

        # Get chat category
        try:
            chat = await self.client.get_entity(chat_id)
            chat_title = chat.title if hasattr(chat, 'title') else ""
        except:
            chat_title = ""
        chat_category = self._get_chat_category(chat_title)

        # Get recent context
        context = await self.db.get_recent_messages(chat_id, limit=10)
        
        # Calculate relevance score
        relevance = await self._calculate_relevance(message, context)
        
        # Adjust chance based on chat category
        base_chance = self.config.policy.response_probability[chat_category]
        
        # Boost if message mentions persona interests
        if any(interest in (message.text or "").lower() for interest in self.persona.interests):
            base_chance *= 1.5
        
        # Boost if replied to bot
        if message.reply_to_msg_id:
            reply_msg = await self.client.get_messages(chat_id, ids=message.reply_to_msg_id)
            if reply_msg.from_id == (await self.client.get_me()).id:
                base_chance *= 2.0
        
        # Random decision based on chance
        return random.random() < base_chance and relevance > self.config.policy.min_relevance_score

    def _check_rate_limits(self, chat_id: int) -> bool:
        """Check if we can send a message without violating rate limits"""
        now = time.time()
        
        # Check min gap between messages in this chat
        if chat_id in self.last_message_time:
            time_since_last = now - self.last_message_time[chat_id]
            if time_since_last < self.config.policy.min_gap_seconds_per_chat:
                log.debug(f"Rate limit: too soon since last message in chat {chat_id}")
                return False
        
        # Check max messages per hour in this chat
        if chat_id in self.messages_per_hour:
            # Clean old messages (older than 1 hour)
            self.messages_per_hour[chat_id] = [t for t in self.messages_per_hour[chat_id] if now - t < 3600]
            
            if len(self.messages_per_hour[chat_id]) >= self.config.policy.max_replies_per_hour_per_chat:
                log.debug(f"Rate limit: max hourly messages reached in chat {chat_id}")
                return False
        
        return True

    async def _simulate_human_behavior(self, chat_id: int, message: Message):
        """Simulate human typing and delays"""
        # Random delay before "reading"
        await asyncio.sleep(random.uniform(1, 5))
        
        # Mark as read
        await self.client.send_read_acknowledge(chat_id, message)
        
        # Random typing delay based on response length (will be estimated)
        typing_time = random.uniform(self.config.policy.min_typing_delay, self.config.policy.max_typing_delay)
        
        # Send typing action
        async with self.client.action(chat_id, 'typing'):
            await asyncio.sleep(typing_time)

    async def _generate_response(self, chat_id: int, message: Message) -> Optional[str]:
        """Generate a natural response using LLM"""
        # Get recent context for human-like response
        context_messages = await self.db.get_recent_messages(chat_id, limit=5)

        # Build context string
        context = self._build_message_context(context_messages)
        context = f"Контекст разговора:\n{context}\n\nСообщение пользователя: {message.text or ''}"

        # Generate human-like response
        return await self._generate_human_like_response(context, chat_id)

    async def _calculate_relevance(self, message: Message, context: List[MessageContext]) -> float:
        """Calculate how relevant the message is to persona interests"""
        text = message.text or ""
        score = 0.0
        
        # Base score from interests match
        for interest in self.persona.interests:
            if interest.lower() in text.lower():
                score += 1.0
        
        # Boost from context
        for msg in context:
            if any(interest in msg.message_text.lower() for interest in self.persona.interests):
                score += 0.5
        
        # Normalize
        return min(score / len(self.persona.interests), 1.0)

    async def _chat_discovery_loop(self):
        """Background task to discover and join new chats"""
        while True:
            try:
                # Find new chats
                new_chats = await self._find_new_chats()
                
                for chat in new_chats:
                    try:
                        # Join chat
                        await self.client(JoinChannelRequest(chat.id))
                        
                        # Analyze rules
                        # Get pinned message using search for pinned messages
                        async for message in self.client.iter_messages(chat.id, limit=1):
                            if message.pinned:
                                pinned = [message]
                                break
                        else:
                            pinned = []
                        rules = self.rules_analyzer.analyze_chat_rules(chat, pinned)
                        self.chat_rules_cache[chat.id] = rules
                        
                        # Add to database
                        await self.db.add_chat(
                            chat_id=chat.id,
                            title=chat.title,
                            category=self._get_chat_category(chat.title),
                            rules=rules
                        )
                        
                        self.active_chats.add(chat.id)
                        log.info(f"Joined new chat: {chat.title} (ID: {chat.id})")
                    except (ChatAdminRequired, UserBannedInChannel) as e:
                        log.warning(f"Could not join chat {chat.id}: {e}")
                    except Exception as e:
                        log.error(f"Error joining chat {chat.id}: {e}")
                
            except Exception as e:
                log.error(f"Chat discovery error: {e}")
            
            # Sleep with jitter
            sleep_time = self.config.policy.chat_discovery_interval + random.uniform(-300, 300)
            await asyncio.sleep(sleep_time)

    async def _find_new_chats(self) -> List[Chat]:
        """Find new open chats based on keywords"""
        new_chats = []
        
        for keyword in self.config.telegram.search_keywords:
            try:
                # Enhanced chat search using multiple methods
                chats_found = set()

                try:
                    # Method 1: Global search using get_dialogs (this is more reliable)
                    async for dialog in self.client.iter_dialogs(limit=self.config.telegram.max_search_results_per_keyword):
                        if (dialog.is_group and not dialog.is_channel and
                            self._is_suitable_chat(dialog.entity) and
                            dialog.entity.id not in self.active_chats):

                            chats_found.add(dialog.entity.id)
                            new_chats.append(dialog.entity)
                            log.info(f"Found chat via dialogs: {getattr(dialog.entity, 'title', 'Unknown')} (@{getattr(dialog.entity, 'username', 'N/A')})")

                except Exception as e:
                    log.warning(f"Dialogs search failed for '{keyword}': {e}")

                try:
                    # Method 2: Try to find public chats by username patterns
                    if keyword.startswith('@'):
                        try:
                            entity = await self.client.get_entity(keyword)
                            if (entity and self._is_suitable_chat(entity) and
                                entity.id not in self.active_chats):
                                chats_found.add(entity.id)
                                new_chats.append(entity)
                                log.info(f"Found chat via username: {getattr(entity, 'title', 'Unknown')}")
                        except Exception as e:
                            log.debug(f"Username lookup failed for '{keyword}': {e}")

                except Exception as e:
                    log.warning(f"Username search failed for '{keyword}': {e}")

                # Method 3: Try common chat patterns and variations for better matching
                variations = self._generate_search_variations(keyword)
                for variation in variations[:3]:  # Limit to top 3 variations
                    if variation != keyword:  # Avoid duplicate searches
                        try:
                            # Search dialogs with variation
                            async for dialog in self.client.iter_dialogs(limit=10):
                                if (dialog.is_group and not dialog.is_channel and
                                    self._is_suitable_chat(dialog.entity) and
                                    dialog.entity.id not in self.active_chats and
                                    dialog.entity.id not in chats_found):

                                    # Check if variation matches chat title/description
                                    title = getattr(dialog.entity, 'title', '').lower()
                                    desc = getattr(dialog.entity, 'about', '').lower()
                                    username = getattr(dialog.entity, 'username', '').lower()

                                    if (variation.lower() in title or
                                        variation.lower() in desc or
                                        variation.lower() in username):
                                        chats_found.add(dialog.entity.id)
                                        new_chats.append(dialog.entity)
                                        log.info(f"Found chat via variation '{variation}': {getattr(dialog.entity, 'title', 'Unknown')}")

                        except Exception as e:
                            log.debug(f"Variation search failed for '{variation}': {e}")
            except Exception as e:
                if hasattr(e, 'seconds'):
                    await asyncio.sleep(e.seconds)
                else:
                    log.error(f"Search error for keyword '{keyword}': {e}")
                    break
            except Exception as e:
                log.error(f"Search error for keyword '{keyword}': {e}")
            
            await asyncio.sleep(random.uniform(5, 15))  # Anti-flood delay
        
        return new_chats[:self.config.telegram.max_new_chats_per_cycle]

    async def _cleanup_old_messages(self):
        """Periodic cleanup of old message history"""
        while True:
            # Clean messages older than 30 days
            cutoff_date = datetime.now() - timedelta(days=30)
            await self.db.cleanup_old_messages(cutoff_date)
            await asyncio.sleep(86400)  # Run daily

    async def _activity_scheduler(self):
        """Smart activity scheduler for human-like behavior"""
        while True:
            try:
                current_time = datetime.now(pytz.timezone(self.config.policy.timezone))

                # Check if we're in active hours
                if not self._is_active_time(current_time):
                    await asyncio.sleep(1800)  # Check every 30 minutes
                    continue

                # Get daily statistics
                today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
                daily_stats = await self.db.get_daily_stats(today_start)

                messages_sent_today = daily_stats.get('messages_sent', 0)
                active_chats_today = len(daily_stats.get('active_chats', set()))

                # If we haven't reached daily target, be more active
                if messages_sent_today < self.config.policy.daily_message_target:
                    # Distribute activity across available chats
                    available_chats = list(self.active_chats)
                    if available_chats:
                        # Shuffle chats for natural distribution
                        random.shuffle(available_chats)

                        # Calculate how many messages we need to send
                        remaining_messages = self.config.policy.daily_message_target - messages_sent_today
                        chats_to_use = min(len(available_chats), self.config.policy.max_chats_per_day)

                        messages_per_chat = max(1, remaining_messages // chats_to_use)

                        for chat_id in available_chats[:chats_to_use]:
                            try:
                                await self._send_scheduled_message(chat_id, messages_per_chat)
                                # Random delay between chat interactions
                                await asyncio.sleep(random.uniform(60, 300))  # 1-5 minutes
                            except Exception as e:
                                log.error(f"Error sending scheduled message to {chat_id}: {e}")

                # Sleep until next activity check (use configured interval)
                sleep_time = self.config.policy.chat_discovery_interval + random.uniform(-300, 300)  # ±5 minutes jitter
                await asyncio.sleep(max(600, sleep_time))  # Minimum 10 minutes

            except Exception as e:
                log.error(f"Error in activity scheduler: {e}")
                await asyncio.sleep(1800)

    def _is_active_time(self, current_time: datetime) -> bool:
        """Check if current time is within active hours"""
        hour = current_time.hour

        # Weekend vs weekday
        is_weekend = current_time.weekday() >= 5
        activity_multiplier = self.config.policy.weekend_activity_multiplier if is_weekend else 1.0

        # Check against active hours
        for period, hours in self.config.policy.active_hours.items():
            if isinstance(hours, list):
                start_hour, end_hour = hours
                if start_hour <= hour < end_hour:
                    # Add some randomness
                    if random.random() < activity_multiplier:
                        return True
            elif isinstance(hours, int):
                if hour >= hours:  # wake_up time
                    return True

        # Night messages (rare)
        if random.random() < self.config.policy.night_messages_probability:
            return True

        return False

    async def _send_scheduled_message(self, chat_id: int, target_messages: int):
        """Send scheduled messages to a chat"""
        messages_sent = 0

        # Get recent messages from this chat for context
        recent_messages = await self.db.get_recent_messages(chat_id, limit=5)

        for _ in range(min(target_messages, 3)):  # Max 3 messages per chat per cycle
            try:
                # Generate context-aware response
                context = self._build_message_context(recent_messages)
                response = await self._generate_human_like_response(context, chat_id)

                if response and len(response.strip()) > 10:  # Minimum length
                    # Add human-like delays and typing simulation
                    await self._simulate_human_behavior(chat_id)

                    # Send message
                    await self.client.send_message(chat_id, response)

                    # Update statistics
                    await self.db.log_message(
                        chat_id=chat_id,
                        user_id=0,  # Bot message
                        message_text=response,
                        is_bot_message=True
                    )

                    messages_sent += 1

                    # Random delay between messages in same chat
                    await asyncio.sleep(random.uniform(30, 120))

            except Exception as e:
                log.error(f"Error sending scheduled message to {chat_id}: {e}")
                break

    def _build_message_context(self, recent_messages) -> str:
        """Build context from recent messages"""
        context_parts = []
        for msg in recent_messages[-3:]:  # Last 3 messages
            context_parts.append(f"{msg.username or 'User'}: {msg.message_text}")

        return "\n".join(context_parts) if context_parts else "Начало разговора"

    async def _generate_human_like_response(self, context: str, chat_id: int) -> str:
        """Generate human-like response with typos and variations"""
        try:
            # Get base response from LLM
            response = await self.llm.generate_response(
                system_prompt=self.persona.get_system_prompt(),
                user_message=f"Контекст разговора:\n{context}\n\nНапиши естественный ответ в этом чате.",
                chat_context={"chat_id": chat_id}
            )

            if not response:
                return None

            # Add human-like variations
            response = self._add_human_variations(response)

            return response

        except Exception as e:
            log.error(f"Error generating response: {e}")
            return None

    def _add_human_variations(self, text: str) -> str:
        """Add human-like variations to text (typos, length variations, etc.)"""
        # Length variation
        if random.random() < self.config.policy.message_length_variation:
            words = text.split()
            if len(words) > 3:
                # Randomly remove or add words
                if random.random() < 0.5 and len(words) > 2:
                    words = words[:-1]  # Remove last word
                elif random.random() < 0.3:
                    # Add a filler word
                    fillers = ["ну", "вот", "типа", "как бы", "в общем"]
                    insert_pos = random.randint(0, len(words))
                    words.insert(insert_pos, random.choice(fillers))

                text = " ".join(words)

        # Occasional typos
        if random.random() < self.config.policy.typo_probability:
            text = self._add_typo(text)

        return text

    def _add_typo(self, text: str) -> str:
        """Add a random typo to text"""
        if len(text) < 5:
            return text

        # Common typos in Russian
        typo_patterns = [
            ("о", "а"), ("а", "о"), ("е", "и"), ("и", "е"),
            ("ы", "и"), ("у", "ю"), ("я", "а"), ("с", "з"),
            ("т", "д"), ("н", "м"), ("р", "л")
        ]

        words = text.split()
        if words:
            word_idx = random.randint(0, len(words) - 1)
            word = words[word_idx]

            if len(word) > 3:
                char_idx = random.randint(1, len(word) - 2)
                original_char = word[char_idx]

                # Find replacement
                for orig, repl in typo_patterns:
                    if original_char == orig:
                        new_word = word[:char_idx] + repl + word[char_idx + 1:]
                        words[word_idx] = new_word
                        break

        return " ".join(words)

    async def _check_hourly_limit(self, chat_id: int) -> bool:
        """Check if we've reached the hourly message limit for this chat"""
        current_time = datetime.now()
        hour_start = current_time.replace(minute=0, second=0, microsecond=0)

        # Get messages sent in the last hour
        recent_messages = await self.db.get_messages_since(chat_id, hour_start, bot_only=True)

        return len(recent_messages) < self.config.policy.max_replies_per_hour_per_chat

    async def _simulate_human_behavior(self, chat_id: int):
        """Simulate human-like behavior before sending message"""
        # Random delay before typing
        delay = random.uniform(*self.config.policy.reaction_delay_range)
        await asyncio.sleep(delay)

        # Simulate typing
        typing_time = random.uniform(
            self.config.policy.min_typing_delay,
            self.config.policy.max_typing_delay
        )
        async with self.client.action(chat_id, 'typing'):
            await asyncio.sleep(typing_time)
