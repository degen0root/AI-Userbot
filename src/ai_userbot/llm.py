from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Optional, Dict, Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)


@dataclass
class LLMRequest:
    prompt: str
    chat_context: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 256
    system_prompt: Optional[str] = None


class LLMClient:
    """Base class for LLM clients"""
    
    def generate(self, req: LLMRequest) -> str:
        """Synchronous generation"""
        raise NotImplementedError
    
    async def generate_async(self, req: LLMRequest) -> str:
        """Asynchronous generation"""
        # Default implementation runs sync version in thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.generate, req)


class StubLLM(LLMClient):
    """Enhanced stub that generates more contextual responses"""

    def __init__(self):
        self.response_templates = {
            "greeting": [
                "Привет! Как дела? ☺️",
                "Здравствуйте! Рада вас видеть 🙏",
                "Приветик! Какое настроение? ✨"
            ],
            "meditation": [
                "О, медитация - это прекрасно! Я сама практикую каждое утро 🧘‍♀️",
                "Медитация так помогает найти баланс в жизни ✨",
                "Обожаю медитировать, особенно на рассвете 🌅"
            ],
            "yoga": [
                "Йога - моя страсть! Какие асаны любите? 🧘‍♀️",
                "Практикую йогу уже 5 лет, это изменило мою жизнь 🙏",
                "Йога - путь к гармонии души и тела ✨"
            ],
            "support": [
                "Все обязательно наладится, верьте в себя! 💪",
                "Понимаю вас, иногда бывает непросто 🤗",
                "Вы справитесь, я в вас верю! ⭐"
            ],
            "general": [
                "Интересная мысль, расскажите больше 🤔",
                "Да, полностью согласна с вами!",
                "Как здорово, что вы это подметили ✨",
                "О, никогда об этом не думала! Любопытно 💫"
            ]
        }

    def generate(self, req: LLMRequest) -> str:
        prompt_lower = req.prompt.lower()
        
        # Simple keyword matching for context
        if any(word in prompt_lower for word in ["привет", "здравств", "добрый"]):
            responses = self.response_templates["greeting"]
        elif any(word in prompt_lower for word in ["медитац", "осознан", "mindful"]):
            responses = self.response_templates["meditation"]
        elif any(word in prompt_lower for word in ["йога", "асан", "пранаям"]):
            responses = self.response_templates["yoga"]
        elif any(word in prompt_lower for word in ["трудно", "сложно", "помог", "поддерж"]):
            responses = self.response_templates["support"]
        else:
            responses = self.response_templates["general"]
        
        base_response = random.choice(responses)
        
        # Small chance to add promotion (will be controlled by policy)
        # Promotion logic is handled at higher level now
        
        return base_response


class OpenAIClient(LLMClient):
    """OpenAI API client with retry logic"""
    
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", 
                 temperature: float = 0.7, base_url: Optional[str] = None):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.base_url = base_url or "https://api.openai.com/v1"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def generate_async(self, req: LLMRequest) -> str:
        """Generate response using OpenAI API"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            messages = []
            
            if req.system_prompt:
                messages.append({"role": "system", "content": req.system_prompt})
            
            if req.chat_context:
                messages.append({"role": "user", "content": req.chat_context})
            
            messages.append({"role": "user", "content": req.prompt})
            
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": req.temperature or self.temperature,
                "max_tokens": req.max_tokens,
                "presence_penalty": 0.6,  # Reduce repetition
                "frequency_penalty": 0.3
            }
            
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=payload
                )
                response.raise_for_status()
                
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
                
            except httpx.HTTPStatusError as e:
                log.error(f"OpenAI API error: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                log.error(f"OpenAI API error: {e}")
                raise
    
    def generate(self, req: LLMRequest) -> str:
        """Synchronous wrapper"""
        return asyncio.run(self.generate_async(req))


class AnthropicClient(LLMClient):
    """Anthropic Claude API client"""
    
    def __init__(self, api_key: str, model: str = "claude-3-haiku-20240307",
                 temperature: float = 0.7):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def generate_async(self, req: LLMRequest) -> str:
        """Generate response using Anthropic API"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            system_prompt = req.system_prompt or "You are a helpful assistant."
            
            user_content = req.prompt
            if req.chat_context:
                user_content = f"{req.chat_context}\n\n{req.prompt}"
            
            payload = {
                "model": self.model,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_content}],
                "temperature": req.temperature or self.temperature,
                "max_tokens": req.max_tokens
            }
            
            try:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=self.headers,
                    json=payload
                )
                response.raise_for_status()
                
                data = response.json()
                return data["content"][0]["text"].strip()
                
            except httpx.HTTPStatusError as e:
                log.error(f"Anthropic API error: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                log.error(f"Anthropic API error: {e}")
                raise
    
    def generate(self, req: LLMRequest) -> str:
        """Synchronous wrapper"""
        return asyncio.run(self.generate_async(req))


class GoogleGeminiClient(LLMClient):
    """Google Gemini API client"""
    
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash",
                 temperature: float = 0.7):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def generate_async(self, req: LLMRequest) -> str:
        """Generate response using Google Gemini API"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            
            prompt = req.prompt
            if req.system_prompt:
                prompt = f"{req.system_prompt}\n\n{prompt}"
            if req.chat_context:
                prompt = f"{req.chat_context}\n\n{prompt}"
            
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": req.temperature or self.temperature,
                    "maxOutputTokens": req.max_tokens,
                    "topP": 0.8,
                    "topK": 40
                }
            }
            
            try:
                response = await client.post(
                    url,
                    params={"key": self.api_key},
                    json=payload
                )
                response.raise_for_status()
                
                data = response.json()
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                
            except httpx.HTTPStatusError as e:
                log.error(f"Google Gemini API error: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                log.error(f"Google Gemini API error: {e}")
                raise
    
    def generate(self, req: LLMRequest) -> str:
        """Synchronous wrapper"""
        return asyncio.run(self.generate_async(req))


def create_llm_client(config: Dict[str, Any]) -> LLMClient:
    """Factory function to create appropriate LLM client"""
    provider = config.get("provider", "stub").lower()
    
    if provider == "stub":
        return StubLLM()
    
    elif provider == "openai":
        if not config.get("api_key"):
            log.warning("OpenAI API key not provided, falling back to StubLLM")
            return StubLLM()
        
        return OpenAIClient(
            api_key=config["api_key"],
            model=config.get("model", "gpt-4o-mini"),
            temperature=config.get("temperature", 0.7),
            base_url=config.get("base_url")
        )
    
    elif provider == "anthropic":
        if not config.get("api_key"):
            log.warning("Anthropic API key not provided, falling back to StubLLM")
            return StubLLM()
        
        return AnthropicClient(
            api_key=config["api_key"],
            model=config.get("model", "claude-3-haiku-20240307"),
            temperature=config.get("temperature", 0.7)
        )
    
    elif provider == "google" or provider == "gemini":
        if not config.get("api_key"):
            log.warning("Google API key not provided, falling back to StubLLM")
            return StubLLM()
        
        return GoogleGeminiClient(
            api_key=config["api_key"],
            model=config.get("model", "gemini-1.5-flash"),
            temperature=config.get("temperature", 0.7)
        )
    
    else:
        log.warning(f"Unknown LLM provider: {provider}, falling back to StubLLM")
        return StubLLM()

