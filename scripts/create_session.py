#!/usr/bin/env python3
"""
One-time Pyrogram session creator for AI-Userbot.

Run inside the container to generate a .session file based on config:

  docker compose -f docker-compose.ai-userbot.yml exec -it ai-userbot-persona \
    python scripts/create_session.py

It will:
  - Load TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE_NUMBER from env
  - Load session path from configs/config.yaml (telegram.session_name)
  - Ask for the SMS/Telegram code and optional 2FA password
  - Save session file so the bot can start without prompts next time
"""

from __future__ import annotations

import asyncio
import os
import sys
from getpass import getpass

from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, FloodWait

from src.ai_userbot.config import load_config


async def main() -> int:
    cfg = load_config()

    api_id = int(os.getenv("TELEGRAM_API_ID", 0))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    phone = os.getenv("TELEGRAM_PHONE_NUMBER", "")

    if not api_id or not api_hash or not phone:
        print("Missing TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE_NUMBER in env", file=sys.stderr)
        return 2

    # Ensure we store session under sessions/ and use absolute path inside container
    session_name = cfg.telegram.session_name or "userbot_session"
    if "/" not in session_name:
        session_name = f"sessions/{session_name}"
    if not os.path.isabs(session_name):
        session_name = os.path.join("/app", session_name)
    # Ensure session directory exists
    session_dir = os.path.dirname(session_name)
    if session_dir:
        os.makedirs(session_dir, exist_ok=True)
    print(f"Using session name/path: {session_name}")

    app = Client(
        name=session_name,
        api_id=api_id,
        api_hash=api_hash,
        phone_number=phone,
    )

    await app.connect()
    # Pyrogram v2 compatibility: no is_authorized(); try get_me()
    try:
        await app.get_me()
        print("Already authorized; session is valid.")
        await app.disconnect()
        return 0
    except Exception:
        pass

    print("Sending login code to your Telegram...")
    try:
        sent = await app.send_code(phone)
    except FloodWait as e:
        wait_s = getattr(e, "x", None) or getattr(e, "value", None) or 60
        print(f"FloodWait: need to wait {wait_s} seconds before retrying...")
        await asyncio.sleep(int(wait_s) + 1)
        sent = await app.send_code(phone)
    code = input("Enter the code you received (digits): ").strip()

    try:
        # Try to complete sign-in with code
        await app.sign_in(
            phone_number=phone,
            code=code,
            phone_code_hash=sent.phone_code_hash,
        )
    except SessionPasswordNeeded:
        pwd = os.getenv("TELEGRAM_2FA_PASSWORD") or getpass("Enter your 2FA password: ")
        await app.check_password(password=pwd)

    print("Logged in successfully; saving session...")
    await app.disconnect()
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)
