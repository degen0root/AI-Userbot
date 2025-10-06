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
from telethon.tl.types import MessageId
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
        # Handle messages in groups
        @self.client.on(events.NewMessage(chats=None, incoming=True))
        async def on_group_message(event: events.NewMessage.Event):
            if event.is_group:
                await self._handle_group_message(event)
    
    async def start(self):
        """Start the userbot"""
        await self.client.start()
        log.info("UserBot started successfully")

        # Load previously active chats from database
        active_chats = await self.db.get_active_chats()
        self.active_chats = {chat.chat_id for chat in active_chats}

        # Start background tasks
        asyncio.create_task(self._chat_discovery_loop())
        asyncio.create_task(self._cleanup_old_messages())
    
    async def stop(self):
        """Stop the userbot"""
        await self.client.disconnect()
        log.info("UserBot stopped")
    
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
        # Get chat info
        chat = await self.client.get_entity(chat_id)
        chat_title = chat.title if hasattr(chat, 'title') else "Unknown"
        chat_category = self._get_chat_category(chat_title)
        
        # Get recent context
        context = await self.db.get_recent_messages(chat_id, limit=self.config.llm.context_messages)
        
        # Decide if to promote
        should_promote = random.random() < self.config.policy.promotion_probability[chat_category]
        
        # Get relevant bot features if promoting
        if should_promote:
            relevant_features = get_relevant_features(message.text or "", context)
            bot_mention = generate_natural_mention(self.config.promoted_bot, relevant_features, self.rules_analyzer.analyze_chat_rules(chat))
        else:
            bot_mention = ""
        
        # Prepare LLM request
        request = LLMRequest(
            system_prompt=self.persona.get_system_prompt(chat_category, should_promote),
            user_message=message.text or "",
            context=context,
            bot_mention=bot_mention if should_promote else ""
        )
        
        try:
            response = await self.llm.generate_response(request)
            if not response:
                return None
            
            # Enforce max length
            if len(response) > self.config.policy.max_response_length:
                response = response[:self.config.policy.max_response_length] + "..."
            
            return response
            
        except Exception as e:
            log.error(f"LLM generation error: {e}")
            return None

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
                        pinned = await self.client.get_messages(chat.id, ids=MessageId(pinned=True))
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
            sleep_time = self.config.telegram.chat_discovery_interval + random.uniform(-300, 300)
            await asyncio.sleep(sleep_time)

    async def _find_new_chats(self) -> List[Chat]:
        """Find new open chats based on keywords"""
        new_chats = []
        
        for keyword in self.config.telegram.search_keywords:
            try:
                # Search for public chats
                result = await self.client(functions.contacts.Search(q=keyword, limit=10))
                
                for chat in result.chats:
                    if chat.is_group and not chat.is_private and chat.is_joinable:
                        if chat.id not in self.active_chats:
                            new_chats.append(chat)
            except FloodWait as e:
                await asyncio.sleep(e.seconds)
            except Exception as e:
                log.error(f"Search error for keyword '{keyword}': {e}")
            
            await asyncio.sleep(random.uniform(5, 15))  # Anti-flood delay
        
        return new_chats[:self.config.policy.max_new_chats_per_cycle]

    async def _cleanup_old_messages(self):
        """Periodic cleanup of old message history"""
        while True:
            await self.db.cleanup_old_messages(self.config.db.message_history_days)
            await asyncio.sleep(86400)  # Run daily
