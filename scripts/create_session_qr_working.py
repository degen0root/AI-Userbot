#!/usr/bin/env python3
"""
Working QR code session creator for AI-Userbot.
Based on the excellent example from the user.
"""

import asyncio
import base64
import os
import sys
from dataclasses import dataclass

# Add the app directory to Python path
sys.path.insert(0, '/app')

from pyrogram import Client
from pyrogram.raw.functions.auth import ExportLoginToken, ImportLoginToken
from pyrogram.raw.types import (
    UpdateLoginToken,
    auth as auth_types,
)
import qrcode


@dataclass
class Config:
    api_id: int
    api_hash: str
    session_name: str = "userbot_session"


def b64url_no_pad(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def show_qr_for_token(token_bytes: bytes):
    deep_link = f"tg://login?token={b64url_no_pad(token_bytes)}"
    print("\nScan this QR with a Telegram app that is already logged in:")
    print(deep_link)  # fallback if QR viewer can't open
    # Render a QR image and show it
    qrcode.make(deep_link).show()


async def finalize_after_update(app: Client, cfg: Config) -> str:
    """
    Called when we receive UpdateLoginToken.
    Re-export or import the token (if migrated) to finish authorization,
    then return the session string.
    """
    res = await app.invoke(ExportLoginToken(api_id=cfg.api_id, api_hash=cfg.api_hash))

    # Case 1: Success right away
    if isinstance(res, auth_types.LoginTokenSuccess):
        return await app.export_session_string()

    # Case 2: Need to migrate to another DC first
    if isinstance(res, auth_types.LoginTokenMigrateTo):
        # Connect to target DC and import token there
        imported = await app.invoke(ImportLoginToken(token=res.token))
        if isinstance(imported, auth_types.LoginTokenSuccess):
            return await app.export_session_string()
        if isinstance(imported, auth_types.LoginToken):
            # Rare: still a token — user may need to rescan on target DC
            show_qr_for_token(imported.token)
            print("Waiting for the QR to be scanned again (after DC migrate)…")
            return await wait_for_qr_and_finish(app, cfg)

    # Case 3: We got a new token again; show it and wait one more time
    if isinstance(res, auth_types.LoginToken):
        show_qr_for_token(res.token)
        print("Waiting for the QR to be scanned…")
        return await wait_for_qr_and_finish(app, cfg)

    raise RuntimeError("Unexpected state during QR finalize flow.")


async def wait_for_qr_and_finish(app: Client, cfg: Config) -> str:
    """
    Wait for UpdateLoginToken, then finalize and return the session string.
    """
    # Wait for the specific raw update
    async for update in app.listen_raw():
        if isinstance(update, UpdateLoginToken):
            return await finalize_after_update(app, cfg)


async def main():
    # Read config from environment
    api_id = int(os.getenv("TELEGRAM_API_ID", 0))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    session_name = "userbot_session"

    if not api_id or not api_hash:
        print("ERROR: Missing TELEGRAM_API_ID or TELEGRAM_API_HASH in environment", file=sys.stderr)
        return 1

    cfg = Config(api_id=api_id, api_hash=api_hash, session_name=session_name)

    # Start Pyrogram (no prior login needed)
    app = Client(cfg.session_name, api_id=cfg.api_id, api_hash=cfg.api_hash)

    await app.connect()

    try:
        # 1) First export -> display QR
        exported = await app.invoke(ExportLoginToken(api_id=cfg.api_id, api_hash=cfg.api_hash))

        if isinstance(exported, auth_types.LoginToken):
            show_qr_for_token(exported.token)
            print("Waiting for the QR to be scanned…")
            session_string = await wait_for_qr_and_finish(app, cfg)

        elif isinstance(exported, auth_types.LoginTokenMigrateTo):
            # Some accounts are served by a different DC; hop & import
            imported = await app.invoke(ImportLoginToken(token=exported.token))
            if isinstance(imported, auth_types.LoginTokenSuccess):
                session_string = await app.export_session_string()
            elif isinstance(imported, auth_types.LoginToken):
                show_qr_for_token(imported.token)
                print("Waiting for the QR to be scanned…")
                session_string = await wait_for_qr_and_finish(app, cfg)
            else:
                raise RuntimeError("Unexpected response after ImportLoginToken.")

        elif isinstance(exported, auth_types.LoginTokenSuccess):
            # (Rare) immediate success
            session_string = await app.export_session_string()

        else:
            raise RuntimeError("Unexpected response from ExportLoginToken.")

        me = await app.get_me()
        print(f"\n✅ Logged in as: @{getattr(me, 'username', None) or me.id}")
        print("\n=== SESSION STRING ===")
        print(session_string)
        print(f"\nSaved local session file: {cfg.session_name}.session")
        print("Keep this session string SECRET. Anyone with it can access your account.")

    finally:
        await app.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
