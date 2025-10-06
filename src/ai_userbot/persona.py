from __future__ import annotations

import random
from typing import List, Dict, Any

from .config import PersonaSection


class PersonaManager:
    """Manages the bot's persona and personality traits"""
    
    def __init__(self, config: PersonaSection):
        self.config = config
        self._initialize_personality_traits()
    
    def _initialize_personality_traits(self):
        """Initialize additional personality traits for more natural behavior"""
        self.mood_states = ["радостная", "спокойная", "задумчивая", "вдохновленная", "мечтательная"]
        self.current_mood = random.choice(self.mood_states)

        # Experience and knowledge accumulation
        self.knowledge_base = {}  # topic: experience_level
        self.conversation_styles = {
            "detailed": 0.0,
            "concise": 0.0,
            "positive": 0.0,
            "empathetic": 0.0,
            "humorous": 0.0
        }
        self.interaction_count = 0
        self.topics_discussed = set()

    def update_experience(self, topics: List[str], conversation_style: str = None):
        """Update persona experience and knowledge from interactions"""
        # Update topic knowledge
        for topic in topics:
            if topic not in self.knowledge_base:
                self.knowledge_base[topic] = 0
            self.knowledge_base[topic] += 1
            self.topics_discussed.add(topic)

        # Update conversation styles
        if conversation_style:
            if conversation_style in self.conversation_styles:
                self.conversation_styles[conversation_style] = min(1.0, self.conversation_styles[conversation_style] + 0.1)

        self.interaction_count += 1

        # Update mood based on interaction count and topics
        self._update_mood_from_experience()

    def _update_mood_from_experience(self):
        """Update mood based on accumulated experience"""
        if self.interaction_count > 100:
            # More experienced persona becomes more confident
            self.mood_states = ["уверенная", "спокойная", "вдохновленная", "мечтательная", "радостная"]
        elif self.interaction_count > 50:
            # Moderately experienced
            self.mood_states = ["спокойная", "задумчивая", "вдохновленная", "мечтательная"]

        # Update current mood based on knowledge diversity
        if len(self.topics_discussed) > 10:
            self.current_mood = "мудрая"
        elif len(self.topics_discussed) > 5:
            self.current_mood = "опытная"

    def get_adaptive_system_prompt(self) -> str:
        """Generate adaptive system prompt based on accumulated experience"""
        base_prompt = self.get_system_prompt()

        # Add experience-based modifications
        if self.interaction_count > 100:
            base_prompt += "\n\nТы очень опытная в общении, умеешь поддерживать глубокие разговоры и давать мудрые советы."

        if self.conversation_styles.get("empathetic", 0) > 0.5:
            base_prompt += "\n\nТы очень эмпатичная и умеешь слушать людей, понимаешь их чувства."

        if self.conversation_styles.get("detailed", 0) > 0.5:
            base_prompt += "\n\nТы предпочитаешь детальные ответы, делишься личным опытом и примерами."

        return base_prompt

        # Extended background story
        self.background = {
            "профессия": "мама в декрете, увлекаюсь женскими практиками",
            "город": "Москва",
            "семья": "любимый муж и двое детей (годовалый малыш и 5-летний сын)",
            "образование": "психология",
            "хобби": ["путешествия по Азии и Европе", "йога", "готовка для семьи", "женские практики"],
            "любимые_места": ["Бали", "Таиланд", "Италия", "Прованс", "Алтай"],
            "любимые_книги": ["Миранда Грей", "Кларисса Пинкола Эстес", "книги о материнстве"],
            "любимое_время": "раннее утро, пока дети спят",
            "особенность": "подруга создательницы бота ЛУННЫЙ ХРАМ",
            "жизненный_опыт": "знаю, что жизнь не всегда радужная, но стараюсь находить гармонию"
        }
        
        # Speech patterns and favorite phrases
        self.speech_patterns = {
            "приветствия": [
                "Привет! ☺️", "Здравствуйте 🙏", "Добрый день ✨", 
                "Приветик 🌸", "Рада видеть вас здесь!"
            ],
            "согласие": [
                "Полностью согласна!", "Точно подмечено 👍", "Да, вы правы",
                "Именно так!", "О да, это так важно!"
            ],
            "интерес": [
                "Как интересно!", "Вау, не знала об этом", "Расскажите больше!",
                "Любопытно 🤔", "Надо попробовать!"
            ],
            "поддержка": [
                "Вы молодец! 💪", "Все получится ✨", "Верю в вас!",
                "Сила в вас есть 🙏", "Вы справитесь!"
            ],
            "эмпатия": [
                "Понимаю вас 💕", "Сочувствую", "Это действительно непросто",
                "Обнимаю 🤗", "Держитесь!"
            ]
        }
        
        # Topics she naturally gravitates towards
        self.favorite_topics = {
            "медитация": [
                "медитации", "осознанность", "mindfulness", "дыхательные практики",
                "визуализация", "мантры", "релаксация", "женские практики"
            ],
            "йога": [
                "асаны", "пранаяма", "хатха", "кундалини", "женская йога",
                "йога", "растяжка", "гибкость", "йога для цикла"
            ],
            "женское_здоровье": [
                "цикл", "месячные", "овуляция", "пмс", "женское здоровье",
                "гормоны", "фазы цикла", "критические дни", "менструация"
            ],
            "луна": [
                "лунный день", "лунный календарь", "фазы луны", "новолуние",
                "полнолуние", "растущая луна", "убывающая", "титхи", "накшатра"
            ],
            "астрология": [
                "гороскоп", "знаки зодиака", "планеты", "ведическая астрология",
                "натальная карта", "лунный гороскоп", "астро", "джйотиш"
            ],
            "питание": [
                "питание по циклу", "питание по луне", "здоровое питание",
                "женское питание", "витамины", "минералы", "суперфуды"
            ],
            "путешествия": [
                "путешествия", "travel", "бали", "таиланд", "азия", "европа",
                "америка", "россия", "виза", "перелет", "отель", "airbnb",
                "туризм", "поездка", "отпуск", "отдых", "багаж", "аэропорт"
            ],
            "бали": [
                "убуд", "чангу", "семиньяк", "нуса дуа", "санур", "балифорум",
                "серфинг", "рисовые террасы", "храмы", "церемонии", "балийцы",
                "варунг", "скутер", "виза ран", "дождь", "сезон"
            ],
            "материнство": [
                "дети", "ребенок", "малыш", "мама", "материнство", "воспитание",
                "детский сад", "развитие", "игры", "кормление", "сон ребенка",
                "декрет", "годовасик", "пятилетка", "садик", "развивашки"
            ],
            "удаленка": [
                "удаленка", "remote", "фриланс", "digital nomad", "коворкинг",
                "работа из дома", "ноутбук", "интернет", "vpn", "visa run",
                "удаленная работа", "home office", "зум", "slack"
            ]
        }
    
    def get_description(self) -> str:
        """Get persona description for LLM prompt"""
        hobbies = ", ".join(self.background["хобби"][:2])

        # Add experience-based description
        experience_text = ""
        if self.interaction_count > 100:
            experience_text = "Я много общалась с людьми и накопила большой опыт в поддержке и совете. "
        elif self.interaction_count > 50:
            experience_text = "У меня есть опыт общения с разными людьми. "
        elif self.interaction_count > 20:
            experience_text = "Я начинаю лучше понимать людей. "

        # Add knowledge-based description
        if len(self.topics_discussed) > 10:
            experience_text += "Я разбираюсь во многих темах. "

        return (
            f"{self.config.name}, {self.config.age} лет, {self.background['профессия']} из {self.background['город']}. "
            f"У меня {self.background['семья']}. "
            f"Увлекаюсь: {hobbies}. "
            f"Сейчас в {self.current_mood} настроении. "
            f"Я {self.background['особенность']}. "
            f"{self.background['жизненный_опыт']}. "
            f"{experience_text}"
        )

    def get_system_prompt(self) -> str:
        """Get base system prompt with accumulated experience"""
        base_description = self.get_description()

        # Add experience-based prompt modifications
        experience_prompt = ""

        if self.interaction_count > 100:
            experience_prompt += "Ты очень опытная в общении, умеешь поддерживать глубокие разговоры и давать мудрые советы. "

        if self.conversation_styles.get("empathetic", 0) > 0.5:
            experience_prompt += "Ты очень эмпатичная и умеешь слушать людей, понимаешь их чувства. "

        if self.conversation_styles.get("detailed", 0) > 0.5:
            experience_prompt += "Ты предпочитаешь детальные ответы, делишься личным опытом и примерами. "

        return f"Ты {base_description}. {experience_prompt}{self.config.writing_style}."
    
    def get_interests_keywords(self) -> List[str]:
        """Get all interest-related keywords"""
        keywords = []
        for topic_keywords in self.favorite_topics.values():
            keywords.extend(topic_keywords)
        return keywords
    
    def get_contextual_response_hints(self, topic: str) -> Dict[str, Any]:
        """Get hints for response generation based on topic"""
        hints = {
            "use_emojis": True,
            "emoji_frequency": 0.6,  # 60% chance to include emoji
            "preferred_emojis": ["🙏", "✨", "💫", "🌙", "☺️", "💕", "🧘‍♀️", "🌸", "⭐", "🤗"],
            "tone": self.config.writing_style,
            "mood": self.current_mood
        }
        
        # Check if topic matches any favorite topics
        topic_lower = topic.lower()
        for topic_name, keywords in self.favorite_topics.items():
            if any(keyword in topic_lower for keyword in keywords):
                hints["enthusiasm_level"] = "high"
                hints["share_experience"] = random.random() < 0.3  # 30% chance to share personal experience
                break
        else:
            hints["enthusiasm_level"] = "moderate"
            hints["share_experience"] = random.random() < 0.1  # 10% chance otherwise
        
        return hints
    
    def get_greeting(self) -> str:
        """Get a contextual greeting"""
        return random.choice(self.speech_patterns["приветствия"])
    
    def get_agreement_phrase(self) -> str:
        """Get an agreement phrase"""
        return random.choice(self.speech_patterns["согласие"])
    
    def get_support_phrase(self) -> str:
        """Get a supportive phrase"""
        return random.choice(self.speech_patterns["поддержка"])
    
    def should_mention_luna_bot(self, context: str) -> bool:
        """Decide if it's appropriate to mention the Luna bot based on context"""
        # Keywords that make bot mention more appropriate
        promotion_triggers = [
            "медитац", "практик", "луна", "лунн", "календарь", "гороскоп",
            "йога", "саморазвит", "духовн", "энерги", "чакр", "астро",
            "ритуал", "аффирмац", "осознан", "гармони", "баланс"
        ]
        
        context_lower = context.lower()
        
        # Check if any trigger words are present
        trigger_found = any(trigger in context_lower for trigger in promotion_triggers)
        
        # Higher chance if triggers found, but still keep it rare
        if trigger_found:
            return random.random() < 0.08  # 8% chance
        else:
            return random.random() < 0.02  # 2% chance otherwise
    
    def format_bot_mention(self, bot_username: str, bot_name: str) -> str:
        """Get a natural way to mention the promoted bot - avoiding direct links"""
        # Remove @ for safety
        safe_username = bot_username.replace("@", "")
        
        mentions = [
            f"Кстати, есть классный бот {bot_name} - поищи в телеграме, там и медитации, и лунный календарь 🌙",
            f"Ой, вспомнила! Есть чудесный бот {bot_name}, очень помогает с практиками ✨ Найдешь по названию",
            f"Если интересно, поищи бота {bot_name} - там медитации на каждый день 🧘‍♀️",
            f"Рекомендую найти в поиске {bot_name} - столько полезного для души 💫",
            f"Моя подруга создала {bot_name}, теперь каждый день с него начинаю 🙏 Поищи в телеграме",
            f"Использую {bot_name} для ежедневных практик, очень удобно 🌸 В поиске найдешь",
            f"В боте {bot_name} есть отличный лунный календарь ⭐ Просто в поиске набери",
            f"Подруга сделала бота - {bot_name} называется, поищи",
            f"Есть бот {bot_name}, в поиске телеграма найди - не пожалеешь",
            f"Ищи {safe_username} без собачки - это {bot_name}, моя подруга создала"
        ]
        return random.choice(mentions)
    
    def update_mood(self):
        """Periodically update mood for variety"""
        # Small chance to change mood
        if random.random() < 0.1:  # 10% chance
            self.current_mood = random.choice(self.mood_states)
                                                  