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
from pyrogram.errors import RPCError
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

    # Correct flow: export ONCE, display URL, then import SAME token until success or expiry
    while True:
        try:
            first = await app.invoke(ExportLoginToken(api_id=api_id, api_hash=api_hash, except_ids=[]))
        except Exception as e:
            print(f"ExportLoginToken failed: {e}", file=sys.stderr)
            await app.disconnect()
            return 3

        token_to_use: bytes | None = None
        if isinstance(first, auth_types.LoginToken):
            token_to_use = first.token
        elif isinstance(first, auth_types.LoginTokenMigrateTo):
            # Switch DC and get a token valid for that DC
            try:
                await app.session.set_dc(first.dc_id, first.ip, first.port)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                imp = await app.invoke(ImportLoginToken(token=first.token))
            except RPCError as e:
                print(f"Initial migrate import error: {e}", file=sys.stderr)
                continue
            if isinstance(imp, auth_types.LoginTokenSuccess):
                print("QR login completed immediately after DC migrate ✔")
                break
            elif isinstance(imp, auth_types.LoginToken):
                token_to_use = imp.token
            else:
                print("Unexpected import result; retrying…", file=sys.stderr)
                continue
        else:
            print("Unexpected export result; retrying…", file=sys.stderr)
            continue

        # Show link once for this token
        url = f"https://t.me/login?token={_b64url_no_pad(token_to_use)}"
        _print_qr(url)
        print("Waiting for approval in Telegram…")

        # Poll import on the same token
        while True:
            try:
                res = await app.invoke(ImportLoginToken(token=token_to_use))
            except RPCError as e:
                msg = str(e)
                if "AUTH_TOKEN_EXPIRED" in msg:
                    print("Token expired; generating a new one…")
                    break  # back to export a fresh token
                # Not accepted yet or transient error
                await asyncio.sleep(0.6)
                continue

            if isinstance(res, auth_types.LoginTokenSuccess):
                print("QR login completed ✔")
                # Confirm and save
                try:
                    await app.disconnect(); await app.connect()
                    me = await app.get_me()
                    print(f"Authorized as: {getattr(me, 'first_name', '')} ({getattr(me, 'id', '')})")
                    print("Saved session.")
                except Exception:
                    print("Authorized; session saved.")
                await app.disconnect()
                return 0
            elif isinstance(res, auth_types.LoginTokenMigrateTo):
                # Switch DC and try the same token again
                try:
                    await app.session.set_dc(res.dc_id, res.ip, res.port)  # type: ignore[attr-defined]
                except Exception:
                    pass
                await asyncio.sleep(0.2)
                continue
            else:
                # Still pending
                await asyncio.sleep(0.6)


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)
