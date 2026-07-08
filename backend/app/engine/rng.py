"""确定性随机派生。

引擎不持有随机对象；每次抽取都是 (seed, purpose, seq) 的纯函数（哈希派生）。
引擎抽取以 GameState.state_version 为 seq（每事件 +1，事件推导），因此重放天然复现。
"""

from __future__ import annotations

import hashlib
from typing import TypeVar

T = TypeVar("T")


def derive_int(seed: int, purpose: str, seq: int, modulo: int) -> int:
    """由 (seed, purpose, seq) 派生一个 [0, modulo) 的确定性整数。"""
    if modulo <= 0:
        raise ValueError(f"modulo 必须为正数，收到 {modulo}")
    raw = f"{seed}:{purpose}:{seq}".encode()
    digest = hashlib.sha256(raw).digest()
    value = int.from_bytes(digest[:8], "big")
    return value % modulo


def shuffle(seed: int, purpose: str, items: list[T]) -> list[T]:
    """确定性 Fisher-Yates 洗牌，返回新列表，不修改入参。"""
    result = list(items)
    n = len(result)
    for i in range(n - 1, 0, -1):
        j = derive_int(seed=seed, purpose=purpose, seq=n - 1 - i, modulo=i + 1)
        result[i], result[j] = result[j], result[i]
    return result
