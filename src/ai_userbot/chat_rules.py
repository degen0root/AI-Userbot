"""
Chat rules analyzer - checks for anti-spam rules in chat
"""

import re
from typing import List, Dict, Optional
import logging

log = logging.getLogger(__name__)

class ChatRulesAnalyzer:
    """Analyzes chat rules to avoid violations"""
    
    def __init__(self):
        # Keywords that indicate link/spam restrictions
        self.restriction_keywords = [
            # Russian
            "запрещен", "нельзя", "не разрешается", "блокировка", "бан",
            "ссылки", "ссылок", "реклама", "рекламы", "спам",
            "промо", "продвижение", "@", "собачка", "упоминания",
            "правила", "регламент", "модерация",
            # English
            "forbidden", "prohibited", "not allowed", "ban", "block",
            "links", "advertising", "ads", "spam", "promo",
            "mention", "mentions", "rules", "moderation"
        ]
        
        # Patterns that indicate strict moderation
        self.strict_patterns = [
            r"запрещ.*ссыл",
            r"нельзя.*@",
            r"бан.*реклам",
            r"no.*link",
            r"no.*@",
            r"no.*ads",
            r"no.*spam"
        ]
    
    def analyze_pinned_message(self, pinned_text: Optional[str]) -> Dict[str, bool]:
        """Analyze pinned message for rules"""
        if not pinned_text:
            return {
                "has_rules": False,
                "prohibits_links": False,
                "prohibits_mentions": False,
                "strict_moderation": False
            }
        
        text_lower = pinned_text.lower()
        
        # Check for restriction keywords
        has_rules = any(keyword in text_lower for keyword in self.restriction_keywords)
        
        # Check specific restrictions
        prohibits_links = any(word in text_lower for word in [
            "ссылк", "link", "url", "http"
        ])
        
        prohibits_mentions = any(word in text_lower for word in [
            "@", "собачк", "упоминан", "mention"
        ])
        
        # Check for strict patterns
        strict_moderation = any(
            re.search(pattern, text_lower) 
            for pattern in self.strict_patterns
        )
        
        result = {
            "has_rules": has_rules,
            "prohibits_links": prohibits_links,
            "prohibits_mentions": prohibits_mentions,
            "strict_moderation": strict_moderation
        }
        
        if has_rules:
            log.info(f"Chat has rules: {result}")
        
        return result
    
    def should_use_safe_mention(self, chat_rules: Dict[str, bool]) -> bool:
        """Decide if we should use safe mention based on chat rules"""
        return (
            chat_rules.get("prohibits_links", False) or
            chat_rules.get("prohibits_mentions", False) or
            chat_rules.get("strict_moderation", False)
        )
    
    def get_safe_mention_style(self, chat_rules: Dict[str, bool]) -> str:
        """Get appropriate mention style based on rules"""
        if chat_rules.get("strict_moderation", False):
            # Very careful - only bot name
            return "name_only"
        elif chat_rules.get("prohibits_mentions", False):
            # No @ but can mention username
            return "no_at"
        else:
            # Default safe mode
            return "search_hint"
