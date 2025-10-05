#!/usr/bin/env python3
"""
Simple QR code session creator for AI-Userbot.
"""

import asyncio
import base64
import os
import sys

# Add the app directory to Python path
sys.path.insert(0, '/app')

from pyrogram import Client
from pyrogram.raw.functions.auth import ExportLoginToken
import qrcode


def b64url_no_pad(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


async def main():
    api_id = int(os.getenv("TELEGRAM_API_ID", 0))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")

    if not api_id or not api_hash:
        print("ERROR: Missing TELEGRAM_API_ID or TELEGRAM_API_HASH in environment", file=sys.stderr)
        return 1

    session_path = "/app/sessions/userbot_session"

    print("Creating Pyrogram client...")
    app = Client(
        name=session_path,
        api_id=api_id,
        api_hash=api_hash,
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
        print("Not authorized, generating QR code...")

    # Generate login token
    exported = await app.invoke(ExportLoginToken(api_id=api_id, api_hash=api_hash, except_ids=[]))

    if hasattr(exported, 'token'):
        # Generate QR code
        deep_link = f"tg://login?token={b64url_no_pad(exported.token)}"

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
        qr.add_data(deep_link)
        qr.make(fit=True)

        # Print QR code to console
        print("Scan this QR code with your Telegram app:\n")
        qr.print_ascii(invert=True)

        print(f"\nDirect link: {deep_link}")
        print("\n✅ QR code generated successfully!")
        print("📱 Please scan the QR code in Telegram and complete authorization.")
        print("⏳ After authorization, press Ctrl+C to continue...")

        try:
            # Wait for user to interrupt
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n\n🔄 Checking authorization status...")

        # Check if authorized
        try:
            # Disconnect and reconnect with fresh session
            await app.disconnect()
            await app.connect()

            # Try to get user info
            me = await app.get_me()
            print(f"\n✅ Successfully logged in as: {me.first_name} (@{me.username})")

            # Export session string
            session_string = await app.export_session_string()
            print("\n=== SESSION STRING ===")
            print(session_string)
            print(f"\n💾 Session saved to: {session_path}.session")

        except Exception as e:
            print(f"\n❌ Authorization failed: {e}")
            print("❌ Please try again or check if the QR code was scanned correctly")
            await app.disconnect()
            return 1

    await app.disconnect()
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n❌ Cancelled by user")
        sys.exit(130)
