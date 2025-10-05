#!/usr/bin/env python3
"""
Phone number session creator for AI-Userbot.
"""

import asyncio
import os
import sys

# Add the app directory to Python path
sys.path.insert(0, '/app')

from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, FloodWait


async def main():
    api_id = int(os.getenv("TELEGRAM_API_ID", 0))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    phone = os.getenv("TELEGRAM_PHONE_NUMBER", "")

    if not api_id or not api_hash or not phone:
        print("ERROR: Missing TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE_NUMBER in env", file=sys.stderr)
        return 2

    session_path = "/app/sessions/userbot_session"

    print("Creating Pyrogram client...")
    app = Client(
        name=session_path,
        api_id=api_id,
        api_hash=api_hash,
        phone_number=phone,
    )

    print("Connecting to Telegram...")
    await app.connect()

    # Check if already authorized
    try:
        me = await app.get_me()
        print(f"Already authorized as: {me.first_name} (@{me.username})")
        await app.disconnect()
        return 0
    except Exception:
        print("Not authorized, sending code...")

    # Send code
    try:
        sent = await app.send_code(phone)
        print(f"Code sent to {phone}")
        print("Please check your Telegram app for the confirmation code.")
    except FloodWait as e:
        wait_s = getattr(e, "x", None) or getattr(e, "value", None) or 60
        print(f"FloodWait: need to wait {wait_s} seconds before retrying...")
        await asyncio.sleep(int(wait_s) + 1)
        sent = await app.send_code(phone)

    # Get code from user
    print("Enter the code you received:")
    code = input().strip()

    # Sign in with code
    try:
        await app.sign_in(
            phone_number=phone,
            phone_code=code,
            phone_code_hash=sent.phone_code_hash,
        )
    except SessionPasswordNeeded:
        print("2FA password required. Enter your 2FA password:")
        pwd = input().strip()
        await app.check_password(password=pwd)

    print("✅ Successfully logged in!")

    # Get user info to confirm
    me = await app.get_me()
    print(f"Logged in as: {me.first_name} (@{me.username})")

    await app.disconnect()
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nCancelled by user")
        sys.exit(130)
