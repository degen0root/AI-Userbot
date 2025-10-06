#!/usr/bin/env python3
"""
Automated phone number session creator for AI-Userbot using Telethon.
Set TELEGRAM_CODE environment variable before running.
"""

import asyncio
import os
import sys

# Add the app directory to Python path
sys.path.insert(0, '/app')

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeeded, FloodWait


async def main():
    api_id = int(os.getenv("TELEGRAM_API_ID", 0))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    phone = os.getenv("TELEGRAM_PHONE_NUMBER", "")
    code = os.getenv("TELEGRAM_CODE", "")

    if not api_id or not api_hash or not phone:
        print("ERROR: Missing TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE_NUMBER in env", file=sys.stderr)
        return 2

    if not code:
        print("ERROR: Missing TELEGRAM_CODE in env. Please set it to the code you received.", file=sys.stderr)
        return 2

    session_name = "userbot_session"

    print("Creating Telethon client...")
    client = TelegramClient(session_name, api_id, api_hash)

    print("Connecting to Telegram...")
    await client.connect()

    # Check if already authorized
    if await client.is_user_authorized():
        print("Already authorized!")
        me = await client.get_me()
        print(f"Logged in as: {me.first_name} (@{me.username})")

        # Export session string
        session_string = client.session.save()
        print("\n=== SESSION STRING ===")
        print(session_string)
        print(f"\n💾 Session saved to: {session_name}.session")
        await client.disconnect()
        return 0

    print("Not authorized, sending code...")

    # Send code
    try:
        sent = await client.send_code_request(phone)
        print(f"Code sent to {phone}")
        print(f"Using code: {code}")
    except FloodWait as e:
        wait_s = getattr(e, "x", None) or getattr(e, "value", None) or 60
        print(f"FloodWait: need to wait {wait_s} seconds before retrying...")
        await asyncio.sleep(int(wait_s) + 1)
        sent = await client.send_code_request(phone)

    # Sign in with code
    try:
        await client.sign_in(phone, code)
    except SessionPasswordNeeded:
        pwd = os.getenv("TELEGRAM_2FA_PASSWORD", "")
        if not pwd:
            print("2FA password required but TELEGRAM_2FA_PASSWORD not set!", file=sys.stderr)
            await client.disconnect()
            return 3
        await client.sign_in(password=pwd)

    print("✅ Successfully logged in!")

    # Get user info to confirm
    me = await client.get_me()
    print(f"Logged in as: {me.first_name} (@{me.username})")

    # Export session string
    session_string = client.session.save()
    print("\n=== SESSION STRING ===")
    print(session_string)
    print(f"\n💾 Session saved to: {session_name}.session")
    print("Keep this session string SECRET. Anyone with it can access your account.")

    await client.disconnect()
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n❌ Cancelled by user")
        sys.exit(130)
