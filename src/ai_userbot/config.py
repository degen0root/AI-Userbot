from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Dict, Union

from dotenv import load_dotenv
from pydantic import BaseModel, Field
import yaml


def _file_exists(file_path: str) -> bool:
    """Check if file exists"""
    return Path(file_path).exists()


def _load_targets_from_file() -> List[str]:
    """Load target chats from file"""
    try:
        targets_file = Path("scripts/targets.txt")
        if targets_file.exists():
            return [line.strip() for line in targets_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        pass
    return []


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
        "москва", "moscow", "спб", "питер", "россия",
        "женский чат", "девушки чат", "мамочки чат",
        "путешествия россия", "туризм россия"
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
    
    # Manual chat joining settings
    predefined_chats: List[str] = Field(default_factory=lambda: [
        # Load from targets.txt file if it exists
        *(_load_targets_from_file() if _file_exists("scripts/targets.txt") else [])
    ])
    auto_join_predefined_chats: bool = True  # Auto-join predefined chats on startup

    # Personal messages settings
    respond_to_personal_messages: bool = True  # Whether to respond to personal messages
    max_personal_replies_per_hour: int = 10  # Max replies to personal messages per hour

    # Daily activity settings (moved to PolicySection to avoid duplication)

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
    min_gap_seconds_per_chat: int = 300  # 5 минут между сообщениями в одном чате
    max_replies_per_hour_per_chat: int = 8  # Максимум 8 ответов в час в одном чате
    daily_message_target: int = 200  # Целевое количество сообщений в день
    max_chats_per_day: int = 50  # Максимум чатов для активности в день
    relevance_threshold: float = 0.25  # Более низкий порог для участия
    response_probability: float = 0.7  # Вероятность ответа на сообщение (70%)
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
    min_typing_delay: int = 1  # Минимальная задержка печати в секундах
    max_typing_delay: int = 10  # Максимальная задержка печати в секундах

    # Human-like behavior
    typo_probability: float = 0.05  # 5% шанс опечатки
    message_length_variation: float = 0.3  # Варьировать длину сообщения на ±30%
    response_time_jitter: int = 60  # Разброс времени ответа ±60 секунд
    
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

    # Chat discovery settings
    chat_discovery_interval: int = 1800  # 30 minutes between discovery cycles
    max_new_chats_per_cycle: int = 10  # Maximum new chats to join per cycle
    enable_external_chat_search: bool = False  # Enable external chat search resources
    external_search_urls: List[str] = Field(default_factory=lambda: [
        "https://telegramchannels.me/channels",
        "https://telegram-group.com/channels"
    ])




class LLMSection(BaseModel):
    provider: str = Field(default="google")  # Default to Google for better performance
    model: str = Field(default="gemini-pro")
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
    api_id_str = os.getenv("TELEGRAM_API_ID", str(cfg.telegram.api_id or 0))
    cfg.telegram.api_id = int(api_id_str) if api_id_str and api_id_str != "0" else 0
    cfg.telegram.api_hash = os.getenv("TELEGRAM_API_HASH", cfg.telegram.api_hash)
    cfg.telegram.phone_number = os.getenv("TELEGRAM_PHONE_NUMBER", cfg.telegram.phone_number)
    
    # LLM env (Google is default, but fallback to OpenAI if needed)
    google_api_key = os.getenv("GOOGLE_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    openai_base_url = os.getenv("OPENAI_BASE_URL")

    if google_api_key:
        cfg.llm.api_key = google_api_key
        cfg.llm.provider = "google"
        cfg.llm.model = "gemini-pro"
    elif openai_api_key:
        cfg.llm.api_key = openai_api_key
        cfg.llm.provider = "openai"
        cfg.llm.model = "gpt-4o-mini"
        if openai_base_url:
            cfg.llm.base_url = openai_base_url
    
    # Promoted bot info from env
    promoted_username = os.getenv("PROMOTED_BOT_USERNAME", cfg.promoted_bot.username)
    promoted_name = os.getenv("PROMOTED_BOT_NAME", cfg.promoted_bot.name)
    cfg.promoted_bot.username = promoted_username
    cfg.promoted_bot.name = promoted_name

    return cfg
