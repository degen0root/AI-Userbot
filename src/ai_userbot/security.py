"""
Security utilities for AI UserBot
"""

import os
import re
import logging
import secrets
from typing import Dict, Any, Optional
from cryptography.fernet import Fernet
import hashlib

log = logging.getLogger(__name__)


class SecretsManager:
    """Secure secrets management"""

    def __init__(self, encryption_key: Optional[str] = None):
        """Initialize secrets manager with encryption key"""
        if encryption_key:
            self.key = encryption_key.encode()
        else:
            # Generate or get key from environment
            self.key = os.getenv('SECRETS_ENCRYPTION_KEY', self._generate_key()).encode()

        self.fernet = Fernet(self.key)

    def _generate_key(self) -> str:
        """Generate a new encryption key"""
        return Fernet.generate_key().decode()

    def encrypt_secret(self, secret: str) -> str:
        """Encrypt a secret value"""
        return self.fernet.encrypt(secret.encode()).decode()

    def decrypt_secret(self, encrypted_secret: str) -> str:
        """Decrypt a secret value"""
        return self.fernet.decrypt(encrypted_secret.encode()).decode()

    def validate_api_key(self, provider: str, api_key: str) -> bool:
        """Validate API key format for different providers"""
        if not api_key or len(api_key.strip()) < 10:
            return False

        # Provider-specific validation
        if provider.lower() == "openai":
            return api_key.startswith("sk-") and len(api_key) >= 51
        elif provider.lower() in ["google", "gemini"]:
            return len(api_key) >= 39 and api_key.startswith("AIza")
        elif provider.lower() == "anthropic":
            return api_key.startswith("sk-ant-") and len(api_key) >= 50

        return True  # Generic validation for other providers

    def validate_phone_number(self, phone: str) -> bool:
        """Validate phone number format"""
        if not phone:
            return False

        # Remove common formatting characters
        cleaned = re.sub(r'[\s\-\(\)\+]', '', phone)

        # Check if it starts with country code and has correct length
        if cleaned.startswith('+'):
            return len(cleaned) >= 11 and len(cleaned) <= 15
        else:
            return len(cleaned) >= 10 and len(cleaned) <= 15

    def sanitize_log_message(self, message: str) -> str:
        """Remove or mask sensitive information from log messages"""
        # Mask potential API keys
        message = re.sub(r'(sk-|AIza|sk-ant-)[a-zA-Z0-9_-]{20,}', r'\1[REDACTED]', message)

        # Mask phone numbers
        message = re.sub(r'\+?\d{10,15}', '[PHONE]', message)

        return message


class InputValidator:
    """Input validation utilities"""

    @staticmethod
    def validate_chat_id(chat_id: Any) -> bool:
        """Validate chat ID"""
        try:
            int(chat_id)
            return abs(int(chat_id)) < 2**63  # Reasonable limit
        except (ValueError, TypeError, OverflowError):
            return False

    @staticmethod
    def validate_username(username: str) -> bool:
        """Validate username format"""
        if not username or not isinstance(username, str):
            return False

        # Telegram username rules
        if len(username) < 5 or len(username) > 32:
            return False

        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            return False

        return True

    @staticmethod
    def validate_message_text(text: str, max_length: int = 4096) -> bool:
        """Validate message text"""
        if not isinstance(text, str):
            return False

        if len(text) > max_length:
            return False

        # Check for extremely long repeated characters (potential spam)
        if len(set(text)) < len(text) * 0.1 and len(text) > 50:
            return False

        return True

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename for safe file operations"""
        # Remove path separators and dangerous characters
        sanitized = re.sub(r'[<>:"/\\|?*]', '', filename)
        return sanitized[:100]  # Limit length


def generate_secure_session_name() -> str:
    """Generate a secure random session name"""
    return f"session_{secrets.token_hex(16)}"


def hash_sensitive_data(data: str) -> str:
    """Create a hash of sensitive data for logging (not reversible)"""
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def validate_environment_variables() -> Dict[str, str]:
    """Validate that all required environment variables are properly set"""
    errors = {}

    # Check Telegram credentials
    api_id = os.getenv('TELEGRAM_API_ID')
    api_hash = os.getenv('TELEGRAM_API_HASH')
    phone = os.getenv('TELEGRAM_PHONE_NUMBER')

    if not api_id or not api_id.isdigit():
        errors['TELEGRAM_API_ID'] = 'Must be a valid numeric API ID'

    if not api_hash or len(api_hash) < 32:
        errors['TELEGRAM_API_HASH'] = 'Must be a valid API hash (at least 32 characters)'

    if not phone:
        errors['TELEGRAM_PHONE_NUMBER'] = 'Phone number is required'
    else:
        # Create a temporary secrets manager to validate phone
        temp_secrets = SecretsManager()
        if not temp_secrets.validate_phone_number(phone):
            errors['TELEGRAM_PHONE_NUMBER'] = 'Invalid phone number format'

    # Check LLM credentials (at least one should be provided)
    llm_providers = ['OPENAI_API_KEY', 'GOOGLE_API_KEY', 'ANTHROPIC_API_KEY']
    has_llm_key = any(os.getenv(key) for key in llm_providers)

    if not has_llm_key:
        errors['LLM_API_KEY'] = 'At least one LLM API key must be provided'

    # Validate individual LLM keys
    for provider in llm_providers:
        key = os.getenv(provider)
        if key:
            temp_secrets = SecretsManager()
            if not temp_secrets.validate_api_key(provider.replace('_API_KEY', '').lower(), key):
                errors[provider] = f'Invalid {provider.replace("_API_KEY", "").lower()} API key format'

    return errors
