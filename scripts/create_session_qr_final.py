#!/usr/bin/env python3
"""
Final QR code session creator for AI-Userbot.
"""

import asyncio
import os
import sys
import base64

# Add the app directory to Python path
sys.path.insert(0, '/app')

from pyrogram import Client
from pyrogram.raw import functions, types
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
        
        # Wait for authorization using ImportLoginToken
        auth_attempts = 0
        max_attempts = 60  # 3 minutes timeout
        while auth_attempts < max_attempts:
            await asyncio.sleep(3)
            auth_attempts += 1
            try:
                # Try to import the login token
                result = await app.invoke(
                    functions.auth.ImportLoginToken(
                        token=r.token
                    )
                )
                
                if isinstance(result, types.auth.LoginTokenSuccess):
                    # Authorization successful, need to get user info
                    auth_result = result.authorization
                    if isinstance(auth_result, types.auth.Authorization):
                        user = auth_result.user
                        print(f"\n✅ Successfully logged in as: {user.first_name} (@{user.username if hasattr(user, 'username') else 'no username'})")
                        break
                elif isinstance(result, types.auth.LoginTokenMigrateTo):
                    print("\n❌ Need to migrate to DC:", result.dc_id)
                    # In production, you would handle DC migration here
                    await app.disconnect()
                    return 1
                else:
                    # Still waiting
                    print(".", end="", flush=True)
                    continue
            except Exception as e:
                # Check if we can get user info now
                try:
                    me = await app.get_me()
                    print(f"\n✅ Successfully logged in as: {me.first_name} (@{me.username})")
                    break
                except:
                    # Still waiting
                    print(".", end="", flush=True)
                    continue
        
        if auth_attempts >= max_attempts:
            print("\n❌ Authorization timeout. Please try again.")
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
