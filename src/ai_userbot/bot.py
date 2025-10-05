from __future__ import annotations

import asyncio
import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import AppConfig
from .llm import LLMClient, LLMRequest, StubLLM
from .policy import ParticipationPolicy


log = logging.getLogger(__name__)


class BotService:
    def __init__(self, cfg: AppConfig, llm: Optional[LLMClient] = None):
        self.cfg = cfg
        self.llm = llm or StubLLM()
        self.policy = ParticipationPolicy(cfg.policy, cfg.telegram)
        self.app: Optional[Application] = None

    def build(self) -> Application:
        app = (
            ApplicationBuilder()
            .token(self.cfg.telegram_bot_token)
            .rate_limiter(AIORateLimiter())
            .build()
        )
        app.add_handler(CommandHandler("start", self.on_start))
        app.add_handler(CommandHandler("help", self.on_help))
        app.add_handler(CommandHandler("ping", self.on_ping))
        app.add_handler(CommandHandler("chatid", self.on_chatid))
        # Group text messages (exclude commands)
        app.add_handler(
            MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, self.on_group_text)
        )
        self.app = app
        return app

    async def on_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            "Привет! Я AI-ассистент. Добавьте меня в группу, и я буду отвечать уместно и аккуратно."
        )

    async def on_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        policy = self.cfg.policy
        text = (
            "Я отвечаю в группах, где меня добавили, редко и по делу.\n"
            f"Задержка между ответами: ~{policy.min_gap_seconds_per_chat}s.\n"
            f"Ограничение на час: {policy.max_replies_per_hour_per_chat}.\n"
            "Я всегда соблюдаю правила чата."
        )
        await update.effective_message.reply_text(text)

    async def on_ping(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text("pong")

    async def on_chatid(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        if not chat:
            return
        await update.effective_message.reply_text(f"chat_id: {chat.id}")

    async def on_group_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat:
            return

        decision = self.policy.decide(chat.id, msg.text or "")
        if not decision.should_reply:
            log.debug("skip: %s", decision.reason)
            return

        # Build the prompt minimally; in production add prior context if desired
        req = LLMRequest(prompt=msg.text or "")
        try:
            answer = self.llm.generate(req)
        except Exception as e:
            log.exception("LLM error: %s", e)
            return

        lines = []
        if decision.disclosure_text:
            lines.append(decision.disclosure_text)
        lines.append(answer)
        if decision.include_promotion:
            promo = self.cfg.policy.promotion_text.strip()
            if promo:
                lines.append(promo)
        text = "\n".join(lines)

        await msg.reply_text(text)

    async def run(self) -> None:
        if not self.app:
            self.build()
        assert self.app is not None
        log.info("Starting bot %s", self.cfg.app.name)
        await self.app.initialize()
        await self.app.start()
        try:
            await self.app.updater.start_polling()
            await asyncio.Event().wait()  # run forever
        finally:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
