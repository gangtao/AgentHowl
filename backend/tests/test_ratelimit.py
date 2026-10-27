"""内存滑动窗口限流（issue #114）。"""

from app.runtime.ratelimit import DEFAULT_RULES, RateLimiter


def test_window_and_keys() -> None:
    t = [0.0]
    rl = RateLimiter({"login": (2, 10.0)}, clock=lambda: t[0])
    assert rl.check("login", "1.1.1.1")
    assert rl.check("login", "1.1.1.1")
    assert not rl.check("login", "1.1.1.1")
    assert rl.check("login", "2.2.2.2")  # 不同 key 独立
    t[0] = 10.1
    assert rl.check("login", "1.1.1.1")  # 窗口滑过


def test_unknown_rule_allows_and_disabled() -> None:
    rl = RateLimiter({})
    assert rl.check("nope", "x")
    off = RateLimiter.disabled()
    assert all(off.check("login", "x") for _ in range(100))
    assert set(DEFAULT_RULES) == {"register", "login", "login_account", "resend", "verify"}
