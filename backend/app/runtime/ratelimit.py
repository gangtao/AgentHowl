"""内存滑动窗口限流（issue #114）：只防暴力，不是配额系统。单进程假设与 token 登记表一致。"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Mapping

DEFAULT_RULES: dict[str, tuple[int, float]] = {
    "register": (5, 3600.0),
    "login": (10, 60.0),
    "login_account": (10, 60.0),  # issue #120：按账号（用户名 / 邮箱）限流，分布式撞库也受限
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
        self._evict_stale(now)
        return True

    def _evict_stale(self, now: float) -> None:
        """issue #120：窗口已空的键淘汰掉，_hits 不随历史上出现过的 IP / 账号无限增长。"""
        if len(self._hits) < 256:
            return
        for k in [k for k, q in self._hits.items() if not q or now - q[-1] >= self._rules[k[0]][1]]:
            del self._hits[k]
