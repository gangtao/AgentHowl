"""密码哈希（issue #114）：scrypt + 随机盐；校验失败不抛。"""

from app.runtime.users import hash_password, verify_password


def test_hash_roundtrip_and_salted() -> None:
    a = hash_password("correct horse")
    b = hash_password("correct horse")
    assert a != b  # 随机盐
    assert a.startswith("scrypt$16384$8$1$")
    assert verify_password("correct horse", a)
    assert verify_password("correct horse", b)
    assert not verify_password("wrong", a)


def test_verify_malformed_returns_false() -> None:
    assert not verify_password("x", "")
    assert not verify_password("x", "scrypt$bad")
    assert not verify_password("x", "scrypt$16384$8$1$!!!$!!!")
