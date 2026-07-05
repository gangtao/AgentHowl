from app.engine.rng import derive_int, shuffle


def test_derive_int_in_range() -> None:
    for seq in range(100):
        v = derive_int(seed=42, purpose="deal", seq=seq, modulo=12)
        assert 0 <= v < 12


def test_derive_int_is_deterministic() -> None:
    a = derive_int(seed=7, purpose="tie", seq=3, modulo=5)
    b = derive_int(seed=7, purpose="tie", seq=3, modulo=5)
    assert a == b


def test_derive_int_varies_by_inputs() -> None:
    base = derive_int(seed=1, purpose="deal", seq=0, modulo=1000)
    assert derive_int(seed=2, purpose="deal", seq=0, modulo=1000) != base
    assert derive_int(seed=1, purpose="x", seq=0, modulo=1000) != base
    assert derive_int(seed=1, purpose="deal", seq=1, modulo=1000) != base


def test_derive_int_rejects_bad_modulo() -> None:
    import pytest

    with pytest.raises(ValueError):
        derive_int(seed=1, purpose="p", seq=0, modulo=0)


def test_shuffle_is_permutation_and_pure() -> None:
    items = list(range(12))
    out = shuffle(seed=99, purpose="deal", items=items)
    assert sorted(out) == items          # 是一个排列
    assert items == list(range(12))      # 未改入参
    assert out != items                  # 对该 seed 确实打乱（12! 下几乎必然）


def test_shuffle_is_deterministic() -> None:
    a = shuffle(seed=5, purpose="deal", items=list(range(9)))
    b = shuffle(seed=5, purpose="deal", items=list(range(9)))
    assert a == b
