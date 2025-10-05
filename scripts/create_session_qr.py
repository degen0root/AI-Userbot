#!/usr/bin/env python3
"""
QR code session creator for AI-Userbot.
"""

from __future__ import annotations

import asyncio
import os
import sys

from pyrogram import Client
from pyrogram.types import User

from src.ai_userbot.config import load_config


async def main() -> int:
    cfg = load_config()

    api_id = int(os.getenv("TELEGRAM_API_ID", 0))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")

    if not api_id or not api_hash:
        print("Missing TELEGRAM_API_ID / TELEGRAM_API_HASH in env", file=sys.stderr)
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
    )

    # Connect and check if already authorized
    await app.connect()
    try:
        me: User = await app.get_me()
        print(f"Already authorized as: {me.first_name} (@{me.username})")
        await app.disconnect()
        return 0
    except Exception:
        pass

    print("\n" + "="*50)
    print("QR CODE AUTHORIZATION")
    print("="*50 + "\n")

    # Generate QR code for login
    try:
        r = await app.invoke(
            functions.auth.ExportLoginToken(
                api_id=api_id,
                api_hash=api_hash,
                except_ids=[]
            )
        )
        
        # Display QR code
        print("Scan this QR code with your Telegram app:")
        print(f"\nhttps://telegram.org/dl?tg=tg://login?token={r.token.hex()}\n")
        print("Or use any QR scanner and open the link in Telegram.")
        print("\nWaiting for authorization...")
        
        # Wait for user to scan
        while True:
            await asyncio.sleep(2)
            try:
                # Check if authorized
                me: User = await app.get_me()
                print(f"\n✅ Successfully logged in as: {me.first_name} (@{me.username})")
                break
            except Exception:
                # Still waiting
                continue
                
    except Exception as e:
        print(f"Error during QR login: {e}")
        await app.disconnect()
        return 1

    print("Saving session...")
    await app.disconnect()
    return 0


if __name__ == "__main__":
    # Add missing import
    import sys
    sys.path.insert(0, '/app')
    
    from pyrogram.raw import functions
    
    try:
        rc = asyncio.run(main())
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)