#!/usr/bin/env python3
"""
Correct QR code session creator for AI-Userbot.
"""

import asyncio
import os
import sys
import base64

# Add the app directory to Python path
sys.path.insert(0, '/app')

from pyrogram import Client
from pyrogram.raw import functions
import qrcode


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

    # Generate QR code
    try:
        print("Requesting login token...")
        r = await app.invoke(
            functions.auth.ExportLoginToken(
                api_id=api_id,
                api_hash=api_hash,
                except_ids=[]
            )
        )
        
        # Convert token to base64url format (no padding)
        token_base64url = base64.urlsafe_b64encode(r.token).decode('ascii').rstrip('=')
        
        # Create login URL with tg:// deep link format and base64url token
        login_url = f"tg://login?token={token_base64url}"
        
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
        qr.add_data(login_url)
        qr.make(fit=True)
        
        # Print QR code to console
        print("Scan this QR code with your Telegram app:\n")
        qr.print_ascii(invert=True)
        
        print(f"\nDebug info:")
        print(f"Token (hex): {r.token.hex()}")
        print(f"Token (base64url): {token_base64url}")
        print(f"Full URL: {login_url}")
        print("\nWaiting for authorization...")
        
        # Wait for authorization
        print("\n⏳ Please scan the QR code in Telegram and complete authorization...")
        print("The script will automatically check for authorization in 30 seconds...")

        # Wait 30 seconds for user to scan and authorize
        await asyncio.sleep(30)

        # Now check if we're authorized
        try:
            # Disconnect and reconnect with fresh session
            await app.disconnect()
            await app.connect()

            # Try to get user info - if this works, we're authorized
            me = await app.get_me()
            print(f"\n✅ Successfully logged in as: {me.first_name} (@{me.username})")

        except Exception as e:
            print(f"\n❌ Authorization failed: {e}")
            print("❌ Please try again or check if the QR code was scanned correctly")
            await app.disconnect()
            return 1
                
    except Exception as e:
        print(f"\nError during QR login: {e}")
        import traceback
        traceback.print_exc()
        await app.disconnect()
        return 1

    print("\nSaving session...")
    await app.disconnect()
    print("Session saved successfully!")
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nCancelled by user")
        sys.exit(130)
