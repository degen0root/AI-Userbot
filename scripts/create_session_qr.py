#!/usr/bin/env python3
"""
QR-based Pyrogram session creator using raw API (ExportLoginToken/ImportLoginToken).

Flow:
  1) Export a login token and render a tg://login?token=... QR
  2) When another Telegram client scans the QR, we receive UpdateLoginToken
  3) Export again to finalize; handle DC migration by ImportLoginToken
  4) On success, the session becomes authorized and is saved
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path

import qrcode
from pyrogram import Client
from pyrogram.raw.functions.auth import ExportLoginToken, ImportLoginToken
from pyrogram.raw.types import UpdateLoginToken
from pyrogram.raw.types import auth as auth_types

from src.ai_userbot.config import load_config


def _resolve_session_path(name: str) -> str:
    if "/" not in name:
        name = f"sessions/{name}"
    if not os.path.isabs(name):
        name = os.path.join("/app", name)
    Path(os.path.dirname(name)).mkdir(parents=True, exist_ok=True)
    return name


def _b64url_no_pad(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _print_qr(deeplink: str) -> None:
    print("\nScan this QR with Telegram (Settings → Devices → Link Desktop Device):\n")
    qr = qrcode.QRCode(border=1)
    qr.add_data(deeplink)
    qr.make(fit=True)
    try:
        qr.print_ascii(invert=True)
    except Exception:
        # Fallback: show URL if ASCII isn't available
        pass
    print("\nIf the QR isn't readable, open this URL on a screen and scan it:")
    print(deeplink)
    print("")


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

    # Connect without triggering phone-code login
    await app.connect()
    # Already logged in?
    try:
        await app.get_me()
        print("Already authorized; session is valid.")
        await app.disconnect()
        return 0
    except Exception:
        pass

    # First export
    try:
        res = await app.invoke(ExportLoginToken(api_id=api_id, api_hash=api_hash, except_ids=[]))
    except Exception as e:
        print(f"ExportLoginToken failed: {e}", file=sys.stderr)
        await app.stop()
        return 3

    if isinstance(res, auth_types.LoginToken):
        deeplink = f"tg://login?token={_b64url_no_pad(res.token)}"
        _print_qr(deeplink)
        # Poll until success
        print("Waiting for QR to be scanned…")
        while True:
            await asyncio.sleep(2)
            res2 = await app.invoke(ExportLoginToken(api_id=api_id, api_hash=api_hash, except_ids=[]))
            if isinstance(res2, auth_types.LoginTokenSuccess):
                print("QR login completed ✔")
                break
            elif isinstance(res2, auth_types.LoginTokenMigrateTo):
                imported = await app.invoke(ImportLoginToken(token=res2.token))
                if isinstance(imported, auth_types.LoginTokenSuccess):
                    print("QR login completed after DC migrate ✔")
                    break
                elif isinstance(imported, auth_types.LoginToken):
                    deeplink = f"tg://login?token={_b64url_no_pad(imported.token)}"
                    _print_qr(deeplink)
            elif isinstance(res2, auth_types.LoginToken):
                # Still waiting; optionally refresh QR
                pass
    elif isinstance(res, auth_types.LoginTokenMigrateTo):
        imported = await app.invoke(ImportLoginToken(token=res.token))
        if isinstance(imported, auth_types.LoginTokenSuccess):
            print("QR login completed immediately after DC migrate ✔")
        elif isinstance(imported, auth_types.LoginToken):
            deeplink = f"tg://login?token={_b64url_no_pad(imported.token)}"
            _print_qr(deeplink)
            print("Waiting for QR to be scanned…")
            while True:
                await asyncio.sleep(2)
                res2 = await app.invoke(ExportLoginToken(api_id=api_id, api_hash=api_hash, except_ids=[]))
                if isinstance(res2, auth_types.LoginTokenSuccess):
                    print("QR login completed ✔")
                    break
    else:
        print("Unexpected exportLoginToken result; retry later.", file=sys.stderr)
        await app.disconnect()
        return 5

    # Confirm and save
    try:
        # Reconnect to ensure session reflects new auth
        await app.disconnect()
        await app.connect()
        me = await app.get_me()
        print(f"Authorized as: {getattr(me, 'first_name', '')} ({getattr(me, 'id', '')})")
        print("Saved session.")
    except Exception as e:
        print(f"Authorized, but couldn't fetch profile — continuing. ({e})")

    await app.disconnect()
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)
