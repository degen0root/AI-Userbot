from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import structlog
from rich.console import Console
from rich.logging import RichHandler

from .config import load_config
from .database import ChatDatabase
from .llm import create_llm_client
from .userbot import UserBot
from .security import validate_environment_variables, SecretsManager


console = Console()


def setup_logging(level: str = "INFO"):
    """Configure structured logging with rich output"""
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard logging with Rich handler
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)]
    )


class Application:
    """Main application class that manages all components"""
    
    def __init__(self, config_path: Path):
        self.config = load_config(config_path)
        self.db: Optional[ChatDatabase] = None
        self.llm = None
        self.userbot: Optional[UserBot] = None
        self.log = structlog.get_logger(__name__)
    
    async def initialize(self):
        """Initialize all components"""
        self.log.info("Initializing application", app_name=self.config.app.name)

        # Validate environment variables first
        env_errors = validate_environment_variables()
        if env_errors:
            console.print("[red]Environment validation errors:[/red]")
            for var, error in env_errors.items():
                console.print(f"  • {var}: {error}")
            console.print("\n[yellow]Please fix environment variables before running[/yellow]")
            raise RuntimeError("Environment validation failed")

        # Initialize secrets manager
        self.secrets_manager = SecretsManager()
        self.log.info("Security manager initialized")

        # Initialize database
        self.db = ChatDatabase()
        await self.db.initialize()
        self.log.info("Database initialized")

        # Initialize LLM client
        llm_config = {
            "provider": self.config.llm.provider,
            "api_key": self.config.llm.api_key,
            "model": self.config.llm.model,
            "temperature": self.config.llm.temperature,
            "base_url": self.config.llm.base_url
        }
        self.llm = create_llm_client(llm_config)
        self.log.info("LLM client initialized", provider=self.config.llm.provider)

        # Initialize userbot
        self.userbot = UserBot(self.config, self.llm, self.db)
        self.log.info("UserBot initialized")
    
    async def run(self):
        """Run the application"""
        try:
            # Validate configuration
            if not self._validate_config():
                return
            
            # Start userbot
            await self.userbot.start()
            
            self.log.info(
                "UserBot is running",
                persona_name=self.config.persona.name,
                active_chats=len(self.userbot.active_chats)
            )
            
            # Display startup info
            self._display_startup_info()
            
            # Keep running until interrupted
            await asyncio.Event().wait()
            
        except KeyboardInterrupt:
            self.log.info("Received interrupt signal, shutting down...")
        except Exception as e:
            self.log.error("Application error", error=str(e), exc_info=True)
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Gracefully shutdown all components"""
        self.log.info("Shutting down application...")

        if self.userbot:
            await self.userbot.stop()

        if self.db:
            await self.db.close()

        # Clear any cached sensitive data
        if hasattr(self, 'secrets_manager'):
            # Note: Fernet doesn't need explicit cleanup, but we can clear references
            pass

        self.log.info("Application shutdown complete")
    
    def _validate_config(self) -> bool:
        """Validate configuration before starting"""
        errors = []

        # Check Telegram credentials
        if not self.config.telegram.api_id or self.config.telegram.api_id == 0:
            errors.append("TELEGRAM_API_ID not configured")

        if not self.config.telegram.api_hash:
            errors.append("TELEGRAM_API_HASH not configured")

        if not self.config.telegram.phone_number:
            errors.append("TELEGRAM_PHONE_NUMBER not configured")

        # Check LLM configuration
        if self.config.llm.provider != "stub" and not self.config.llm.api_key:
            errors.append(f"{self.config.llm.provider.upper()}_API_KEY not configured")

        # Check response probability configuration
        if not isinstance(self.config.policy.response_probability, dict):
            errors.append("response_probability must be a dictionary with chat categories")
        else:
            required_categories = {"women", "travel", "local", "general"}
            missing_categories = required_categories - set(self.config.policy.response_probability.keys())
            if missing_categories:
                errors.append(f"Missing response probability categories: {missing_categories}")

        # Validate chat categories
        if not isinstance(self.config.telegram.chat_categories, dict):
            errors.append("chat_categories must be a dictionary")
        else:
            for category, keywords in self.config.telegram.chat_categories.items():
                if not isinstance(keywords, list):
                    errors.append(f"Keywords for category '{category}' must be a list")

        # Validate active hours
        if not isinstance(self.config.policy.active_hours, dict):
            errors.append("active_hours must be a dictionary")
        else:
            required_times = {"wake_up", "morning_active", "lunch_break", "afternoon_active", "evening_active", "sleep_time"}
            missing_times = required_times - set(self.config.policy.active_hours.keys())
            if missing_times:
                errors.append(f"Missing active hours configuration: {missing_times}")

        # Validate forbidden terms
        if not isinstance(self.config.policy.forbidden_terms, list):
            errors.append("forbidden_terms must be a list")

        # Validate search keywords
        if not isinstance(self.config.telegram.search_keywords, list) or len(self.config.telegram.search_keywords) == 0:
            errors.append("search_keywords must be a non-empty list")

        if errors:
            console.print("[red]Configuration errors:[/red]")
            for error in errors:
                console.print(f"  • {error}")
            console.print("\n[yellow]Please update your config.yaml or set environment variables[/yellow]")
            return False
        
        # Ensure Telethon session file exists to avoid repeated SendCode (FloodWait)
        session_name = self.config.telegram.session_name or "userbot_session"
        # Check in sessions directory first (Docker environment)
        session_dir = Path("/app/sessions")
        if session_dir.exists():
            session_path = session_dir / (session_name + ".session")
        else:
            # Fallback to current directory (local development)
            session_path = Path(session_name + ".session")
            
        if not session_path.exists():
            console.print("[red]Telegram session not found[/red]")
            console.print(f"Expected session file: [cyan]{session_path}[/cyan]")
            console.print("\n[yellow]Create the session interactively first:[/yellow]")
            console.print("  python scripts/create_session_qr_telethon.py")
            console.print("  python scripts/create_session_phone_telethon.py")
            console.print("\nIf running via Docker compose:")
            console.print("  docker compose --env-file ~/.ai-userbot.env -f docker-compose.ai-userbot.yml run --rm ai-userbot python scripts/create_session_qr_telethon.py")
            console.print("  docker compose --env-file ~/.ai-userbot.env -f docker-compose.ai-userbot.yml run --rm ai-userbot python scripts/create_session_phone_telethon.py")
            return False

        return True
    
    def _display_startup_info(self):
        """Display startup information"""
        console.print("\n[green]✨ AI UserBot Started Successfully![/green]\n")
        
        console.print(f"[cyan]Persona:[/cyan] {self.config.persona.name}, {self.config.persona.age} лет")
        console.print(f"[cyan]Интересы:[/cyan] {', '.join(self.config.persona.interests[:3])}...")
        console.print(f"[cyan]LLM Provider:[/cyan] {self.config.llm.provider}")
        console.print(f"[cyan]Active Chats:[/cyan] {len(self.userbot.active_chats)}")
        console.print(f"[cyan]Search Keywords:[/cyan] {', '.join(self.config.telegram.search_keywords)}")
        
        console.print("\n[yellow]Monitoring:[/yellow]")
        console.print(f"  • Min gap between messages: {self.config.policy.min_gap_seconds_per_chat}s")
        console.print(f"  • Max messages per hour: {self.config.policy.max_replies_per_hour_per_chat}")
        console.print(f"  • Promotion probability: {self.config.policy.promotion_probability * 100:.1f}%")
        
        console.print("\n[dim]Press Ctrl+C to stop[/dim]\n")


async def main():
    """Main entry point"""
    # Check config file
    config_path = Path("configs/config.yaml")
    if not config_path.exists():
        console.print("[red]Error:[/red] Config not found at configs/config.yaml")
        console.print("Copy configs/config.example.yaml to configs/config.yaml and configure it")
        sys.exit(1)
    
    # Load config and setup logging
    try:
        cfg = load_config(config_path)
        setup_logging(cfg.app.logging_level)
    except Exception as e:
        console.print(f"[red]Error loading config:[/red] {e}")
        sys.exit(1)
    
    # Create and run application
    app = Application(config_path)
    await app.initialize()
    await app.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Goodbye![/yellow]")
    except Exception as e:
        console.print(f"\n[red]Fatal error:[/red] {e}")
        sys.exit(1)
