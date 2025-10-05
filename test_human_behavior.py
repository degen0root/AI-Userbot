#!/usr/bin/env python3
"""
Тест человеческого поведения бота
"""

import asyncio
from datetime import datetime
import pytz
from src.ai_userbot.config import load_config
from src.ai_userbot.userbot import UserBot
from src.ai_userbot.llm import create_llm_client
from src.ai_userbot.database import ChatDatabase
from src.ai_userbot.persona import PersonaManager

class MockMessage:
    def __init__(self, text, chat_title="Test Chat"):
        self.text = text
        self.caption = None
        self.from_user = type('obj', (object,), {'id': 123})
        self.chat = type('obj', (object,), {'id': 456, 'title': chat_title})

async def test_time_check():
    """Тест проверки активного времени"""
    config = load_config()
    
    print("🕐 Тестирование временных ограничений")
    print(f"Часовой пояс: {config.policy.timezone}")
    
    tz = pytz.timezone(config.policy.timezone)
    now = datetime.now(tz)
    print(f"Текущее время: {now.strftime('%H:%M:%S %Z')}")
    
    # Создаем мок бота для теста
    class MockBot:
        def __init__(self, config):
            self.config = config
            
        def _is_active_time(self):
            tz = pytz.timezone(self.config.policy.timezone)
            now = datetime.now(tz)
            current_hour = now.hour
            
            wake_up = self.config.policy.active_hours["wake_up"]
            sleep_time = self.config.policy.active_hours["sleep_time"]
            
            if current_hour >= sleep_time or current_hour < wake_up:
                return False
                
            for period_name, hours in self.config.policy.active_hours.items():
                if isinstance(hours, list) and len(hours) == 2:
                    if hours[0] <= current_hour < hours[1]:
                        if now.weekday() >= 5:
                            print(f"  Выходной день - активность снижена до {config.policy.weekend_activity_multiplier * 100}%")
                        return True
            
            return False
    
    bot = MockBot(config)
    is_active = bot._is_active_time()
    
    print(f"Бот активен сейчас: {'✅ Да' if is_active else '❌ Нет'}")
    print()
    print("Расписание активности:")
    for period, hours in config.policy.active_hours.items():
        if isinstance(hours, list):
            print(f"  {period}: {hours[0]}:00 - {hours[1]}:00")
        else:
            print(f"  {period}: {hours}:00")

async def test_chat_categories():
    """Тест определения категорий чатов"""
    config = load_config()
    
    print("\n🗂 Тестирование категорий чатов")
    
    test_chats = [
        ("Женский чат Москвы", "women"),
        ("Бали форум - Убуд", "travel"),
        ("Московские мамочки", "women"),
        ("Digital Nomads Thailand", "travel"),
        ("Программисты России", "general"),
        ("Путешествия по Азии", "travel")
    ]
    
    class MockBot:
        def __init__(self, config):
            self.config = config
            
        def _get_chat_category(self, chat_title):
            title_lower = chat_title.lower() if chat_title else ""
            
            for category, keywords in self.config.telegram.chat_categories.items():
                if any(keyword in title_lower for keyword in keywords):
                    return category
            
            return "general"
    
    bot = MockBot(config)
    
    for chat_title, expected in test_chats:
        category = bot._get_chat_category(chat_title)
        status = "✅" if category == expected else "❌"
        print(f"{status} '{chat_title}' -> {category} (ожидалось: {expected})")

async def test_promotion_logic():
    """Тест логики продвижения"""
    config = load_config()
    
    print("\n📢 Тестирование логики продвижения")
    
    test_messages = [
        (MockMessage("Девочки, у кого есть опыт с циклом после родов?", "Мамочки Москвы"), True),
        (MockMessage("Где лучше жить на Бали с детьми?", "Бали форум"), False),
        (MockMessage("Ищу няню в Москве", "Москва - объявления"), False),
        (MockMessage("Поделитесь опытом восстановления после родов", "Женское здоровье"), True)
    ]
    
    print(f"Шанс продвижения в женских чатах: {config.policy.promotion_probability * 100}%")
    print("Продвижение разрешено только в женских чатах\n")
    
    class MockBot:
        def __init__(self, config):
            self.config = config
            
        def _get_chat_category(self, chat_title):
            title_lower = chat_title.lower() if chat_title else ""
            
            for category, keywords in self.config.telegram.chat_categories.items():
                if any(keyword in title_lower for keyword in keywords):
                    return category
            
            return "general"
    
    bot = MockBot(config)
    
    for message, should_allow_promotion in test_messages:
        category = bot._get_chat_category(message.chat.title)
        can_promote = category == "women"
        status = "✅" if can_promote == should_allow_promotion else "❌"
        print(f"{status} Чат: '{message.chat.title}' ({category}) - продвижение {'разрешено' if can_promote else 'запрещено'}")

async def main():
    """Запуск всех тестов"""
    print("🤖 Тестирование человеческого поведения AI UserBot\n")
    
    await test_time_check()
    await test_chat_categories()
    await test_promotion_logic()
    
    print("\n✨ Тестирование завершено!")

if __name__ == "__main__":
    asyncio.run(main())
