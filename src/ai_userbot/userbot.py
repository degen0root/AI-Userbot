from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
import pytz

from pyrogram import Client, filters, enums
from pyrogram.types import Message, Chat
from pyrogram.errors import FloodWait, ChatAdminRequired, UserBannedInChannel

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
        
        # Pyrogram client
        self.client = Client(
            name=config.telegram.session_name,
            api_id=config.telegram.api_id,
            api_hash=config.telegram.api_hash,
            phone_number=config.telegram.phone_number
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
        @self.client.on_message(filters.group & filters.text & ~filters.me)
        async def on_group_message(client: Client, message: Message):
            await self._handle_group_message(message)
    
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
        await self.client.stop()
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
        else:
            if current_hour >= sleep_time or current_hour < wake_up:
                return random.random() < self.config.policy.night_messages_probability
        
        # Check active periods
        for period_name, hours in self.config.policy.active_hours.items():
            if isinstance(hours, list) and len(hours) == 2:
                if hours[0] <= current_hour < hours[1]:
                    # Weekend activity reduction
                    if now.weekday() >= 5:  # Saturday or Sunday
                        return random.random() < self.config.policy.weekend_activity_multiplier
                    return True
        
        return False
    
    async def _handle_group_message(self, message: Message):
        """Handle incoming group messages"""
        chat_id = message.chat.id
        
        # Skip if chat is not in our active list
        if chat_id not in self.active_chats:
            return
        
        # Check if we're in active hours
        if not self._is_active_time():
            log.debug(f"Skipping message - outside active hours")
            return
        
        # Store message context for future reference
        await self.db.add_message_context(
            chat_id=chat_id,
            user_id=message.from_user.id if message.from_user else 0,
            username=message.from_user.username if message.from_user else "",
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
            await message.reply_text(response)
            
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
            log.warning(f"FloodWait for {e.x} seconds in chat {chat_id}")
            await asyncio.sleep(e.x)
        except Exception as e:
            log.error(f"Error sending message to chat {chat_id}: {e}")
    
    async def _should_respond(self, chat_id: int, message: Message) -> bool:
        """Decide if bot should respond to the message"""
        # Check rate limits
        if not self._check_rate_limits(chat_id):
            return False
        
        # Check forbidden terms
        if any(term.lower() in message.text.lower() for term in self.config.policy.forbidden_terms):
            return False
        
        # Get chat category
        chat_title = message.chat.title if message.chat else ""
        chat_category = self._get_chat_category(chat_title)
        
        # Get recent context
        context = await self.db.get_recent_messages(chat_id, limit=10)
        
        # Calculate relevance score
        relevance = await self._calculate_relevance(message, context)
        
        # Adjust chance based on chat category
        if chat_category == "travel":
            # Higher engagement in travel chats (for karma farming)
            chance = relevance * 0.25  # Max 25% chance
        elif chat_category == "women":
            # Normal engagement in women chats
            chance = relevance * 0.15  # Max 15% chance
        else:
            # Lower engagement in general chats
            chance = relevance * 0.10  # Max 10% chance
        
        return random.random() < chance
    
    def _check_rate_limits(self, chat_id: int) -> bool:
        """Check if we're within rate limits"""
        now = time.time()
        
        # Check minimum gap
        last_time = self.last_message_time.get(chat_id, 0)
        if now - last_time < self.config.policy.min_gap_seconds_per_chat:
            return False
        
        # Check hourly limit
        if chat_id in self.messages_per_hour:
            # Remove old entries
            hour_ago = now - 3600
            self.messages_per_hour[chat_id] = [
                t for t in self.messages_per_hour[chat_id] if t > hour_ago
            ]
            
            if len(self.messages_per_hour[chat_id]) >= self.config.policy.max_replies_per_hour_per_chat:
                return False
        
        return True
    
    async def _calculate_relevance(self, message: Message, context: List[MessageContext]) -> float:
        """Calculate how relevant the message is to our persona interests"""
        text = message.text.lower()
        
        # Check for direct mentions or replies
        if message.reply_to_message and message.reply_to_message.from_user:
            if message.reply_to_message.from_user.is_self:
                return 0.9  # High relevance if someone replies to us
        
        # Check for persona interests
        relevance_score = 0.0
        for interest in self.config.persona.interests:
            if interest.lower() in text:
                relevance_score += 0.3
        
        # Check conversation flow
        if context:
            # If we recently participated, slightly higher chance to continue
            recent_our_messages = [m for m in context[-5:] if m.user_id == 0]  # 0 = bot messages
            if recent_our_messages:
                relevance_score += 0.2
        
        return min(relevance_score, 1.0)
    
    async def _simulate_human_behavior(self, chat_id: int, message: Message):
        """Simulate human-like behavior before responding"""
        # Random initial delay
        delay = random.uniform(*self.config.policy.reaction_delay_range)
        await asyncio.sleep(delay)
        
        # Mark as typing
        self.is_typing[chat_id] = True
        try:
            await self.client.send_chat_action(chat_id, enums.ChatAction.TYPING)
            
            # Calculate typing duration based on response length
            # We'll estimate this, actual duration will depend on generated response
            typing_duration = random.uniform(3, 8)
            await asyncio.sleep(typing_duration)
            
        finally:
            self.is_typing[chat_id] = False
    
    async def _generate_response(self, chat_id: int, message: Message) -> Optional[str]:
        """Generate a response using LLM"""
        # Get conversation context
        context_messages = await self.db.get_recent_messages(chat_id, limit=15)
        
        # Decide if we should include promotion (only in women chats)
        chat_title = message.chat.title if message.chat else ""
        chat_category = self._get_chat_category(chat_title)
        
        include_promotion = (
            chat_category == "women" and 
            random.random() < self.config.policy.promotion_probability
        )
        
        # Build prompt
        prompt = self._build_prompt(message, context_messages, include_promotion)
        
        # Generate response
        try:
            request = LLMRequest(
                prompt=prompt,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens
            )
            response = await self.llm.generate_async(request)
            
            # Post-process response
            response = self._post_process_response(response, include_promotion)
            
            return response
            
        except Exception as e:
            log.error(f"Error generating response: {e}")
            return None
    
    def _build_prompt(self, message: Message, context: List[MessageContext], include_promotion: bool) -> str:
        """Build prompt for LLM"""
        persona_desc = self.persona.get_description()
        
        # Format context
        context_str = ""
        for ctx in context[-10:]:  # Last 10 messages
            username = ctx.username or "Пользователь"
            context_str += f"{username}: {ctx.message_text}\n"
        
        # Current message
        current_user = message.from_user.username if message.from_user else "Пользователь"
        context_str += f"{current_user}: {message.text}\n"
        
        # Get bot context if promoting
        bot_context = ""
        if include_promotion:
            bot_info = get_bot_context()
            # Find relevant features based on conversation
            keywords = message.text.lower().split()
            relevant_features = get_relevant_features(keywords)
            
            if relevant_features:
                bot_context = f"\nИнформация о боте {bot_info['username']} который ты можешь порекомендовать:\n"
                for feature, details in relevant_features.items():
                    if not feature.startswith("hooks_"):
                        bot_context += f"- {details['description']}\n"
        
        prompt = f"""Ты - {persona_desc}

Контекст беседы:
{context_str}

Твоя задача - ответить на последнее сообщение естественно и по-человечески. 
Используй стиль: {self.config.persona.writing_style}

Важные правила:
- Отвечай кратко и по существу (1-3 предложения)
- Будь дружелюбной и эмпатичной
- Используй эмодзи умеренно
- НЕ раскрывай, что ты бот
- Веди себя как обычный участник чата
"""

        if include_promotion:
            prompt += f"\n- Если уместно в контексте беседы, можешь естественно упомянуть бота {self.config.promoted_bot.username}"
            prompt += f"\n- Упоминай только те функции бота, которые релевантны текущей теме разговора"
            if bot_context:
                prompt += bot_context
        
        prompt += f"\n{self.config.persona.name}:"
        
        return prompt
    
    def _post_process_response(self, response: str, include_promotion: bool) -> str:
        """Post-process the generated response"""
        # Remove any potential bot indicators
        response = response.replace("Как AI", "").replace("Я - бот", "")
        
        # Ensure promotion is natural if included
        if include_promotion and self.config.promoted_bot.username not in response and self.config.promoted_bot.name not in response:
            # Don't force it if LLM didn't include naturally
            pass
        
        # Trim excessive length
        sentences = response.split('. ')
        if len(sentences) > 3:
            response = '. '.join(sentences[:3]) + '.'
        
        return response.strip()
    
    async def _chat_discovery_loop(self):
        """Background task to discover new chats"""
        while True:
            try:
                await self._discover_new_chats()
                # Run discovery every 6 hours
                await asyncio.sleep(6 * 60 * 60)
            except Exception as e:
                log.error(f"Error in chat discovery: {e}")
                await asyncio.sleep(60)  # Retry after 1 minute
    
    async def _discover_new_chats(self):
        """Discover new female-oriented chats"""
        log.info("Starting chat discovery...")
        
        discovered_count = 0
        for keyword in self.config.telegram.search_keywords:
            try:
                # Search for public groups
                async for dialog in self.client.get_dialogs():
                    if dialog.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
                        chat = dialog.chat
                        
                        # Check if already tracked
                        if chat.id in self.active_chats:
                            continue
                        
                        # Check member count
                        if hasattr(chat, 'members_count'):
                            if chat.members_count < self.config.telegram.min_members:
                                continue
                            if chat.members_count > self.config.telegram.max_members:
                                continue
                        
                        # Check title/description for keywords
                        title_lower = (chat.title or "").lower()
                        description_lower = (chat.description or "").lower()
                        
                        if keyword.lower() in title_lower or keyword.lower() in description_lower:
                            # Try to join if not already member
                            try:
                                if not dialog.chat.is_participant:
                                    await self.client.join_chat(chat.id)
                                
                                # Add to active chats
                                self.active_chats.add(chat.id)
                                
                                # Save to database
                                await self.db.add_chat(
                                    chat_id=chat.id,
                                    title=chat.title,
                                    username=chat.username,
                                    members_count=chat.members_count if hasattr(chat, 'members_count') else 0
                                )
                                
                                discovered_count += 1
                                log.info(f"Discovered and joined chat: {chat.title} ({chat.id})")
                                
                                # Add delay to avoid flood
                                await asyncio.sleep(random.uniform(30, 60))
                                
                            except (ChatAdminRequired, UserBannedInChannel) as e:
                                log.warning(f"Cannot join chat {chat.title}: {e}")
                            except Exception as e:
                                log.error(f"Error joining chat {chat.title}: {e}")
                
            except FloodWait as e:
                log.warning(f"FloodWait during discovery: {e.x} seconds")
                await asyncio.sleep(e.x)
            except Exception as e:
                log.error(f"Error during chat discovery with keyword '{keyword}': {e}")
        
        log.info(f"Chat discovery completed. Discovered {discovered_count} new chats")
    
    async def _cleanup_old_messages(self):
        """Clean up old message history to save space"""
        while True:
            try:
                # Keep only last 7 days of messages
                cutoff_date = datetime.now() - timedelta(days=7)
                await self.db.cleanup_old_messages(cutoff_date)
                
                # Run cleanup daily
                await asyncio.sleep(24 * 60 * 60)
            except Exception as e:
                log.error(f"Error in cleanup task: {e}")
                await asyncio.sleep(60 * 60)  # Retry after 1 hour
