from __future__ import annotations

import logging
import json
from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Float, Text, select, and_, desc
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from pydantic import BaseModel

log = logging.getLogger(__name__)

Base = declarative_base()


class ChatRecord(Base):
    """Database model for tracked chats"""
    __tablename__ = "chats"
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, unique=True, nullable=False, index=True)
    title = Column(String(255))
    username = Column(String(255))
    members_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    joined_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow)
    total_messages_sent = Column(Integer, default=0)
    total_promotions_sent = Column(Integer, default=0)
    ai_analysis = Column(Text)  # JSON field for AI analysis results
    join_status = Column(String(20), default='joined')  # joined, pending, rejected


class MessageRecord(Base):
    """Database model for message context"""
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False)
    username = Column(String(255))
    message_text = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    is_bot_message = Column(Boolean, default=False)


class InteractionLog(Base):
    """Database model for bot interactions"""
    __tablename__ = "interaction_logs"
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    bot_message = Column(Text)
    includes_promotion = Column(Boolean, default=False)
    response_time_seconds = Column(Float)


# Pydantic models for data transfer
class ChatInfo(BaseModel):
    chat_id: int
    title: Optional[str] = None
    username: Optional[str] = None
    members_count: int = 0
    is_active: bool = True
    total_messages_sent: int = 0
    total_promotions_sent: int = 0


class MessageContext(BaseModel):
    chat_id: int
    user_id: int
    username: str
    message_text: str
    timestamp: datetime
    is_bot_message: bool = False


class ChatDatabase:
    """Async database manager for chat tracking"""
    
    def __init__(self, database_url: str = "sqlite+aiosqlite:///userbot.db"):
        # Convert to async URL if needed
        if database_url.startswith("sqlite://"):
            database_url = database_url.replace("sqlite://", "sqlite+aiosqlite://")
        
        self.engine = create_async_engine(database_url, echo=False)
        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
    
    async def initialize(self):
        """Create all tables"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("Database initialized")
    
    async def close(self):
        """Close database connections"""
        await self.engine.dispose()
    
    async def get_chat(self, chat_id: int) -> Optional[ChatRecord]:
        """Get chat record from database"""
        async with self.async_session() as session:
            result = await session.execute(
                select(ChatRecord).where(ChatRecord.chat_id == chat_id)
            )
            return result.scalar_one_or_none()

    async def add_chat(self, chat_id: int, title: Optional[str] = None,
                      username: Optional[str] = None, members_count: int = 0,
                      ai_analysis: Optional[dict] = None, join_status: str = 'joined') -> ChatInfo:
        """Add or update a chat in the database"""
        async with self.async_session() as session:
            # Check if chat exists
            result = await session.execute(
                select(ChatRecord).where(ChatRecord.chat_id == chat_id)
            )
            chat = result.scalar_one_or_none()
            
            if chat:
                # Update existing
                chat.title = title or chat.title
                chat.username = username or chat.username
                chat.members_count = members_count or chat.members_count
                chat.last_activity = datetime.utcnow()
                chat.is_active = True
                chat.join_status = join_status
                if ai_analysis:
                    chat.ai_analysis = json.dumps(ai_analysis)
            else:
                # Create new
                chat = ChatRecord(
                    chat_id=chat_id,
                    title=title,
                    username=username,
                    members_count=members_count,
                    join_status=join_status,
                    ai_analysis=json.dumps(ai_analysis) if ai_analysis else None
                )
                session.add(chat)
            
            await session.commit()
            
            return ChatInfo(
                chat_id=chat.chat_id,
                title=chat.title,
                username=chat.username,
                members_count=chat.members_count,
                is_active=chat.is_active,
                total_messages_sent=chat.total_messages_sent,
                total_promotions_sent=chat.total_promotions_sent
            )
    
    async def get_active_chats(self) -> List[ChatInfo]:
        """Get all active chats"""
        async with self.async_session() as session:
            result = await session.execute(
                select(ChatRecord).where(ChatRecord.is_active == True)
            )
            chats = result.scalars().all()
            
            return [
                ChatInfo(
                    chat_id=chat.chat_id,
                    title=chat.title,
                    username=chat.username,
                    members_count=chat.members_count,
                    is_active=chat.is_active,
                    total_messages_sent=chat.total_messages_sent,
                    total_promotions_sent=chat.total_promotions_sent
                )
                for chat in chats
            ]
    
    async def deactivate_chat(self, chat_id: int):
        """Mark a chat as inactive"""
        async with self.async_session() as session:
            result = await session.execute(
                select(ChatRecord).where(ChatRecord.chat_id == chat_id)
            )
            chat = result.scalar_one_or_none()
            
            if chat:
                chat.is_active = False
                await session.commit()
    
    async def add_message_context(self, chat_id: int, user_id: int, username: str,
                                 message_text: str, timestamp: datetime,
                                 is_bot_message: bool = False):
        """Store message for context tracking"""
        async with self.async_session() as session:
            message = MessageRecord(
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                message_text=message_text[:1000],  # Limit text length
                timestamp=timestamp,
                is_bot_message=is_bot_message
            )
            session.add(message)
            await session.commit()
    
    async def get_recent_messages(self, chat_id: int, limit: int = 20) -> List[MessageContext]:
        """Get recent messages from a chat"""
        async with self.async_session() as session:
            result = await session.execute(
                select(MessageRecord)
                .where(MessageRecord.chat_id == chat_id)
                .order_by(desc(MessageRecord.timestamp))
                .limit(limit)
            )
            messages = result.scalars().all()
            
            # Reverse to get chronological order
            return [
                MessageContext(
                    chat_id=msg.chat_id,
                    user_id=msg.user_id,
                    username=msg.username,
                    message_text=msg.message_text,
                    timestamp=msg.timestamp,
                    is_bot_message=msg.is_bot_message
                )
                for msg in reversed(messages)
            ]
    
    async def log_message(self, chat_id: int, user_id: int, message_text: str,
                         is_bot_message: bool = False, username: Optional[str] = None):
        """Log any message to the database"""
        async with self.async_session() as session:
            message = MessageRecord(
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                message_text=message_text[:1000],  # Limit text length
                timestamp=datetime.utcnow(),
                is_bot_message=is_bot_message
            )
            session.add(message)
            await session.commit()

    async def log_bot_message(self, chat_id: int, message_text: str,
                            includes_promotion: bool = False,
                            response_time_seconds: float = 0):
        """Log bot's message and update statistics"""
        async with self.async_session() as session:
            # Log interaction
            interaction = InteractionLog(
                chat_id=chat_id,
                bot_message=message_text[:1000],
                includes_promotion=includes_promotion,
                response_time_seconds=response_time_seconds
            )
            session.add(interaction)
            
            # Update chat statistics
            result = await session.execute(
                select(ChatRecord).where(ChatRecord.chat_id == chat_id)
            )
            chat = result.scalar_one_or_none()
            
            if chat:
                chat.total_messages_sent += 1
                if includes_promotion:
                    chat.total_promotions_sent += 1
                chat.last_activity = datetime.utcnow()
            
            # Also add to message context as bot message
            message = MessageRecord(
                chat_id=chat_id,
                user_id=0,  # 0 for bot
                username="AI_Assistant",
                message_text=message_text[:1000],
                is_bot_message=True
            )
            session.add(message)
            
            await session.commit()
    
    async def get_chat_statistics(self, chat_id: int) -> Dict[str, Any]:
        """Get statistics for a specific chat"""
        async with self.async_session() as session:
            # Get chat info
            result = await session.execute(
                select(ChatRecord).where(ChatRecord.chat_id == chat_id)
            )
            chat = result.scalar_one_or_none()
            
            if not chat:
                return {}
            
            # Count interactions in last 24 hours
            yesterday = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            result = await session.execute(
                select(InteractionLog)
                .where(and_(
                    InteractionLog.chat_id == chat_id,
                    InteractionLog.timestamp >= yesterday
                ))
            )
            recent_interactions = result.scalars().all()
            
            return {
                "chat_id": chat_id,
                "title": chat.title,
                "total_messages_sent": chat.total_messages_sent,
                "total_promotions_sent": chat.total_promotions_sent,
                "messages_today": len(recent_interactions),
                "promotions_today": sum(1 for i in recent_interactions if i.includes_promotion),
                "avg_response_time": sum(i.response_time_seconds for i in recent_interactions) / len(recent_interactions) if recent_interactions else 0,
                "is_active": chat.is_active,
                "last_activity": chat.last_activity
            }
    
    async def cleanup_old_messages(self, cutoff_date: datetime):
        """Remove old messages to save space"""
        async with self.async_session() as session:
            # Delete old messages
            await session.execute(
                MessageRecord.__table__.delete().where(
                    MessageRecord.timestamp < cutoff_date
                )
            )
            
            # Delete old interaction logs
            await session.execute(
                InteractionLog.__table__.delete().where(
                    InteractionLog.timestamp < cutoff_date
                )
            )
            
            await session.commit()
            log.info(f"Cleaned up messages older than {cutoff_date}")

    async def get_daily_stats(self, date_start: datetime) -> Dict:
        """Get daily statistics for messages and active chats"""
        async with self.async_session() as session:
            # Get messages sent today
            messages_result = await session.execute(
                select(MessageRecord).where(
                    MessageRecord.timestamp >= date_start,
                    MessageRecord.is_bot_message == True
                )
            )
            messages = messages_result.scalars().all()

            # Get active chats today
            chats_result = await session.execute(
                select(ChatRecord.chat_id).where(
                    ChatRecord.last_activity >= date_start,
                    ChatRecord.is_active == True
                )
            )
            active_chats = set(chats_result.scalars().all())

            return {
                "messages_sent": len(messages),
                "active_chats": active_chats
            }

    async def get_messages_since(self, chat_id: int, since: datetime, bot_only: bool = False) -> List[MessageRecord]:
        """Get messages from a chat since a specific time"""
        async with self.async_session() as session:
            query = select(MessageRecord).where(
                MessageRecord.chat_id == chat_id,
                MessageRecord.timestamp >= since
            )

            if bot_only:
                query = query.where(MessageRecord.is_bot_message == True)

            result = await session.execute(query)
            return result.scalars().all()

    async def get_personal_messages_since(self, user_id: int, since: datetime) -> List[MessageRecord]:
        """Get personal messages sent to a specific user since a specific time"""
        async with self.async_session() as session:
            result = await session.execute(
                select(MessageRecord).where(
                    MessageRecord.chat_id == 0,  # Personal messages have chat_id = 0
                    MessageRecord.user_id == user_id,
                    MessageRecord.timestamp >= since,
                    MessageRecord.is_bot_message == True
                )
            )
            return result.scalars().all()
