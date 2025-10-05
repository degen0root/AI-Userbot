from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .config import PolicySection, TelegramSection


@dataclass
class Decision:
    should_reply: bool
    include_promotion: bool = False
    disclosure_text: Optional[str] = None
    reason: str = ""


class ParticipationPolicy:
    def __init__(self, policy: PolicySection, tg: TelegramSection):
        self._p = policy
        self._tg = tg
        self._last_reply_ts: Dict[int, float] = {}
        self._reply_times: Dict[int, List[float]] = {}

    def is_allowed_chat(self, chat_id: int) -> bool:
        # Safe default: respond only to explicitly allowed chats
        return chat_id in set(self._tg.allowed_chat_ids)

    def _within_rate_limits(self, chat_id: int, now: float) -> bool:
        last = self._last_reply_ts.get(chat_id, 0.0)
        if now - last < self._p.min_gap_seconds_per_chat:
            return False
        # hourly cap
        window_start = now - 3600
        times = self._reply_times.get(chat_id, [])
        times = [t for t in times if t >= window_start]
        self._reply_times[chat_id] = times
        return len(times) < self._p.max_replies_per_hour_per_chat

    def _record_reply(self, chat_id: int, now: float) -> None:
        self._last_reply_ts[chat_id] = now
        self._reply_times.setdefault(chat_id, []).append(now)

    def _relevance(self, text: str) -> float:
        # Very simple heuristic placeholder
        t = text.lower()
        keywords = ["кто", "что", "как", "почему", "зачем", "когда", "где", "совет", "помогите"]
        score = 0.0
        if any(k in t for k in keywords):
            score += 0.4
        if "?" in t:
            score += 0.3
        if 10 < len(t) < 500:
            score += 0.2
        return min(score, 1.0)

    def _contains_forbidden(self, text: str) -> bool:
        t = text.lower()
        return any(term.lower() in t for term in self._p.forbidden_terms)

    def decide(self, chat_id: int, text: str, now: Optional[float] = None) -> Decision:
        now = now or time.time()
        if not self.is_allowed_chat(chat_id):
            return Decision(False, reason="chat_not_allowed")
        if self._contains_forbidden(text):
            return Decision(False, reason="forbidden_terms")
        if not self._within_rate_limits(chat_id, now):
            return Decision(False, reason="rate_limited")

        relevance = self._relevance(text)
        if relevance < self._p.relevance_threshold:
            return Decision(False, reason="low_relevance")

        include_promo = random.random() < self._p.promotion_probability
        disclosure = self._p.disclosure_text if self._p.disclose_identity else None

        # Record rate state only if we actually reply
        self._record_reply(chat_id, now)
        return Decision(True, include_promo, disclosure, reason="ok")

