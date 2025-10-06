#!/usr/bin/env python3
"""
Tests for database module
"""

import pytest
import asyncio
import tempfile
from pathlib import Path

from src.ai_userbot.database import ChatDatabase, ChatRecord, MessageRecord, InteractionLog


class TestChatDatabase:
    """Test database operations"""

    @pytest.fixture
    async def db(self):
        """Create a test database"""
        # Create temporary database file
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        # Create database instance
        database = ChatDatabase(f"sqlite+aiosqlite:///{db_path}")

        # Initialize database
        await database.initialize()

        yield database

        # Cleanup
        await database.close()
        Path(db_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_add_chat(self, db):
        """Test adding a chat to database"""
        chat_info = await db.add_chat(
            chat_id=12345,
            title="Test Chat",
            username="testchat",
            members_count=100
        )

        assert chat_info.chat_id == 12345
        assert chat_info.title == "Test Chat"
        assert chat_info.username == "testchat"
        assert chat_info.members_count == 100
        assert chat_info.is_active == True

    @pytest.mark.asyncio
    async def test_get_active_chats(self, db):
        """Test getting active chats"""
        # Add some test chats
        await db.add_chat(chat_id=1, title="Chat 1")
        await db.add_chat(chat_id=2, title="Chat 2")
        await db.add_chat(chat_id=3, title="Chat 3", is_active=False)

        active_chats = await db.get_active_chats()

        assert len(active_chats) == 2
        assert all(chat.is_active for chat in active_chats)
        assert {chat.chat_id for chat in active_chats} == {1, 2}

    @pytest.mark.asyncio
    async def test_add_message_context(self, db):
        """Test adding message context"""
        await db.add_message_context(
            chat_id=123,
            user_id=456,
            username="testuser",
            message_text="Hello world",
            timestamp=None  # Will use current time
        )

        # Check that message was added (we can't easily query it back without more complex setup)
        # This test mainly ensures no exceptions are raised

    @pytest.mark.asyncio
    async def test_log_bot_message(self, db):
        """Test logging bot message"""
        await db.log_bot_message(
            chat_id=123,
            message_text="Bot response",
            includes_promotion=False,
            response_time_seconds=1.5
        )

        # Check that interaction was logged
        # This test mainly ensures no exceptions are raised

    @pytest.mark.asyncio
    async def test_log_message(self, db):
        """Test logging any message"""
        await db.log_message(
            chat_id=123,
            user_id=456,
            message_text="Test message",
            is_bot_message=False,
            username="testuser"
        )

        # Check that message was logged
        # This test mainly ensures no exceptions are raised


if __name__ == "__main__":
    pytest.main([__file__])
