#!/usr/bin/env python3
"""
Bulletproof QR login for Pyrogram:
- Auto-refresh QR before expiry
- Handles DC migrate (LoginTokenMigrateTo) via auth.importLoginToken
- Finalizes after UpdateLoginToken and prints session string
- ASCII/PNG output; headless friendly

Usage examples:
  python scripts/create_session_qr_correct.py --ascii \
    --session-name sessions/userbot_session

Environment for convenience:
  TELEGRAM_API_ID / API_ID
  TELEGRAM_API_HASH / API_HASH
  SESSION_NAME (optional)
  QR_PNG (optional)
  QR_REFRESH_MARGIN (seconds, default 5)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import signal
import sys
import time
from typing import Optional, Tuple

from pyrogram import Client
from pyrogram.raw.functions.auth import ExportLoginToken, ImportLoginToken
from pyrogram.raw.types import UpdateLoginToken
from pyrogram.raw.types import auth as auth_types

try:
    import qrcode
except Exception:
    qrcode = None  # ASCII fallback only


def b64url_no_pad(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def make_deeplink(token_bytes: bytes) -> str:
    # Telegram deep link scheme for QR login
    return f"tg://login?token={b64url_no_pad(token_bytes)}"


def render_ascii_qr(deeplink: str):
    # High-contrast block QR for terminal scanning
    if qrcode is None:
        print("\n[!] qrcode not installed; showing deep link only:\n", deeplink)
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(deeplink)
    qr.make(fit=True)
    m = qr.get_matrix()
    BLACK, WHITE = "██", "  "
    print()
    # top quiet zone
    print(WHITE * (len(m[0]) + 2))
    for row in m:
        print(WHITE + "".join(BLACK if cell else WHITE for cell in row) + WHITE)
    # bottom quiet zone
    print(WHITE * (len(m[0]) + 2))
    print()


def save_png_qr(deeplink: str, path: str, open_viewer: bool):
    if qrcode is None:
        raise RuntimeError("qrcode is required for PNG output. Install with: pip install qrcode[pil]")
    img = qrcode.make(deeplink)
    img.save(path)
    if open_viewer:
        try:
            img.show()
        except Exception:
            pass


async def on_update_login_token(app: Client, stop_evt: asyncio.Event):
    @app.on_raw_update()
    async def _handler(_, update, __):  # type: ignore
        if isinstance(update, UpdateLoginToken):
            stop_evt.set()


async def export_token(app: Client, api_id: int, api_hash: str):
    res = await app.invoke(ExportLoginToken(api_id=api_id, api_hash=api_hash))
    if isinstance(res, auth_types.LoginToken):
        return "token", res
    if isinstance(res, auth_types.LoginTokenMigrateTo):
        return "migrate", res
    if isinstance(res, auth_types.LoginTokenSuccess):
        return "success", res
    raise RuntimeError("Unexpected ExportLoginToken result.")


async def finalize_after_update_fast(app: Client, api_id: int, api_hash: str) -> bool:
    """Finalize authorization with a short, rapid loop to avoid token expiry races.

    Tries multiple times in quick succession:
    - exportLoginToken → success? done
    - exportLoginToken → migrate? importLoginToken → success? done
    Otherwise retries a few times with tiny sleeps.
    """
    for _ in range(20):  # ~4 seconds at 200ms steps
        kind, obj = await export_token(app, api_id, api_hash)
        if kind == "success":
            return True
        if kind == "migrate":
            try:
                imported = await app.invoke(ImportLoginToken(token=obj.token))
            except Exception:
                await asyncio.sleep(0.2)
                continue
            if isinstance(imported, auth_types.LoginTokenSuccess):
                return True
        await asyncio.sleep(0.2)
    return False


async def qr_login_and_get_session(
    api_id: int,
    api_hash: str,
    session_name: str,
    refresh_margin_s: int,
    ascii_only: bool,
    png_path: Optional[str],
    open_png_viewer: bool,
) -> Tuple[str, str]:
    app = Client(session_name, api_id=api_id, api_hash=api_hash)
    await app.connect()

    try:
        # Listen for UpdateLoginToken
        update_evt = asyncio.Event()
        await on_update_login_token(app, update_evt)

        def show_qr_from_token(login_token: auth_types.LoginToken):
            deeplink = make_deeplink(login_token.token)
            if png_path:
                save_png_qr(deeplink, png_path, open_png_viewer)
                print(f"\nQR saved to {png_path} (scan with a logged-in Telegram app)")
            if ascii_only or not png_path:
                render_ascii_qr(deeplink)

        while True:
            kind, obj = await export_token(app, api_id, api_hash)

            if kind == "success":
                break

            if kind == "migrate":
                imported = await app.invoke(ImportLoginToken(token=obj.token))
                if isinstance(imported, auth_types.LoginTokenSuccess):
                    break
                if isinstance(imported, auth_types.LoginToken):
                    obj = imported
                    kind = "token"
                else:
                    continue  # loop re-exports

            if kind == "token":
                show_qr_from_token(obj)

                # Use expires to refresh slightly before expiry; meanwhile poll the update event rapidly.
                now = int(time.time())
                expires = getattr(obj, "expires", now + 60)
                deadline = max(now + 1, int(expires - refresh_margin_s))

                # Poll quickly for UpdateLoginToken to minimize race with expiry
                while time.time() < deadline:
                    if update_evt.is_set():
                        ok = await finalize_after_update_fast(app, api_id, api_hash)
                        if ok:
                            update_evt.clear()
                            return await app.export_session_string(), f"@{(await app.get_me()).username or (await app.get_me()).id}"
                        update_evt.clear()
                    await asyncio.sleep(0.2)
                # No update before margin; loop will re-export and print a fresh QR

        # Authorized → export session string (optional convenience)
        session_string = await app.export_session_string()
        me = await app.get_me()
        me_display = f"@{getattr(me, 'username', None) or me.id}"
        return session_string, me_display

    finally:
        await app.disconnect()


def parse_args() -> argparse.Namespace:
    # Prefer TELEGRAM_* envs, fallback to API_ID/API_HASH
    env_api_id = os.getenv("TELEGRAM_API_ID") or os.getenv("API_ID")
    env_api_hash = os.getenv("TELEGRAM_API_HASH") or os.getenv("API_HASH")
    env_session = os.getenv("SESSION_NAME", "qr_session")
    p = argparse.ArgumentParser(description="Pyrogram QR login (robust) → session string")
    p.add_argument("--api-id", type=int, default=env_api_id, required=env_api_id is None)
    p.add_argument("--api-hash", type=str, default=env_api_hash, required=env_api_hash is None)
    p.add_argument("--session-name", type=str, default=env_session)
    p.add_argument("--ascii", action="store_true", help="Force ASCII QR in terminal")
    p.add_argument("--png", type=str, default=os.getenv("QR_PNG"), help="Save QR to this PNG file")
    p.add_argument("--no-view", action="store_true", help="Do not open the PNG viewer")
    p.add_argument("--refresh-margin", type=int, default=int(os.getenv("QR_REFRESH_MARGIN", "5")),
                   help="Seconds before expiry to refresh the QR")
    return p.parse_args()


def install_signal_handlers(loop: asyncio.AbstractEventLoop):
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, loop.stop)
        except NotImplementedError:
            pass


def main():
    args = parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    install_signal_handlers(loop)

    try:
        session_string, me_display = loop.run_until_complete(
            qr_login_and_get_session(
                api_id=int(args.api_id),
                api_hash=str(args.api_hash),
                session_name=args.session_name,
                refresh_margin_s=args.refresh_margin,
                ascii_only=bool(args.ascii),
                png_path=args.png,
                open_png_viewer=not args.no_view,
            )
        )
        print(f"\n✅ Logged in as: {me_display}")
        print("\n=== SESSION STRING ===")
        print(session_string)
        print(f"\nSaved session file: {args.session_name}.session")
        print("Keep this session string SECRET.")
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as e:
        print(f"\n[!] Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        loop.close()


if __name__ == "__main__":
    main()
