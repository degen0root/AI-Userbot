#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Join a list of Telegram chats (groups/channels) using a Telethon user session,
optionally filtering/sorting targets by Persona interests.

Usage:
  pip install telethon pyyaml
  python scripts/join_chats.py --config configs/config.yaml \
    --links-file scripts/targets.txt --session-name sessions/userbot_session

Notes:
- Requires a valid Telethon .session for the account (user account, не бот).
- Handles FloodWait; respects a small throttle between joins.
- Expects one t.me link/username per line in the links file.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from typing import Iterable, Tuple

from telethon import TelegramClient, errors
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from src.ai_userbot.config import load_config
from src.ai_userbot.persona import PersonaManager


INVITE_RE = re.compile(r"t\.me/joinchat/\+?([A-Za-z0-9_-]+)|t\.me/\+([A-Za-z0-9_-]+)")
USERNAME_RE = re.compile(r"t\.me/([A-Za-z0-9_]+)")


def load_links(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def extract_target(s: str) -> Tuple[str, str]:
    """Return (kind, value): kind in {invite, username}. Raises ValueError for unsupported."""
    m = INVITE_RE.search(s)
    if m:
        invite = m.group(1) or m.group(2)
        return ("invite", invite)
    m = USERNAME_RE.search(s)
    if m:
        return ("username", m.group(1))
    # Bare username without URL
    if re.fullmatch(r"[A-Za-z0-9_]{3,}", s):
        return ("username", s)
    raise ValueError(f"Unsupported target: {s}")


def persona_keywords() -> set[str]:
    # Instantiate PersonaManager from config to get favorite_topics keywords
    cfg = load_config("configs/config.yaml") if Path("configs/config.yaml").exists() else load_config("configs/config.example.yaml")
    pm = PersonaManager(cfg.persona)
    kws: set[str] = set()
    topics = getattr(pm, "favorite_topics", {})
    for lst in topics.values():
        for kw in lst:
            kws.add(kw.lower())
    # Also add generic interests
    for it in cfg.persona.interests:
        kws.add(it.lower())
    return kws


def score_by_persona(target: str, kws: set[str]) -> int:
    t = target.lower()
    # Score by keyword presence in slug/username
    return sum(1 for k in kws if k in t)


async def join_one(client: TelegramClient, raw: str, throttle_s: float) -> tuple[str, str]:
    try:
        kind, value = extract_target(raw)
    except ValueError:
        return raw, "skip_unsupported"
    try:
        if kind == "invite":
            await client(ImportChatInviteRequest(hash=value))
        else:
            await client(JoinChannelRequest(value))
        await asyncio.sleep(throttle_s)
        return raw, "joined"
    except errors.UserAlreadyParticipantError:
        return raw, "already_member"
    except errors.FloodWaitError as e:
        await asyncio.sleep(e.seconds + 1)
        try:
            if kind == "invite":
                await client(ImportChatInviteRequest(hash=value))
            else:
                await client(JoinChannelRequest(value))
            await asyncio.sleep(throttle_s)
            return raw, "joined_after_floodwait"
        except Exception as e2:
            return raw, f"error_after_floodwait: {type(e2).__name__}: {e2}"
    except Exception as e:
        return raw, f"error: {type(e).__name__}: {e}"


async def run_join(
    config: str,
    session_name: str,
    links_file: str,
    throttle: float,
    persona_filter: bool,
    sort_by_score: bool,
    dry_run: bool,
) -> int:
    links_path = Path(links_file)
    if not links_path.exists():
        print(f"Links file not found: {links_path}", file=sys.stderr)
        return 2

    cfg_path = Path(config)
    cfg = load_config(cfg_path) if cfg_path.exists() else load_config()

    targets = load_links(links_path)
    if not targets:
        print("No targets to join", file=sys.stderr)
        return 2

    kws = persona_keywords() if (persona_filter or sort_by_score) else set()
    scored: list[tuple[int, str]] = [(score_by_persona(t, kws), t) for t in targets]
    if persona_filter:
        scored = [it for it in scored if it[0] > 0]
        if not scored:
            print("No targets matched Persona interests", file=sys.stderr)
            return 2
    if sort_by_score:
        scored.sort(key=lambda x: x[0], reverse=True)
    # Flatten
    final_targets = [t for _, t in scored] if (persona_filter or sort_by_score) else targets

    if dry_run:
        for t in final_targets:
            sc = score_by_persona(t, kws) if kws else 0
            print(f"DRY: would join {t} (score={sc})")
        return 0

    # Telethon client with API creds from config/env
    api_id = cfg.telegram.api_id
    api_hash = cfg.telegram.api_hash
    if not api_id or not api_hash:
        print("Missing TELEGRAM_API_ID/TELEGRAM_API_HASH in config/env", file=sys.stderr)
        return 2

    # Resolve Telethon session path robustly
    sess = session_name
    p = Path(sess)
    if not p.exists():
        if not str(sess).endswith('.session') and Path(sess + '.session').exists():
            sess = sess + '.session'
    client = TelegramClient(sess, api_id=api_id, api_hash=api_hash)
    await client.connect()
    try:
        me = await client.get_me()
        who = f"@{getattr(me, 'username', None) or me.id}"
        print(f"Using session: {who}")

        successes = already = errors_cnt = 0
        for idx, tgt in enumerate(final_targets, 1):
            ident, status = await join_one(client, tgt, throttle)
            sc = score_by_persona(ident, kws) if kws else 0
            print(f"[{idx}/{len(final_targets)}] {ident} (score={sc}) -> {status}")
            if status.startswith("joined"):
                successes += 1
            elif status == "already_member":
                already += 1
            else:
                errors_cnt += 1

        print(f"Done. joined={successes}, already={already}, errors={errors_cnt}")
        return 0 if errors_cnt == 0 else 1
    finally:
        await client.disconnect()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Join a list of Telegram chats with Telethon user session")
    ap.add_argument("--config", default="configs/config.yaml", help="Path to app config YAML")
    ap.add_argument("--session-name", default="sessions/userbot_session", help="Telethon session name or path")
    ap.add_argument("--links-file", default="scripts/targets.txt", help="Path to file with t.me links/usernames")
    ap.add_argument("--throttle", type=float, default=2.5, help="Seconds to wait between joins")
    ap.add_argument("--persona-filter", action="store_true", help="Join only targets matching Persona interests")
    ap.add_argument("--sort-by-score", action="store_true", help="Join in order of Persona relevance (high→low)")
    ap.add_argument("--dry-run", action="store_true", help="Only print actions, do not join")
    args = ap.parse_args()
    try:
        rc = asyncio.run(run_join(
            config=args.config,
            session_name=args.session_name,
            links_file=args.links_file,
            throttle=args.throttle,
            persona_filter=args.persona_filter,
            sort_by_score=args.sort_by_score,
            dry_run=args.dry_run,
        ))
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)
