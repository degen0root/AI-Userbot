#!/usr/bin/env python3
"""
Tests for LLM module
"""

import pytest
from unittest.mock import patch, AsyncMock

from src.ai_userbot.llm import (
    LLMClient, StubLLM, OpenAIClient, GoogleGeminiClient, AnthropicClient,
    create_llm_client, LLMRequest
)


class TestLLMRequest:
    """Test LLMRequest dataclass"""

    def test_llm_request_creation(self):
        """Test creating LLM request"""
        request = LLMRequest(
            prompt="Hello world",
            temperature=0.8,
            max_tokens=100
        )

        assert request.prompt == "Hello world"
        assert request.temperature == 0.8
        assert request.max_tokens == 100
        assert request.chat_context is None
        assert request.system_prompt is None

    def test_llm_request_defaults(self):
        """Test LLM request default values"""
        request = LLMRequest(prompt="Test")

        assert request.temperature == 0.7  # Default
        assert request.max_tokens == 256  # Default


class TestStubLLM:
    """Test Stub LLM implementation"""

    def test_stub_llm_response(self):
        """Test that stub LLM returns responses"""
        llm = StubLLM()
        request = LLMRequest(prompt="Hello")

        response = llm.generate(request)

        assert isinstance(response, str)
        assert len(response) > 0

    def test_stub_llm_greeting_detection(self):
        """Test greeting keyword detection"""
        llm = StubLLM()
        request = LLMRequest(prompt="Привет, как дела?")

        response = llm.generate(request)

        # Should return greeting response
        assert "Привет" in response or "Здравствуйте" in response

    def test_stub_llm_meditation_detection(self):
        """Test meditation keyword detection"""
        llm = StubLLM()
        request = LLMRequest(prompt="Расскажи о медитации")

        response = llm.generate(request)

        # Should return meditation-related response
        assert "медитац" in response.lower()


class TestLLMFactory:
    """Test LLM client factory"""

    def test_create_stub_llm(self):
        """Test creating stub LLM"""
        config = {"provider": "stub"}
        llm = create_llm_client(config)

        assert isinstance(llm, StubLLM)

    def test_create_openai_llm(self):
        """Test creating OpenAI LLM"""
        config = {
            "provider": "openai",
            "api_key": "test-key",
            "model": "gpt-4"
        }
        llm = create_llm_client(config)

        assert isinstance(llm, OpenAIClient)
        assert llm.api_key == "test-key"
        assert llm.model == "gpt-4"

    def test_create_google_llm(self):
        """Test creating Google Gemini LLM"""
        config = {
            "provider": "google",
            "api_key": "test-key",
            "model": "gemini-pro"
        }
        llm = create_llm_client(config)

        assert isinstance(llm, GoogleGeminiClient)
        assert llm.api_key == "test-key"
        assert llm.model == "gemini-pro"

    def test_create_anthropic_llm(self):
        """Test creating Anthropic LLM"""
        config = {
            "provider": "anthropic",
            "api_key": "test-key",
            "model": "claude-3-haiku"
        }
        llm = create_llm_client(config)

        assert isinstance(llm, AnthropicClient)
        assert llm.api_key == "test-key"
        assert llm.model == "claude-3-haiku"

    def test_fallback_to_stub_on_missing_key(self):
        """Test fallback to stub when API key is missing"""
        config = {"provider": "openai"}  # No API key
        llm = create_llm_client(config)

        assert isinstance(llm, StubLLM)

    def test_unknown_provider_fallback(self):
        """Test fallback to stub for unknown provider"""
        config = {"provider": "unknown"}
        llm = create_llm_client(config)

        assert isinstance(llm, StubLLM)


class TestOpenAIClient:
    """Test OpenAI client (mocked)"""

    @patch('httpx.AsyncClient')
    def test_openai_client_creation(self, mock_client):
        """Test OpenAI client initialization"""
        client = OpenAIClient(
            api_key="test-key",
            model="gpt-4",
            temperature=0.8
        )

        assert client.api_key == "test-key"
        assert client.model == "gpt-4"
        assert client.temperature == 0.8
        assert client.base_url == "https://api.openai.com/v1"

    @patch('httpx.AsyncClient')
    @pytest.mark.asyncio
    async def test_openai_response_generation(self, mock_client):
        """Test OpenAI response generation (mocked)"""
        # Setup mock response
        mock_response = AsyncMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Mock response"}}]
        }
        mock_response.raise_for_status = AsyncMock()

        mock_client.return_value.__aenter__.return_value.post.return_value = mock_response

        client = OpenAIClient(api_key="test-key")
        request = LLMRequest(prompt="Test prompt")

        response = await client.generate_async(request)

        assert response == "Mock response"


class TestGoogleGeminiClient:
    """Test Google Gemini client (mocked)"""

    @patch('httpx.AsyncClient')
    def test_google_client_creation(self, mock_client):
        """Test Google Gemini client initialization"""
        client = GoogleGeminiClient(
            api_key="test-key",
            model="gemini-pro",
            temperature=0.8
        )

        assert client.api_key == "test-key"
        assert client.model == "gemini-pro"
        assert client.temperature == 0.8


if __name__ == "__main__":
    pytest.main([__file__])
