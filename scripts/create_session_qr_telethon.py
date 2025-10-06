#!/usr/bin/env python3
"""
QR code session creator for AI-Userbot using Telethon.
"""

import asyncio
import os
import sys

# Add the app directory to Python path
sys.path.insert(0, '/app')

from telethon import TelegramClient, events
from telethon.sessions import StringSession
import qrcode


async def main():
    api_id = int(os.getenv("TELEGRAM_API_ID", 0))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")

    if not api_id or not api_hash:
        print("ERROR: Missing TELEGRAM_API_ID or TELEGRAM_API_HASH in environment", file=sys.stderr)
        return 1

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

    print("Not authorized, generating QR code...")

    # Generate QR code for login
    qr_login = await client.qr_login()

    print("\n" + "="*50)
    print("QR CODE AUTHORIZATION")
    print("="*50 + "\n")

    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=1,
    )
    qr.add_data(qr_login.url)
    qr.make(fit=True)

    # Print QR code to console
    print("Scan this QR code with your Telegram app:\n")
    qr.print_ascii(invert=True)

    print(f"\nDirect link: {qr_login.url}")
    print("\n✅ QR code generated successfully!")
    print("📱 Please scan the QR code in Telegram and complete authorization.")
    print("⏳ The script will wait for authorization...")

    try:
        # Wait for authorization
        await qr_login.wait()

        print("✅ Successfully logged in!")

        # Get user info
        me = await client.get_me()
        print(f"Logged in as: {me.first_name} (@{me.username})")

        # Export session string
        session_string = client.session.save()
        print("\n=== SESSION STRING ===")
        print(session_string)
        print(f"\n💾 Session saved to: {session_name}.session")
        print("Keep this session string SECRET. Anyone with it can access your account.")

    except Exception as e:
        print(f"\n❌ Authorization failed: {e}")
        await client.disconnect()
        return 1

    await client.disconnect()
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n❌ Cancelled by user")
        sys.exit(130)
