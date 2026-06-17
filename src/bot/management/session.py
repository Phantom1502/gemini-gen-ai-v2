"""
bot/management/session.py
=========================
SessionFilter — kiểm tra phiên giao dịch được phép.
"""

import datetime
from typing import Optional, List, Dict, Tuple

import config


class SessionFilter:

    @staticmethod
    def is_allowed(now: Optional[datetime.datetime] = None) -> Tuple[bool, str]:
        """Trả về (allowed, reason)."""
        if now is None:
            now = datetime.datetime.now()

        weekday = now.weekday()
        if weekday not in config.ALLOWED_WEEKDAYS:
            return False, f"Ngoài ngày giao dịch (weekday={weekday})"

        if weekday == 4:
            fc = datetime.datetime.strptime(config.FORCE_CLOSE_FRIDAY_TIME, "%H:%M").time()
            if now.time() >= fc:
                return False, f"Thứ 6 sau {config.FORCE_CLOSE_FRIDAY_TIME}"

        now_time = now.time()
        for s in config.ALLOWED_SESSIONS:
            start = datetime.datetime.strptime(s["start"], "%H:%M").time()
            end   = datetime.datetime.strptime(s["end"],   "%H:%M").time()
            if start <= now_time <= end:
                return True, f"{s['name']} ({s['start']}–{s['end']})"

        return False, f"Ngoài phiên ({now.strftime('%H:%M')})"

    @staticmethod
    def should_force_close(now: Optional[datetime.datetime] = None) -> bool:
        if now is None:
            now = datetime.datetime.now()
        if now.weekday() != 4:
            return False
        fc = datetime.datetime.strptime(config.FORCE_CLOSE_FRIDAY_TIME, "%H:%M").time()
        return now.time() >= fc
