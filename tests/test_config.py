#!/usr/bin/env python3
"""
Tests for configuration module
"""

import pytest
from pathlib import Path
import tempfile
import yaml

from src.ai_userbot.config import load_config, AppConfig


class TestConfigLoading:
    """Test configuration loading and validation"""

    def test_load_example_config(self):
        """Test loading the example configuration"""
        config = load_config("configs/config.example.yaml")
        assert isinstance(config, AppConfig)
        assert config.app.name == "AIUserbot"
        assert config.telegram.api_id == 0  # Default value

    def test_config_validation(self):
        """Test configuration validation"""
        config = load_config("configs/config.example.yaml")

        # Test that configuration has required structure
        assert hasattr(config, 'app')
        assert hasattr(config, 'telegram')
        assert hasattr(config, 'persona')
        assert hasattr(config, 'policy')
        assert hasattr(config, 'llm')

        # Test policy response_probability structure
        assert isinstance(config.policy.response_probability, dict)
        assert "women" in config.policy.response_probability
        assert "general" in config.policy.response_probability

    def test_invalid_config_file(self):
        """Test loading non-existent config file"""
        with pytest.raises(FileNotFoundError):
            load_config("nonexistent.yaml")


class TestConfigStructure:
    """Test configuration structure and defaults"""

    def test_telegram_section_defaults(self):
        """Test Telegram section default values"""
        config = load_config("configs/config.example.yaml")

        assert config.telegram.api_id == 0
        assert config.telegram.api_hash == ""
        assert config.telegram.phone_number == ""
        assert config.telegram.session_name == "userbot_session"

    def test_policy_section_defaults(self):
        """Test Policy section default values"""
        config = load_config("configs/config.example.yaml")

        assert config.policy.min_gap_seconds_per_chat == 300
        assert config.policy.max_replies_per_hour_per_chat == 8
        assert config.policy.relevance_threshold == 0.25
        assert isinstance(config.policy.response_probability, dict)

    def test_persona_section_defaults(self):
        """Test Persona section default values"""
        config = load_config("configs/config.example.yaml")

        assert config.persona.name == "Анна"
        assert config.persona.age == 28
        assert "йога" in config.persona.interests

    def test_llm_section_defaults(self):
        """Test LLM section default values"""
        config = load_config("configs/config.example.yaml")

        assert config.llm.provider == "google"
        assert config.llm.model == "gemini-pro"
        assert config.llm.temperature == 0.7


if __name__ == "__main__":
    pytest.main([__file__])
