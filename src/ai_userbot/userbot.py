from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pytz
import qrcode
import io

from telethon import TelegramClient, events, types, errors
from telethon.tl.functions.channels import JoinChannelRequest

from .config import AppConfig
from .llm import LLMClient
from .database import ChatDatabase, MessageContext
from .persona import PersonaManager
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
        # Ensure session is saved in the sessions directory
        import os
        session_dir = "/app/sessions"
        os.makedirs(session_dir, exist_ok=True)
        session_path = os.path.join(session_dir, config.telegram.session_name)
        
        log.info(f"Session path: {session_path}")
        log.info(f"Session file exists: {os.path.exists(session_path + '.session')}")
        
        self.client = TelegramClient(
            session=session_path,
            api_id=config.telegram.api_id,
            api_hash=config.telegram.api_hash,
        )
        
        # State tracking
        self.active_chats: set = set()
        self.last_message_time: Dict[int, float] = {}
        self.messages_per_hour: Dict[int, List[float]] = {}
        self.is_typing: Dict[int, bool] = {}
        self.chat_rules_cache: Dict[int, Dict[str, bool]] = {}  # Cache analyzed rules

        # Cache for user info and entities to avoid repeated API calls
        self._user_info_cache: Optional[types.User] = None
        self._entity_cache: Dict[int, types.InputPeer] = {}
        self._message_cache: Dict[Tuple[int, int], types.Message] = {}  # (chat_id, message_id) -> message

        # Monitoring and statistics
        self._stats = {
            "messages_sent": 0,
            "messages_received": 0,
            "errors": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "api_calls": 0,
            "start_time": time.time()
        }

        # Setup handlers
        self._setup_handlers()

    async def get_me_cached(self):
        """Get cached user info, fetch from API if not cached"""
        if self._user_info_cache is None:
            self._record_cache_miss()
            self._record_api_call()
            self._user_info_cache = await self.client.get_me()
        else:
            self._record_cache_hit()
        return self._user_info_cache

    async def get_entity_cached(self, entity_id: int):
        """Get cached entity, fetch from API if not cached"""
        if entity_id not in self._entity_cache:
            self._record_cache_miss()
            try:
                self._record_api_call()
                entity = await self.client.get_entity(entity_id)
                self._entity_cache[entity_id] = entity
            except (errors.AuthKeyInvalidError, errors.SessionPasswordNeededError) as e:
                log.error(f"Authentication error getting entity {entity_id}: {e}")
                self._increment_stat("errors")
                # Don't cache auth errors
                return None
            except errors.FloodWaitError as e:
                log.warning(f"FloodWait getting entity {entity_id}: waiting {e.seconds}s")
                self._increment_stat("errors")
                await asyncio.sleep(e.seconds)
                # Retry once after waiting
                try:
                    self._record_api_call()
                    entity = await self.client.get_entity(entity_id)
                    self._entity_cache[entity_id] = entity
                except Exception as retry_e:
                    log.error(f"Failed to get entity {entity_id} after retry: {retry_e}")
                    return None
            except Exception as e:
                log.warning(f"Failed to get entity {entity_id}: {e}")
                self._increment_stat("errors")
                return None
        else:
            self._record_cache_hit()
        return self._entity_cache.get(entity_id)

    async def get_message_cached(self, chat_id: int, message_id: int):
        """Get cached message, fetch from API if not cached"""
        cache_key = (chat_id, message_id)
        if cache_key not in self._message_cache:
            self._record_cache_miss()
            try:
                self._record_api_call()
                message = await self.client.get_messages(chat_id, ids=message_id)
                if message:
                    self._message_cache[cache_key] = message
            except (errors.AuthKeyInvalidError, errors.SessionPasswordNeededError) as e:
                log.error(f"Authentication error getting message {chat_id}:{message_id}: {e}")
                self._increment_stat("errors")
                # Don't cache auth errors
                return None
            except errors.FloodWaitError as e:
                log.warning(f"FloodWait getting message {chat_id}:{message_id}: waiting {e.seconds}s")
                self._increment_stat("errors")
                await asyncio.sleep(e.seconds)
                # Retry once after waiting
                try:
                    self._record_api_call()
                    message = await self.client.get_messages(chat_id, ids=message_id)
                    if message:
                        self._message_cache[cache_key] = message
                except Exception as retry_e:
                    log.error(f"Failed to get message {chat_id}:{message_id} after retry: {retry_e}")
                    return None
            except Exception as e:
                log.warning(f"Failed to get message {chat_id}:{message_id}: {e}")
                self._increment_stat("errors")
                return None
        else:
            self._record_cache_hit()
        return self._message_cache.get(cache_key)

    def _parse_chat_identifier(self, chat_identifier):
        """Parse chat identifier from various formats"""
        if not chat_identifier:
            return None

        # Remove whitespace
        chat_identifier = chat_identifier.strip()

        # Handle username (starts with @)
        if chat_identifier.startswith('@'):
            return chat_identifier

        # Handle URL format (https://t.me/username)
        if chat_identifier.startswith('https://t.me/'):
            username = chat_identifier.replace('https://t.me/', '')
            return f'@{username}'

        # Handle numeric ID
        try:
            chat_id = int(chat_identifier)
            return chat_id
        except (ValueError, TypeError):
            pass

        # Handle username without @
        if chat_identifier and not chat_identifier.startswith('http'):
            return f'@{chat_identifier}'

        return None

    def _increment_stat(self, stat_name: str, value: int = 1):
        """Increment monitoring statistic"""
        self._stats[stat_name] += value

    def _record_api_call(self):
        """Record an API call for monitoring"""
        self._increment_stat("api_calls")

    def _record_cache_hit(self):
        """Record a cache hit"""
        self._increment_stat("cache_hits")

    def _record_cache_miss(self):
        """Record a cache miss"""
        self._increment_stat("cache_misses")

    def get_stats(self) -> Dict[str, any]:
        """Get current bot statistics"""
        uptime = time.time() - self._stats["start_time"]

        return {
            **self._stats,
            "uptime_seconds": uptime,
            "cache_hit_rate": (
                self._stats["cache_hits"] / (self._stats["cache_hits"] + self._stats["cache_misses"])
                if (self._stats["cache_hits"] + self._stats["cache_misses"]) > 0 else 0
            ),
            "messages_per_hour": (
                self._stats["messages_sent"] / (uptime / 3600)
                if uptime > 0 else 0
            ),
            "error_rate": (
                self._stats["errors"] / self._stats["api_calls"]
                if self._stats["api_calls"] > 0 else 0
            )
        }

    def _setup_handlers(self):
        """Setup message handlers"""
        # Handle messages in groups and personal messages
        @self.client.on(events.NewMessage(chats=None, incoming=True))
        async def on_message(event):
            self._increment_stat("messages_received")
            if event.is_group:
                await self._handle_group_message(event)
            elif self.config.telegram.respond_to_personal_messages and not event.is_group:
                await self._handle_personal_message(event)

        # Handle replies and mentions in groups
        @self.client.on(events.NewMessage(chats=None, incoming=True))
        async def on_mention_or_reply(event):
            if event.is_group and await self._is_mention_or_reply_to_bot(event):
                await self._handle_mention_or_reply(event)

        # Handle when bot is added to a new chat
        @self.client.on(events.ChatAction)
        async def on_chat_action(event):
            if event.user_added and event.user_id == (await self.get_me_cached()).id:
                log.info(f"Bot was added to chat {event.chat_id}")
                await self._handle_new_chat_joined(event.chat_id)
            elif event.user_kicked and event.user_id == (await self.get_me_cached()).id:
                log.info(f"Bot was removed from chat {event.chat_id}")
                await self._handle_chat_left(event.chat_id)

    async def _handle_personal_message(self, event):
        """Handle personal messages (DMs)"""
        if not self.config.telegram.respond_to_personal_messages:
            return

        message = event.message
        sender = await event.get_sender()

        # Handle different sender types (User vs Channel)
        if sender:
            if hasattr(sender, 'first_name'):
                # This is a User object (personal message)
                sender_name = f"{sender.first_name} {getattr(sender, 'last_name', '')}".strip()
                sender_id = sender.id
            else:
                # This is a Channel object or other type
                sender_name = getattr(sender, 'title', 'Channel')
                sender_id = getattr(sender, 'id', 0)
        else:
            sender_name = 'Unknown'
            sender_id = 0

        log.info(f"Received personal message from {sender_name}: {message.text[:50]}")

        # Check hourly limit for personal messages
        if not await self._check_personal_hourly_limit(sender_id):
            log.debug(f"Personal message limit reached for user {sender_id}")
            return

        # Store message context and update persona experience
        await self.db.add_message_context(
            chat_id=0,  # Personal messages don't have chat_id
            user_id=sender_id,
            username=sender.username if sender and hasattr(sender, 'username') else "",
            message_text=message.text or "",
            timestamp=message.date
        )

        # Update persona experience from personal interaction
        await self._update_persona_experience(message.text or "", is_personal=True)

        # Check if we should respond (simplified logic for personal messages)
        if await self._should_respond_to_personal(sender, message):
            # Simulate human-like delay for personal messages
            delay = random.uniform(*self.config.policy.reaction_delay_range)
            log.debug(f"Simulating {delay:.1f}s delay before responding to personal message")
            await asyncio.sleep(delay)

            # Generate response
            response = await self._generate_personal_response(message)

            if response:
                try:
                    await self.client.send_message(sender.id, response)
                    self._increment_stat("messages_sent")

                    # Log the response
                    await self.db.log_message(
                        chat_id=0,
                        user_id=0,
                        message_text=response,
                        is_bot_message=True
                    )

                    # Update persona experience from response
                    await self._update_persona_experience(response, is_personal=True)

                except Exception as e:
                    log.error(f"Error sending personal response: {e}")

    async def _is_mention_or_reply_to_bot(self, event) -> bool:
        """Check if message is a mention or reply to the bot"""
        message = event.message

        # Check if it's a reply to bot's message
        if message.reply_to_msg_id:
            try:
                reply_msg = await self.get_message_cached(event.chat_id, message.reply_to_msg_id)
                if reply_msg and reply_msg.from_id == (await self.get_me_cached()).id:
                    return True
            except Exception as e:
                log.debug(f"Could not check reply message: {e}")

        # Check if bot is mentioned in the message
        if message.text:
            bot_username = (await self.get_me_cached()).username
            if bot_username and f"@{bot_username}" in message.text:
                return True

        return False

    async def _handle_mention_or_reply(self, event):
        """Handle mentions and replies to the bot"""
        message = event.message
        chat_id = event.chat_id

        # AI-powered message analysis
        message_analysis = await self._analyze_message_tone(message, chat_id)

        # Check if it's spam (very short or repetitive)
        if self._is_potential_spam(message, message_analysis):
            log.debug(f"Ignoring potential spam in chat {chat_id}")
            return

        # Check if we should respond (enhanced with AI analysis)
        should_respond = await self._should_respond(chat_id, message, message_analysis)
        if not should_respond:
            return

        # Check hourly message limit for this chat
        if not await self._check_hourly_limit(chat_id):
            log.debug(f"Hourly limit reached for chat {chat_id}")
            return

        # Simulate human-like typing
        await self._simulate_human_behavior_with_message(chat_id, message)

        # Generate response
        response = await self._generate_response(chat_id, message)
        if not response:
            return

        # Send response
        try:
            await self.client.send_message(chat_id, response)
            self._increment_stat("messages_sent")

            # Log the response
            await self.db.log_message(
                chat_id=chat_id,
                user_id=0,
                message_text=response,
                is_bot_message=True
            )

            # Update persona experience from interaction
            await self._update_persona_experience(message.text or "", is_personal=False)
            await self._update_persona_experience(response, is_personal=False)

        except Exception as e:
            log.error(f"Error sending response to chat {chat_id}: {e}")

    def _is_potential_spam(self, message, message_analysis) -> bool:
        """Check if message looks like spam"""
        text = message.text or ""

        # Very short messages (less than 5 characters)
        if len(text.strip()) < 5:
            return True

        # Repetitive content
        if len(set(text.lower())) < len(text) * 0.3:  # Low character diversity
            return True

        # Too many mentions or links
        mention_count = text.count('@')
        link_count = text.count('http')

        if mention_count > 3 or link_count > 2:
            return True

        # AI analysis for spam detection
        if message_analysis.get("toxicity_level", 0) > 0.9:
            return True

        return False

    async def _update_persona_experience(self, text, is_personal=False):
        """Update persona experience from interactions"""
        try:
            # Extract topics and themes from the text
            topics = self._extract_topics_from_text(text)

            # Update persona knowledge base
            if hasattr(self.persona, 'knowledge_base'):
                for topic in topics:
                    if topic not in self.persona.knowledge_base:
                        self.persona.knowledge_base[topic] = 0
                    self.persona.knowledge_base[topic] += 1

            # Update conversation style preferences
            if hasattr(self.persona, 'conversation_styles'):
                # Analyze text for style indicators
                if len(text) > 50:  # Long messages
                    self.persona.conversation_styles["detailed"] = min(1.0, self.persona.conversation_styles.get("detailed", 0) + 0.1)
                elif len(text) < 20:  # Short messages
                    self.persona.conversation_styles["concise"] = min(1.0, self.persona.conversation_styles.get("concise", 0) + 0.1)

                # Analyze for emotional content
                positive_words = ["спасибо", "класс", "отлично", "замечательно", "рад", "счастлив"]
                negative_words = ["плохо", "ужасно", "ненавижу", "злюсь", "грустно"]

                if any(word in text.lower() for word in positive_words):
                    self.persona.conversation_styles["positive"] = min(1.0, self.persona.conversation_styles.get("positive", 0) + 0.05)
                elif any(word in text.lower() for word in negative_words):
                    self.persona.conversation_styles["empathetic"] = min(1.0, self.persona.conversation_styles.get("empathetic", 0) + 0.05)

            # Update interaction count
            if hasattr(self.persona, 'interaction_count'):
                self.persona.interaction_count += 1

            # Save updated persona to database if needed
            await self._save_persona_updates()

        except Exception as e:
            log.error(f"Error updating persona experience: {e}")

    def _extract_topics_from_text(self, text: str):
        """Extract topics and themes from text"""
        topics = []

        # Interest-related topics
        interest_keywords = {
            "йога": ["йога", "асана", "медитация", "пранаяма", "мантра"],
            "психология": ["психология", "эмоции", "мышление", "самоанализ"],
            "путешествия": ["путешествия", "поездка", "отпуск", "туризм"],
            "саморазвитие": ["саморазвитие", "личностный рост", "мотивация"]
        }

        text_lower = text.lower()
        for topic, keywords in interest_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                topics.append(topic)

        # Add general topics
        general_topics = ["работа", "семья", "друзья", "здоровье", "еда", "спорт", "музыка", "фильмы"]
        for topic in general_topics:
            if topic in text_lower:
                topics.append(topic)

        return list(set(topics))  # Remove duplicates

    async def _save_persona_updates(self):
        """Save updated persona data to database"""
        # This would save the updated persona knowledge to database
        # Implementation depends on how persona data is stored
        pass

    async def join_chats_by_list(self, chat_list):
        """Join multiple chats by their usernames or IDs"""
        joined_count = 0
        max_joins_per_session = 20  # Strict limit to avoid bans
        chats_to_process = min(len(chat_list), max_joins_per_session)

        log.info(f"Attempting to join up to {chats_to_process} out of {len(chat_list)} chats...")

        # Get current dialogs from Telegram API once at the beginning
        try:
            current_dialogs = await self.client.get_dialogs(limit=1000)
            current_chat_ids = {dialog.entity.id for dialog in current_dialogs}
            log.info(f"Found {len(current_chat_ids)} current dialogs in Telegram")
        except Exception as e:
            log.error(f"Could not get current dialogs: {e}")
            current_chat_ids = set()

        for i, chat_identifier in enumerate(chat_list[:chats_to_process]):
            try:
                # Parse chat identifier (username, URL, or numeric ID)
                parsed_identifier = self._parse_chat_identifier(chat_identifier)
                if not parsed_identifier:
                    log.warning(f"Could not parse chat identifier: {chat_identifier}")
                    continue

                # Add delay between join attempts to avoid flood wait
                if i > 0:
                    delay = random.uniform(3, 8)  # Increased delay to avoid bans
                    log.debug(f"Waiting {delay:.1f}s before next join attempt")
                    await asyncio.sleep(delay)

                log.info(f"Attempting to join chat: {parsed_identifier}")

                # Try to get chat entity
                try:
                    chat = await self.get_entity_cached(parsed_identifier)
                except errors.FloodWaitError as e:
                    log.warning(f"FloodWait for {e.seconds} seconds on get_entity")
                    if e.seconds > 60:  # If wait > 1 minute, skip this chat
                        log.info(f"Skipping chat {chat_identifier} - too long wait ({e.seconds}s)")
                        continue
                    await asyncio.sleep(e.seconds)
                    # Retry after waiting
                    try:
                        chat = await self.get_entity_cached(parsed_identifier)
                    except Exception as retry_e:
                        log.warning(f"Could not find chat {chat_identifier} even after waiting: {retry_e}")
                        continue
                except Exception as e:
                    log.warning(f"Could not find chat {chat_identifier}: {e}")
                    # Skip chats that don't exist or have invalid usernames
                    if "No user has" in str(e) or "not supported between instances" in str(e):
                        log.info(f"Skipping chat {chat_identifier} - invalid username or entity")
                        continue
                    else:
                        # Re-raise other exceptions
                        raise

                if not chat:
                    log.warning(f"Chat entity is None for {chat_identifier}")
                    continue

                # Check if already in this chat according to Telegram API
                if chat.id in current_chat_ids:
                    log.info(f"Already in chat {chat_identifier} according to Telegram API - skipping")
                    # Update database to reflect joined status
                    await self.db.add_chat(chat_id=chat.id, join_status='joined')
                    self.active_chats.add(chat.id)
                    continue

                # Check if chat has pending or rejected join status in database
                try:
                    existing_chat = await self.db.get_chat(chat.id)
                    if existing_chat and existing_chat.join_status in ['pending', 'rejected']:
                        log.info(f"Chat {chat_identifier} has status {existing_chat.join_status} in DB - skipping")
                        continue
                except Exception as db_e:
                    log.warning(f"Could not check chat status for {chat_id}: {db_e}")

                # Note: We skip pre-join criteria check as requested - analyze only after joining

                # Join chat
                try:
                    if chat is None:
                        log.error(f"Cannot join chat {chat_identifier} - entity is None")
                        continue
                    await self.client(JoinChannelRequest(chat.id))
                except errors.FloodWaitError as e:
                    log.warning(f"FloodWait for {e.seconds} seconds on JoinChannelRequest")
                    if e.seconds > 180:  # If wait > 3 minutes, skip this chat to avoid bans
                        log.info(f"Skipping chat {chat_identifier} - too long wait ({e.seconds}s) on join attempt")
                        # Mark as rejected to avoid future attempts
                        await self.db.add_chat(chat_id=chat.id, join_status='rejected')
                        continue
                    else:
                        log.info(f"Waiting {e.seconds} seconds before retrying to join {chat_identifier}")
                        await asyncio.sleep(e.seconds)
                        # Retry joining after waiting
                        try:
                            await self.client(JoinChannelRequest(chat.id))
                            log.info(f"Successfully joined chat after waiting: {getattr(chat, 'title', 'Unknown')}")
                            joined_count += 1
                        except Exception as retry_e:
                            log.error(f"Failed to join chat {chat_identifier} even after waiting: {retry_e}")
                            # Mark as rejected after failed retry
                            await self.db.add_chat(chat_id=chat.id, join_status='rejected')
                            continue
                except Exception as e:
                    error_msg = str(e).lower()
                    if "successfully requested to join" in error_msg or ("wait" in error_msg and "seconds" in error_msg):
                        # This is actually a successful join request that needs admin approval
                        log.info(f"Join request sent for {chat_identifier} - waiting for admin approval")
                        joined_count += 1

                        # Mark chat as pending approval in database
                        try:
                            await self.db.add_chat(
                                chat_id=chat.id,
                                title=getattr(chat, 'title', 'Unknown'),
                                username=getattr(chat, 'username', None),
                                members_count=getattr(chat, 'participants_count', 0),
                                join_status='pending'
                            )
                        except Exception as db_e:
                            log.warning(f"Could not mark chat {chat_id} as pending in database: {db_e}")

                        # Don't try to analyze immediately - wait for admin approval
                        continue
                    elif "chat for adults" in error_msg or "private" in error_msg:
                        log.info(f"Skipping private/adult chat {chat_identifier}")
                        continue
                    else:
                        log.error(f"Error joining chat {chat_identifier}: {e}")
                        continue

                # Analyze chat content
                try:
                    if chat is None:
                        log.error(f"Cannot analyze chat {chat_identifier} - entity is None")
                        continue

                    # Check if bot can send messages in this chat
                    try:
                        permissions = await self.client.get_permissions(chat.id)
                        if not permissions.send_messages:
                            log.info(f"Cannot send messages in chat {chat_identifier} - leaving")
                            await self.db.add_chat(
                                chat_id=chat.id,
                                title=getattr(chat, 'title', 'Unknown'),
                                username=getattr(chat, 'username', None),
                                members_count=getattr(chat, 'participants_count', 0),
                                ai_analysis={"should_stay": False, "reason": "Cannot send messages", "no_send_permission": True}
                            )
                            await self.client.delete_dialog(chat.id)
                            continue
                    except Exception as perm_e:
                        log.warning(f"Could not check permissions for chat {chat_identifier}: {perm_e}")

                    recent_messages = []
                    message_authors = []
                    async for message in self.client.iter_messages(chat.id, limit=20):  # Increased to 20 for better analysis
                        if message.text and message.sender_id:
                            recent_messages.append(message.text)
                            message_authors.append(message.sender_id)

                    # Deep analysis
                    chat_analysis = await self._analyze_chat_content_deep(chat, recent_messages, message_authors)

                    if chat_analysis["should_stay"]:
                        # Add to database
                        await self.db.add_chat(
                            chat_id=chat.id,
                            title=getattr(chat, 'title', 'Unknown'),
                            username=getattr(chat, 'username', None),
                            members_count=getattr(chat, 'participants_count', 0),
                            ai_analysis=chat_analysis
                        )

                        self.active_chats.add(chat.id)
                        log.info(f"Successfully joined and staying in chat: {getattr(chat, 'title', 'Unknown')}")
                    else:
                        log.info(f"Leaving chat {chat_identifier} after analysis: {chat_analysis['reason']}")
                        await self.client.delete_dialog(chat.id)
                except Exception as e:
                    log.warning(f"Error analyzing chat {chat_identifier}: {e}")
                    # If we can't analyze the chat, assume it's not suitable
                    log.info(f"Leaving chat {chat_identifier} due to analysis error")
                    await self.client.delete_dialog(chat.id)

            except Exception as e:
                log.error(f"Error joining chat {chat_identifier}: {e}")

        log.info(f"Successfully joined {joined_count} out of {len(chat_list)} chats")

    async def _find_and_join_test_chats(self):
        """Try to find and join some test chats if no active chats available"""
        try:
            # Try to find some public chats that might be suitable
            test_keywords = ["test", "testing", "demo", "пример", "тест"]

            for keyword in test_keywords[:3]:  # Limit to 3 attempts
                try:
                    dialogs = await self.client.get_dialogs(limit=20)

                    for dialog in dialogs:
                        if (dialog.is_group and not dialog.is_channel and
                            self._is_suitable_chat(dialog.entity) and
                            dialog.entity.id not in self.active_chats):

                            # Try to join
                            try:
                                await self.client(JoinChannelRequest(dialog.entity.id))

                                # Quick analysis
                                recent_messages = []
                                async for message in self.client.iter_messages(dialog.entity.id, limit=5):
                                    if message.text:
                                        recent_messages.append(message.text)

                                if recent_messages:  # Has some activity
                                    await self.db.add_chat(
                                        chat_id=dialog.entity.id,
                                        title=getattr(dialog.entity, 'title', 'Unknown'),
                                        username=getattr(dialog.entity, 'username', None),
                                        members_count=getattr(dialog.entity, 'participants_count', 0)
                                    )

                                    self.active_chats.add(dialog.entity.id)
                                    log.info(f"Joined test chat: {getattr(dialog.entity, 'title', 'Unknown')}")
                                    return  # Found and joined one

                            except Exception as e:
                                log.debug(f"Could not join test chat {dialog.entity.id}: {e}")

                except Exception as e:
                    log.debug(f"Error searching for test chats with keyword '{keyword}': {e}")

        except Exception as e:
            log.error(f"Error in find and join test chats: {e}")

    async def _join_predefined_chats_async(self):
        """Wrapper to run chat joining in background"""
        try:
            await self._join_predefined_chats()
        except Exception as e:
            log.error(f"Error in background chat joining: {e}")

    async def _join_predefined_chats(self):
        """Auto-join predefined chats on startup"""
        try:
            log.info(f"_join_predefined_chats called with {len(self.config.telegram.predefined_chats)} chats")
            if not self.config.telegram.predefined_chats:
                log.warning("No predefined chats to join")
                return

            log.info(f"Starting to join {len(self.config.telegram.predefined_chats)} predefined chats...")
            await asyncio.sleep(30)  # Wait for bot to fully start and API to settle
            log.info(f"Joining predefined chats: {self.config.telegram.predefined_chats}")
            await self.join_chats_by_list(self.config.telegram.predefined_chats)
            log.info("Finished joining predefined chats")
        except Exception as e:
            log.error(f"Error joining predefined chats: {e}", exc_info=True)

    async def _should_respond_to_personal(self, sender, message):
        """Determine if we should respond to a personal message"""
        # Don't respond to our own messages
        if sender and sender.id == (await self.get_me_cached()).id:
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

    async def _check_personal_hourly_limit(self, user_id):
        """Check if we've reached the hourly limit for personal messages to this user"""
        current_time = datetime.now()
        hour_start = current_time.replace(minute=0, second=0, microsecond=0)

        # Get messages sent to this user in the last hour
        recent_messages = await self.db.get_personal_messages_since(user_id, hour_start)

        return len(recent_messages) < self.config.telegram.max_personal_replies_per_hour

    async def _generate_personal_response(self, message):
        """Generate response to personal message"""
        try:
            context = f"Пользователь написал: {message.text or ''}"

            response = await self.llm.generate_response(
                system_prompt=self.persona.get_system_prompt(),
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
        # Load predefined chats from targets.txt if not set in config
        log.info(f"Current predefined chats in config: {len(self.config.telegram.predefined_chats)}")
        if not self.config.telegram.predefined_chats:
            targets_file = "/app/scripts/targets.txt"
            try:
                if os.path.exists(targets_file):
                    with open(targets_file, 'r', encoding='utf-8') as f:
                        chats = [line.strip() for line in f if line.strip()]
                        self.config.telegram.predefined_chats = chats
                        log.info(f"Loaded {len(chats)} predefined chats from targets.txt")
                        log.info(f"First few chats: {chats[:3]}")
                else:
                    log.warning(f"Targets file not found: {targets_file}")
            except Exception as e:
                log.error(f"Error loading targets.txt: {e}")
        else:
            log.info(f"Using {len(self.config.telegram.predefined_chats)} predefined chats from config")
        
        # Connect to Telegram
        await self.client.connect()

        # Check if already authorized (existing session works)
        try:
            is_authorized = await self.client.is_user_authorized()
            log.info(f"Authorization check result: {is_authorized}")
            
            if is_authorized:
                me = await self.client.get_me()
                log.info(f"Using existing session - authorized as: {me.first_name} {getattr(me, 'last_name', '')} (@{me.username})")
            else:
                log.warning("Session not authorized or corrupted. Starting QR login flow.")
        except Exception as e:
            log.error(f"Error checking authorization: {e}")
            is_authorized = False
            
        if not is_authorized:
            try:
                # Попробуем альтернативный метод генерации QR-кода
                # Используем прямой вывод для QR-кода, чтобы избежать форматирования логгера
                import sys
                print("\n" + "="*80, flush=True)
                print("🔷🔷🔷 ГЕНЕРАЦИЯ QR-КОДА ДЛЯ АВТОРИЗАЦИИ 🔷🔷🔷", flush=True)
                print("="*80, flush=True)
                print("Для авторизации используйте Telegram Desktop или мобильное приложение:", flush=True)
                print("1. Откройте Telegram → Настройки → Устройства → Подключить устройство", flush=True)
                print("2. Введите код авторизации или отсканируйте QR-код", flush=True)
                print("3. Дождитесь завершения авторизации", flush=True)
                print("="*80, flush=True)
                sys.stdout.flush()

                # Альтернативный способ - показать URL напрямую
                print("DEBUG: Вызываем client.qr_login()...", flush=True)
                sys.stdout.flush()
                qr_login = await self.client.qr_login()
                print("DEBUG: qr_login получен успешно", flush=True)
                print(f"📱 АВТОРИЗАЦИОННЫЙ URL: {qr_login.url}", flush=True)
                print("="*80, flush=True)
                sys.stdout.flush()

                # Генерируем QR-код
                try:
                    import qrcode
                    qr = qrcode.QRCode(
                        version=1,
                        error_correction=qrcode.constants.ERROR_CORRECT_L,
                        box_size=1,
                        border=2,
                    )
                    qr.add_data(qr_login.url)
                    qr.make(fit=True)

                    # Создаем ASCII QR-код
                    print("\n📱 QR-КОД ДЛЯ СКАНИРОВАНИЯ:", flush=True)
                    print("", flush=True)
                    matrix = qr.get_matrix()
                    for row in matrix:
                        line = ""
                        for cell in row:
                            line += "██" if cell else "  "
                        print(line, flush=True)
                    print("", flush=True)
                    sys.stdout.flush()
                    
                except Exception as e:
                    print(f"Не удалось сгенерировать QR-код: {e}", flush=True)
                    
                print("📱 ДЛЯ АВТОРИЗАЦИИ:", flush=True)
                print("1. Отсканируйте QR-код выше ИЛИ", flush=True)
                print("2. Скопируйте URL и откройте в браузере", flush=True)
                print("3. Войдите в аккаунт", flush=True)
                print("4. Дождитесь завершения авторизации", flush=True)

                print("⏰ ОЖИДАНИЕ АВТОРИЗАЦИИ... (до 30 секунд) ⏰", flush=True)
                print("="*80 + "\n", flush=True)
                sys.stdout.flush()

                user = await qr_login.wait(timeout=30)
                print(f"✅ УСПЕШНАЯ АВТОРИЗАЦИЯ: {user.first_name} {getattr(user, 'last_name', '')}")
                log.info(f"Successfully logged in as {user.first_name} {getattr(user, 'last_name', '')}")
                
                # Явно сохраняем сессию
                self.client.session.save()
                log.info("Session saved successfully")

            except asyncio.TimeoutError:
                log.error("❌ Таймаут авторизации. Перезапустите бота.")
                await self.stop()
                return
            except Exception as e:
                log.error(f"❌ Ошибка авторизации: {e}")
                log.error("Перезапустите бота для повторной попытки.")
                await self.stop()
                return

        log.info("UserBot started successfully")

        # Load previously active chats from database
        active_chats = await self.db.get_active_chats()
        self.active_chats = {chat.chat_id for chat in active_chats}

        # Sync active chats status with Telegram API
        await self._sync_all_active_chats_with_telegram()

        # Start background tasks
        asyncio.create_task(self._chat_discovery_loop())
        asyncio.create_task(self._cleanup_old_messages())
        asyncio.create_task(self._activity_scheduler())

        # Auto-join predefined chats if enabled (in background)
        if self.config.telegram.auto_join_predefined_chats and self.config.telegram.predefined_chats:
            # Run chat joining in background to not block main functionality
            asyncio.create_task(self._join_predefined_chats_async())
    
    async def stop(self):
        """Stop the userbot"""
        await self.client.disconnect()
        log.info("UserBot stopped")

    async def _analyze_chat_content_after_joining(self, chat_id, chat):
        """Analyze chat content after joining (for admin-approved chats)"""
        try:
            # Check if bot can send messages in this chat
            try:
                permissions = await self.client.get_permissions(chat_id)
                if not permissions.send_messages:
                    log.info(f"Cannot send messages in chat {chat_id} - leaving")
                    await self.db.add_chat(
                        chat_id=chat_id,
                        title=getattr(chat, 'title', 'Unknown'),
                        username=getattr(chat, 'username', None),
                        members_count=getattr(chat, 'participants_count', 0),
                        ai_analysis={"should_stay": False, "reason": "Cannot send messages", "no_send_permission": True}
                    )
                    await self.client.delete_dialog(chat_id)
                    return False
            except Exception as perm_e:
                log.warning(f"Could not check permissions for chat {chat_id}: {perm_e}")

            # Get recent messages for analysis
            recent_messages = []
            message_authors = []
            try:
                async for message in self.client.iter_messages(chat_id, limit=20):
                    if message.text and message.sender_id:
                        recent_messages.append(message.text)
                        message_authors.append(message.sender_id)
            except Exception as e:
                log.warning(f"Could not get messages for analysis in chat {chat_id}: {e}")
                # If we can't get messages, assume chat is not suitable
                await self.client.delete_dialog(chat_id)
                return False

            # Deep analysis
            chat_analysis = await self._analyze_chat_content_deep(chat, recent_messages, message_authors)

            if chat_analysis["should_stay"]:
                log.info(f"Chat {chat_id} passed content analysis - staying")
                return True
            else:
                log.info(f"Chat {chat_id} failed content analysis: {chat_analysis['reason']} - leaving")
                await self.client.delete_dialog(chat_id)
                return False

        except Exception as e:
            log.error(f"Error analyzing chat {chat_id} after joining: {e}")
            # If we can't analyze the chat, leave it
            try:
                await self.client.delete_dialog(chat_id)
            except:
                pass
            return False

    async def _sync_all_active_chats_with_telegram(self):
        """Sync all active chats status with Telegram API dialogs"""
        try:
            log.info("Syncing active chats status with Telegram API...")
            # Get current dialogs from Telegram API
            dialogs = await self.client.get_dialogs(limit=1000)

            # Create set of chat IDs from Telegram dialogs
            telegram_chat_ids = {dialog.entity.id for dialog in dialogs}

            # Get all chats from database that we think are active
            db_active_chats = await self.db.get_active_chats()

            for db_chat in db_active_chats:
                chat_id = db_chat.chat_id

                if chat_id in telegram_chat_ids:
                    # Chat is in both database and Telegram dialogs - we're really joined
                    if db_chat.join_status != 'joined':
                        await self.db.add_chat(chat_id=chat_id, join_status='joined')
                        log.debug(f"Updated chat {chat_id} status to 'joined' - confirmed in Telegram")
                else:
                    # Chat is in database but not in Telegram dialogs - we left or were removed
                    if db_chat.join_status == 'joined':
                        await self.db.add_chat(chat_id=chat_id, join_status='rejected')
                        log.debug(f"Updated chat {chat_id} status to 'rejected' - not in Telegram dialogs")
                        # Remove from active chats
                        self.active_chats.discard(chat_id)

            log.info(f"Synced {len(db_active_chats)} active chats with Telegram API")

        except Exception as e:
            log.error(f"Could not sync active chats with Telegram API: {e}")

    async def _sync_chat_status_with_telegram(self, chat):
        """Sync chat status with Telegram API dialogs"""
        try:
            # Get current dialogs from Telegram API (cached if possible)
            dialogs = await self.client.get_dialogs(limit=1000)  # Get all dialogs

            # Check if this chat is in our active dialogs
            chat_in_dialogs = any(dialog.entity.id == chat.id for dialog in dialogs)

            # Get current status from database
            existing_chat = await self.db.get_chat(chat.id)

            if chat_in_dialogs:
                # Chat is in our dialogs - we're joined
                if existing_chat and existing_chat.join_status != 'joined':
                    # Update database to reflect joined status
                    await self.db.add_chat(
                        chat_id=chat.id,
                        join_status='joined'
                    )
                    log.debug(f"Updated chat {chat.id} status to 'joined' based on Telegram API")
                return True  # We're already in this chat
            else:
                # Chat is not in our dialogs
                if existing_chat and existing_chat.join_status == 'joined':
                    # We think we're joined but Telegram API says we're not
                    await self.db.add_chat(
                        chat_id=chat.id,
                        join_status='rejected'  # Or handle as left chat
                    )
                    log.debug(f"Updated chat {chat.id} status to 'rejected' - not in Telegram dialogs")
                return False  # We're not in this chat

        except Exception as e:
            log.warning(f"Could not sync chat status for {chat.id}: {e}")
            return False  # Assume not in chat if we can't check

    async def _handle_new_chat_joined(self, chat_id):
        """Handle when bot is added to a new chat (after admin approval)"""
        try:
            # Get chat info
            chat = await self.get_entity_cached(chat_id)
            if not chat:
                return

            log.info(f"Bot was approved and added to chat: {getattr(chat, 'title', 'Unknown')}")

            # Update join status to 'joined' in database
            try:
                await self.db.add_chat(
                    chat_id=chat_id,
                    title=getattr(chat, 'title', 'Unknown'),
                    username=getattr(chat, 'username', None),
                    members_count=getattr(chat, 'participants_count', 0),
                    join_status='joined'
                )
            except Exception as db_e:
                log.warning(f"Could not update join status for chat {chat_id}: {db_e}")

            # Analyze chat content after joining (post-approval analysis)
            should_stay = await self._analyze_chat_content_after_joining(chat_id, chat)

            if should_stay:
                # Analyze chat rules
                try:
                    pinned = await self._get_pinned_messages(chat_id)
                    rules = self.rules_analyzer.analyze_chat_rules(chat, pinned)
                    self.chat_rules_cache[chat_id] = rules
                except Exception as e:
                    log.warning(f"Could not analyze rules for chat {chat_id}: {e}")
                    rules = {}

                # Update database with analysis results
                await self.db.add_chat(
                    chat_id=chat_id,
                    title=getattr(chat, 'title', 'Unknown'),
                    username=getattr(chat, 'username', None),
                    members_count=getattr(chat, 'participants_count', 0),
                    ai_analysis={"should_stay": True, "reason": "Passed post-approval analysis"},
                    is_active=True
                )

                self.active_chats.add(chat_id)
                log.info(f"Successfully joined and staying in chat: {getattr(chat, 'title', 'Unknown')}")

        except Exception as e:
            log.error(f"Error handling new chat {chat_id}: {e}")

    async def _handle_chat_left(self, chat_id):
        """Handle when bot leaves a chat"""
        self.active_chats.discard(chat_id)
        await self.db.deactivate_chat(chat_id)
        log.info(f"Left chat {chat_id}")

    def _is_suitable_chat(self, chat):
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
        if participants_count and 50 <= participants_count <= 50000:  # Reasonable size range
            return True

        return False

    def _generate_search_variations(self, keyword):
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

    async def _analyze_chat_content(self, chat) -> dict:
        """Initial AI analysis of chat before joining"""
        try:
            # Basic info analysis
            title = getattr(chat, 'title', '')
            description = getattr(chat, 'about', '')
            username = getattr(chat, 'username', '')
            participants_count = getattr(chat, 'participants_count', 0)

            # Prepare analysis prompt
            analysis_prompt = f"""
            Проанализируй этот Telegram чат и определи, подходит ли он для молодой женщины по имени Анна (28 лет, интересуется йогой, медитацией, психологией, саморазвитием, путешествиями).

            Информация о чате:
            - Название: {title}
            - Описание: {description}
            - Username: @{username}
            - Количество участников: {participants_count}

            Критерии оценки:
            1. Релевантность интересам Анны (йога, медитация, психология, путешествия)
            2. Женская аудитория (женские чаты, мамочки, подруги)
            3. Положительная атмосфера (без агрессии, спама, политики)
            4. Активность (не слишком маленький чат)

            Верни JSON в формате:
            {{
                "should_join": true/false,
                "relevance_score": 0.0-1.0,
                "reason": "краткое объяснение",
                "confidence": 0.0-1.0,
                "chat_type": "women/travel/local/general"
            }}
            """

            response = await self.llm.generate_response(
                system_prompt="Ты эксперт по анализу Telegram чатов. Оценивай строго и честно.",
                user_message=analysis_prompt,
                chat_context={"analysis_type": "pre_join"}
            )

            # Parse JSON response (simplified parsing)
            import json
            try:
                result = json.loads(response)
                return result
            except:
                # Fallback if JSON parsing fails
                return {
                    "should_join": False,
                    "relevance_score": 0.0,
                    "reason": "Не удалось проанализировать",
                    "confidence": 0.0,
                    "chat_type": "unknown"
                }

        except Exception as e:
            log.error(f"Error analyzing chat {chat.id}: {e}")
            return {
                "should_join": False,
                "relevance_score": 0.0,
                "reason": f"Ошибка анализа: {e}",
                "confidence": 0.0,
                "chat_type": "error"
            }

    async def _analyze_chat_content_deep(self, chat, recent_messages, message_authors=None):
        """Deep AI analysis of chat content after joining"""
        try:
            # Combine recent messages for analysis
            content_sample = "\n".join(recent_messages[:10])  # First 10 messages

            if not content_sample.strip():
                return {
                    "should_stay": True,
                    "relevance_score": 0.7,
                    "reason": "Пустой чат, даем шанс",
                    "toxicity_level": 0.0,
                    "activity_level": 0.0,
                    "forbidden_content": 0.0,
                    "illegal_content": 0.0
                }

            # Check message distribution by authors
            author_dominance = 0.0
            if message_authors and len(message_authors) >= 5:  # Need at least 5 messages for meaningful analysis
                from collections import Counter
                author_counts = Counter(message_authors)
                total_messages = len(message_authors)
                max_author_count = max(author_counts.values())
                author_dominance = max_author_count / total_messages

                if author_dominance > 0.5:  # More than 50% from one author
                    return {
                        "should_stay": False,
                        "relevance_score": 0.0,
                        "toxicity_level": 0.0,
                        "activity_level": 0.0,
                        "forbidden_content": 0.0,
                        "illegal_content": 0.0,
                        "author_dominance": author_dominance,
                        "reason": f"Один автор написал {author_dominance:.1%} сообщений - доминирование"
                    }

            # Prepare deep analysis prompt
            deep_analysis_prompt = f"""
            Проанализируй содержимое этого Telegram чата и дай подробную оценку.

            Название чата: {getattr(chat, 'title', 'Unknown')}
            Недавние сообщения:
            {content_sample}

            КРИТИЧНЫЕ КРИТЕРИИ ОТСЕВА (если любой из них > 0.8, чат НЕ ПОДХОДИТ):
            1. Запрещенный контент (18+, порно, секс-услуги, наркотики, оружие, насилие, терроризм) - 0-1
            2. Противозаконный контент (мошенничество, пирамиды, спам, реклама запрещенных веществ) - 0-1
            3. Доминирование одного автора (больше 50% сообщений от одного аккаунта) - 0-1

            ЕСЛИ forbidden_content > 0.8 ИЛИ illegal_content > 0.8 ИЛИ author_dominance > 0.5, то should_stay = false

            Дополнительные критерии:
            4. Релевантность интересам (йога, медитация, психология, путешествия, духовность) - 0-1
            5. Аудитория (женщины, мамы, подруги) - 0-1
            6. Атмосфера (дружественная, позитивная, поддерживающая) - 0-1
            7. Уровень токсичности (хамство, грубость, агрессия) - 0-1
            8. Активность (живое общение, обсуждения) - 0-1

            Верни JSON в формате:
            {{
                "should_stay": true/false,
                "relevance_score": 0.0-1.0,
                "toxicity_level": 0.0-1.0,
                "activity_level": 0.0-1.0,
                "forbidden_content": 0.0-1.0,
                "illegal_content": 0.0-1.0,
                "author_dominance": 0.0-1.0,
                "mood": "positive/neutral/negative",
                "reason": "подробное объяснение решения"
            }}

            ЕСЛИ forbidden_content > 0.8 ИЛИ illegal_content > 0.8, то should_stay = false
            """

            response = await self.llm.generate_response(
                system_prompt="Ты эксперт по анализу социальных взаимодействий в Telegram. Будь максимально честным и объективным.",
                user_message=deep_analysis_prompt,
                chat_context={"analysis_type": "post_join"}
            )

            # Parse JSON response
            import json
            try:
                result = json.loads(response)
                return result
            except:
                # Fallback analysis
                return {
                    "should_stay": True,
                    "relevance_score": 0.5,
                    "toxicity_level": 0.0,
                    "activity_level": 0.5,
                    "forbidden_content": 0.0,
                    "illegal_content": 0.0,
                    "author_dominance": 0.0,
                    "mood": "neutral",
                    "reason": "Не удалось проанализировать содержимое"
                }

        except Exception as e:
            log.error(f"Error in deep analysis for chat {chat.id}: {e}")
            return {
                "should_stay": False,
                "relevance_score": 0.0,
                "toxicity_level": 1.0,
                "activity_level": 0.0,
                "forbidden_content": 1.0,
                "illegal_content": 1.0,
                "author_dominance": 1.0,
                "mood": "error",
                "reason": f"Ошибка анализа содержимого: {e}"
            }
    
    def _get_chat_category(self, chat_title):
        """Determine chat category based on title"""
        title_lower = chat_title.lower() if chat_title else ""
        
        for category, keywords in self.config.telegram.chat_categories.items():
            if any(keyword in title_lower for keyword in keywords):
                return category
        
        return "general"
    
    def _is_active_time(self):
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
    
    async def _handle_group_message(self, event):
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

        # AI-powered message analysis
        message_analysis = await self._analyze_message_tone(message, chat_id)

        # Ignore toxic or rude messages
        if message_analysis["toxicity_level"] > 0.7:
            log.debug(f"Ignoring toxic message in chat {chat_id}")
            return

        # Check if we should respond (enhanced with AI analysis)
        should_respond = await self._should_respond(chat_id, message, message_analysis)
        if not should_respond:
            return

        # Check hourly message limit for this chat
        if not await self._check_hourly_limit(chat_id):
            log.debug(f"Hourly limit reached for chat {chat_id}")
            return

        # Simulate typing with random delay
        await self._simulate_human_behavior_with_message(chat_id, message)

        # Generate response
        response = await self._generate_response(chat_id, message)
        if not response:
            return

        # Send response
        try:
            await self.client.send_message(chat_id, response)
            self._increment_stat("messages_sent")

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

    async def _should_respond(self, chat_id, message, message_analysis=None):
        """Decide if bot should respond to the message (enhanced with AI analysis)"""
        # Check rate limits
        if not self._check_rate_limits(chat_id):
            return False

        # Check forbidden terms
        if message.text and any(term.lower() in message.text.lower() for term in self.config.policy.forbidden_terms):
            return False

        # Use AI analysis for better decision making
        if message_analysis:
            # AI already analyzed toxicity, use its recommendation
            relevance_score = message_analysis.get("relevance_score", 0.5)
            toxicity_level = message_analysis.get("toxicity_level", 0.0)

            # Don't respond to highly toxic messages
            if toxicity_level > 0.8:
                return False

            # Adjust response probability based on AI analysis
            base_probability = 0.3  # Base probability

            # Boost for relevant messages
            if relevance_score > 0.7:
                base_probability *= 2.0
            elif relevance_score > 0.5:
                base_probability *= 1.5

            # Reduce for toxic messages
            if toxicity_level > 0.3:
                base_probability *= 0.5

            return random.random() < base_probability

        # Fallback to old logic if AI analysis fails
        try:
            chat = await self.get_entity_cached(chat_id)
            chat_title = chat.title if hasattr(chat, 'title') else ""
        except:
            chat_title = ""
        chat_category = self._get_chat_category(chat_title)

        # Get recent context
        context = await self.db.get_recent_messages(chat_id, limit=10)

        # Calculate relevance score
        relevance = await self._calculate_relevance(message, context)

        # Adjust chance based on chat category
        base_chance = self.config.policy.response_probability.get(chat_category, 0.5)

        # Boost if message mentions persona interests
        if any(interest in (message.text or "").lower() for interest in self.persona.interests):
            base_chance *= 1.5

        # Boost if replied to bot
        if message.reply_to_msg_id:
            reply_msg = await self.get_message_cached(chat_id, message.reply_to_msg_id)
            if reply_msg.from_id == (await self.get_me_cached()).id:
                base_chance *= 2.0

        # Random decision based on chance
            return random.random() < base_chance and relevance > self.config.policy.relevance_threshold

    async def _analyze_message_tone(self, message, chat_id):
        """Analyze message tone and relevance using AI"""
        try:
            message_text = message.text or ""

            # Quick check for obviously toxic content
            toxic_indicators = ["сука", "пидор", "хуй", "ебан", "fuck", "shit", "bitch"]
            toxicity_level = sum(1 for indicator in toxic_indicators if indicator.lower() in message_text.lower()) / len(toxic_indicators)

            # AI analysis for more nuanced detection
            analysis_prompt = f"""
            Проанализируй это сообщение в Telegram чате и оцени его тон и релевантность.

            Сообщение: "{message_text}"

            Оцени по шкале 0-1:
            1. Токсичность (хамство, грубость, агрессия)
            2. Релевантность интересам Анны (йога, медитация, психология, путешествия)
            3. Положительность тона (дружественный, позитивный)

            Верни JSON в формате:
            {{
                "toxicity_level": 0.0-1.0,
                "relevance_score": 0.0-1.0,
                "tone_score": 0.0-1.0,
                "should_ignore": true/false,
                "reason": "краткое объяснение"
            }}
            """

            response = await self.llm.generate_response(
                system_prompt="Ты эксперт по анализу социальных взаимодействий. Будь максимально объективным.",
                user_message=analysis_prompt,
                chat_context={"analysis_type": "message_tone"}
            )

            # Parse JSON response
            import json
            try:
                result = json.loads(response)
                # Override toxicity with quick check if it's obviously toxic
                if toxicity_level > 0.5:
                    result["toxicity_level"] = max(result.get("toxicity_level", 0), toxicity_level)
                return result
            except:
                # Fallback if JSON parsing fails
                return {
                    "toxicity_level": toxicity_level,
                    "relevance_score": 0.5,
                    "tone_score": 0.5,
                    "should_ignore": toxicity_level > 0.7,
                    "reason": "Не удалось проанализировать"
                }

        except Exception as e:
            log.error(f"Error analyzing message tone: {e}")
            return {
                "toxicity_level": 0.0,
                "relevance_score": 0.5,
                "tone_score": 0.5,
                "should_ignore": False,
                "reason": f"Ошибка анализа: {e}"
            }

    def _check_rate_limits(self, chat_id):
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

    async def _simulate_human_behavior_with_message(self, chat_id: int, message: Message):
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

    async def _generate_response(self, chat_id, message):
        """Generate a natural response using LLM"""
        # Get recent context for human-like response
        context_messages = await self.db.get_recent_messages(chat_id, limit=5)

        # Build context string
        context = self._build_message_context(context_messages)
        context = f"Контекст разговора:\n{context}\n\nСообщение пользователя: {message.text or ''}"

        # Generate human-like response
        return await self._generate_human_like_response(context, chat_id)

    async def _calculate_relevance(self, message, context):
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
        # Wait before starting discovery to avoid immediate flood
        await asyncio.sleep(300)  # Wait 5 minutes after startup
        
        while True:
            try:
                # Find new chats
                new_chats = await self._find_new_chats()
                
                for chat in new_chats:
                    try:
                        # First, analyze chat content using AI before joining
                        chat_analysis = await self._analyze_chat_content(chat)

                        if not chat_analysis["should_join"]:
                            log.info(f"Skipping chat {chat.title}: {chat_analysis['reason']}")
                            continue

                        # Join chat
                        await self.client(JoinChannelRequest(chat.id))

                        # Get recent messages for deeper analysis
                        recent_messages = []
                        async for message in self.client.iter_messages(chat.id, limit=20):
                            if message.text:
                                recent_messages.append(message.text)
                            if len(recent_messages) >= 20:
                                break

                        # Analyze chat content and rules
                        chat_content_analysis = await self._analyze_chat_content_deep(chat, recent_messages)
                        rules = self.rules_analyzer.analyze_chat_rules(chat, [])

                        # Update analysis with content analysis
                        chat_analysis.update(chat_content_analysis)
                        chat_analysis["rules"] = rules

                        # Final decision based on content analysis
                        if not chat_analysis["should_stay"]:
                            log.info(f"Leaving chat {chat.title} after content analysis: {chat_analysis['reason']}")
                            await self.client.delete_dialog(chat.id)
                            continue

                        # Add to database with AI analysis
                        await self.db.add_chat(
                            chat_id=chat.id,
                            title=getattr(chat, 'title', None),
                            username=getattr(chat, 'username', None),
                            members_count=getattr(chat, 'participants_count', 0),
                            ai_analysis=chat_analysis
                        )

                        self.active_chats.add(chat.id)
                        self.chat_rules_cache[chat.id] = rules
                        log.info(f"Joined chat: {chat.title} (ID: {chat.id}) - AI Score: {chat_analysis['relevance_score']:.2f}")

                    except (ChatAdminRequired, UserBannedInChannel) as e:
                        log.warning(f"Could not join chat {chat.id}: {e}")
                    except Exception as e:
                        log.error(f"Error joining chat {chat.id}: {e}")
                
            except Exception as e:
                log.error(f"Chat discovery error: {e}")
            
            # Sleep with jitter
            try:
                sleep_time = self.config.policy.chat_discovery_interval + random.uniform(-300, 300)
                await asyncio.sleep(sleep_time)
            except AttributeError:
                # Fallback if config.policy.chat_discovery_interval is not found
                sleep_time = 300 + random.uniform(-150, 150) # Default to 300 seconds with jitter
                await asyncio.sleep(sleep_time)

    async def _find_new_chats(self):
        """Find new open chats based on keywords"""
        new_chats = []
        
        for keyword in self.config.telegram.search_keywords:
            try:
                # Enhanced chat search using multiple methods
                chats_found = set()

                # Method 1: Search existing dialogs (skip if not authorized)
                try:
                    # Check if client is authorized before getting dialogs
                    if await self.client.is_user_authorized():
                        try:
                            dialogs = await self.client.get_dialogs(limit=100)
                        except errors.FloodWaitError as e:
                            log.warning(f"FloodWait for {e.seconds} seconds on get_dialogs")
                            await asyncio.sleep(e.seconds)
                            continue

                        for dialog in dialogs:
                            if (dialog.is_group and not dialog.is_channel and
                                self._is_suitable_chat(dialog.entity) and
                                dialog.entity.id not in self.active_chats):

                                chats_found.add(dialog.entity.id)
                                new_chats.append(dialog.entity)
                                log.info(f"Found chat via dialogs: {getattr(dialog.entity, 'title', 'Unknown')} (@{getattr(dialog.entity, 'username', 'N/A')})")
                    else:
                        log.debug(f"Client not authorized for dialogs search with keyword '{keyword}'")

                except (errors.AuthKeyInvalidError, errors.SessionPasswordNeededError) as e:
                    log.error(f"Authentication failed for dialogs search: {e}")
                    break
                except Exception as e:
                    log.warning(f"Dialogs search failed for '{keyword}': {e}")

                try:
                    # Method 2: Try to find public chats by username patterns
                    if keyword.startswith('@'):
                        try:
                            entity = await self.get_entity_cached(keyword)
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
        
        return new_chats[:self.config.policy.max_new_chats_per_cycle]

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
                    else:
                        log.info(f"No active chats available. Messages sent today: {messages_sent_today}/{self.config.policy.daily_message_target}")
                        # If no active chats, try to find and join some
                        await self._find_and_join_test_chats()

                # Sleep until next activity check (use configured interval)
                try:
                    sleep_time = self.config.policy.chat_discovery_interval + random.uniform(-300, 300)  # ±5 minutes jitter
                    await asyncio.sleep(max(600, sleep_time))  # Minimum 10 minutes
                except AttributeError:
                    # Fallback if config.policy.chat_discovery_interval is not found
                    sleep_time = 600 + random.uniform(-300, 300) # Default to 600 seconds with jitter
                    await asyncio.sleep(sleep_time)

            except Exception as e:
                log.error(f"Error in activity scheduler: {e}")
                await asyncio.sleep(1800)

    def _is_active_time(self, current_time):
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
                    self._increment_stat("messages_sent")

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

    async def _generate_human_like_response(self, context, chat_id):
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

    def _add_human_variations(self, text):
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

    def _add_typo(self, text):
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

    async def _check_hourly_limit(self, chat_id):
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
