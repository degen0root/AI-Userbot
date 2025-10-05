from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Dict, Union

from dotenv import load_dotenv
from pydantic import BaseModel, Field
import yaml


class AppSection(BaseModel):
    name: str = Field(default="AIUserbot")
    logging_level: str = Field(default="INFO")


class TelegramSection(BaseModel):
    # Userbot settings
    api_id: int = Field(default=0)
    api_hash: str = Field(default="")
    phone_number: str = Field(default="")
    session_name: str = Field(default="userbot_session")
    
    # Chat search settings
    search_keywords: List[str] = Field(default_factory=lambda: [
        "женский", "девушки", "подруги", "мамочки", "женщины",
        "бали", "балифорум", "таиланд", "путешествия", "travel",
        "москва", "moscow"
    ])
    min_members: int = Field(default=50)
    max_members: int = Field(default=10000)
    
    # Chat categories
    chat_categories: Dict[str, List[str]] = Field(default_factory=lambda: {
        "women": ["женский", "девушки", "мамочки", "женщины"],
        "travel": ["бали", "travel", "путешеств", "таиланд", "азия"],
        "local": ["москва", "moscow", "мск"],
        "general": []
    })
    
    # Old bot settings (kept for compatibility)
    allowed_chat_ids: List[int] = Field(default_factory=list)


class PersonaSection(BaseModel):
    name: str = Field(default="Анна")
    age: int = Field(default=28)
    bio: str = Field(default="Люблю йогу, медитации и саморазвитие")
    interests: List[str] = Field(default_factory=lambda: [
        "йога", "медитация", "психология", "саморазвитие", 
        "астрология", "духовные практики"
    ])
    writing_style: str = Field(default="дружелюбный, эмпатичный, с эмодзи")


class PromotedBotSection(BaseModel):
    username: str = Field(default="@LunnyiHramBot")
    name: str = Field(default="Лунный Храм")
    context_file: str = Field(default="promoted_bot_context.py")


class PolicySection(BaseModel):
    disclose_identity: bool = False  # Не раскрываем, что мы бот
    disclosure_text: str = ""
    min_gap_seconds_per_chat: int = 300  # 5 минут между сообщениями
    max_replies_per_hour_per_chat: int = 8
    relevance_threshold: float = 0.25  # Более низкий порог для участия
    promotion_probability: float = 0.03  # 3% шанс упомянуть бота
    promotion_text: str = (
        "Кстати, недавно нашла классного бота @LunnyiHramBot - "
        "там и медитации, и лунный календарь, очень помогает 🌙"
    )
    forbidden_terms: List[str] = Field(default_factory=lambda: [
        "18+", "NSFW", "политика", "продажа", "реклама"
    ])
    
    # Message timing
    typing_speed_wpm: int = 40  # Слов в минуту при "печатании"
    reaction_delay_range: List[int] = Field(default_factory=lambda: [5, 30])  # секунды
    
    # Time zone and schedule
    timezone: str = Field(default="Europe/Moscow")
    active_hours: Dict[str, Union[int, List[int]]] = Field(default_factory=lambda: {
        "wake_up": 8,
        "morning_active": [8, 12],
        "lunch_break": [12, 13],
        "afternoon_active": [13, 18],
        "evening_active": [19, 22],
        "sleep_time": 23
    })
    
    # Activity patterns
    weekend_activity_multiplier: float = 0.7
    night_messages_probability: float = 0.05


class LLMSection(BaseModel):
    provider: str = Field(default="stub")
    model: str = Field(default="gpt-4o-mini")
    temperature: float = 0.7
    max_tokens: int = 256
    # Loaded from env if needed
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class AppConfig(BaseModel):
    app: AppSection = Field(default_factory=AppSection)
    telegram: TelegramSection = Field(default_factory=TelegramSection)
    persona: PersonaSection = Field(default_factory=PersonaSection)
    promoted_bot: PromotedBotSection = Field(default_factory=PromotedBotSection)
    policy: PolicySection = Field(default_factory=PolicySection)
    llm: LLMSection = Field(default_factory=LLMSection)
    # Secrets
    telegram_bot_token: str = Field(default="")  # Kept for compatibility


def load_config(path: Optional[str | os.PathLike[str]] = None) -> AppConfig:
    """Load configuration.

    If path is None, tries configs/config.yaml; if it doesn't exist,
    falls back to configs/config.example.yaml.
    """
    load_dotenv()  # optional .env

    if path is None:
        primary = Path("configs/config.yaml")
        fallback = Path("configs/config.example.yaml")
        p = primary if primary.exists() else fallback
    else:
        p = Path(path)

    with open(p, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    cfg = AppConfig(**raw)
    # Merge env secrets
    cfg.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", cfg.telegram_bot_token)
    
    # Userbot credentials from env
    cfg.telegram.api_id = int(os.getenv("TELEGRAM_API_ID", cfg.telegram.api_id or 0))
    cfg.telegram.api_hash = os.getenv("TELEGRAM_API_HASH", cfg.telegram.api_hash)
    cfg.telegram.phone_number = os.getenv("TELEGRAM_PHONE_NUMBER", cfg.telegram.phone_number)
    
    # LLM env (if used later)
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    if api_key:
        cfg.llm.api_key = api_key
    if base_url:
        cfg.llm.base_url = base_url
    
    # Promoted bot info from env
    promoted_username = os.getenv("PROMOTED_BOT_USERNAME", cfg.promoted_bot.username)
    promoted_name = os.getenv("PROMOTED_BOT_NAME", cfg.promoted_bot.name)
    cfg.promoted_bot.username = promoted_username
    cfg.promoted_bot.name = promoted_name

    return cfg
