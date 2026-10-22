"""内存滑动窗口限流（issue #114）：只防暴力，不是配额系统。单进程假设与 token 登记表一致。"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Mapping

DEFAULT_RULES: dict[str, tuple[int, float]] = {
    "register": (5, 3600.0),
    "login": (10, 60.0),
    "resend": (3, 3600.0),
    "verify": (10, 60.0),
}


class RateLimiter:
    def __init__(
        self,
        rules: Mapping[str, tuple[int, float]],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rules = dict(rules)
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = {}

    @classmethod
    def disabled(cls) -> RateLimiter:
        return cls({})

    def check(self, rule: str, key: str) -> bool:
        """允许则记一次并返回 True；未配置的 rule 一律放行。"""
        spec = self._rules.get(rule)
        if spec is None:
            return True
        limit, window = spec
        now = self._clock()
        q = self._hits.setdefault((rule, key), deque())
        while q and now - q[0] >= window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True
