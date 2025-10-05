#!/usr/bin/env python3
"""
QR-based Pyrogram session creator for AI-Userbot.

Steps:
  - Connect without sending SMS code
  - Request a QR login token from Telegram
  - Render QR in terminal (ASCII) and print URL as fallback
  - Wait until you scan and approve in Telegram app
  - Save .session under /app/sessions (volume-backed)
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import qrcode
from pyrogram import Client
from pyrogram.errors import FloodWait

from src.ai_userbot.config import load_config


def _resolve_session_path(name: str) -> str:
    if "/" not in name:
        name = f"sessions/{name}"
    if not os.path.isabs(name):
        name = os.path.join("/app", name)
    Path(os.path.dirname(name)).mkdir(parents=True, exist_ok=True)
    return name


async def main() -> int:
    cfg = load_config()

    api_id = int(os.getenv("TELEGRAM_API_ID", 0))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        print("Missing TELEGRAM_API_ID/TELEGRAM_API_HASH in env", file=sys.stderr)
        return 2

    session_name = cfg.telegram.session_name or "userbot_session"
    session_name = _resolve_session_path(session_name)
    print(f"Using session name/path: {session_name}")

    app = Client(
        name=session_name,
        api_id=api_id,
        api_hash=api_hash,
    )

    await app.connect()

    # Already logged in?
    try:
        await app.get_me()
        print("Already authorized; session is valid.")
        await app.disconnect()
        return 0
    except Exception:
        pass

    try:
        # Request QR login token
        qr = await app.qr_login()
    except AttributeError:
        print("This Pyrogram version doesn't support qr_login(). Rebuild the image without cache to update Pyrogram:", file=sys.stderr)
        print("  docker compose -f docker-compose.ai-userbot.yml build --no-cache ai-userbot", file=sys.stderr)
        await app.disconnect()
        return 3
    except FloodWait as e:
        wait_s = int(getattr(e, "x", 60))
        print(f"FloodWait from Telegram: wait {wait_s} seconds before requesting QR again.")
        await app.disconnect()
        return 4

    # Render ASCII QR in terminal
    try:
        qr_code = qrcode.QRCode(border=1)
        qr_code.add_data(qr.url)  # type: ignore[attr-defined]
        qr_code.make(fit=True)
        print("\nScan this QR with Telegram (Settings → Devices → Link Desktop Device):\n")
        qr_code.print_ascii(invert=True)
        print("\nIf the QR isn't readable, open this URL on a screen and scan it:")
        print(qr.url)  # type: ignore[attr-defined]
        print("")
    except Exception as e:
        print(f"Couldn't render QR: {e}. Use URL instead:\n{getattr(qr, 'url', '<no url>')}\n")

    # Wait until login is approved in Telegram app
    print("Waiting for approval in Telegram app...")
    try:
        await qr.wait()  # type: ignore[attr-defined]
    except Exception as e:
        print(f"QR login failed: {e}", file=sys.stderr)
        await app.disconnect()
        return 5

    # Save session
    try:
        await app.get_me()
        print("Logged in successfully; saving session...")
    except Exception:
        print("Login appears incomplete; cannot confirm.", file=sys.stderr)

    await app.disconnect()
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)
