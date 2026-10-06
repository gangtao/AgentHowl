"""AvatarStore（issue #102）：魔数识别、内容寻址、幂等、非法 id 拒绝。"""

from pathlib import Path

import pytest

from app.runtime.avatar_store import (
    AvatarStore,
    FileAvatarStore,
    InMemoryAvatarStore,
    UnsupportedImageError,
    sniff_image,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32


def test_sniff_image() -> None:
    assert sniff_image(PNG) == "png"
    assert sniff_image(JPG) == "jpg"
    assert sniff_image(WEBP) == "webp"
    assert sniff_image(b"GIF89a" + b"\x00" * 32) is None
    assert sniff_image(b"hello world") is None
    assert sniff_image(b"") is None


@pytest.fixture(params=["memory", "file"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> AvatarStore:
    if request.param == "memory":
        return InMemoryAvatarStore()
    return FileAvatarStore(tmp_path / "avatars")


def test_put_is_content_addressed_and_idempotent(store: AvatarStore) -> None:
    a = store.put(PNG)
    assert len(a) == 20 and a.endswith(".png") and a[:16] == a[:16].lower()
    assert store.put(PNG) == a  # 同内容同 id
    assert store.put(JPG) != a
    assert store.path_for(a) is not None
    assert store.path_for(a).read_bytes() == PNG  # type: ignore[union-attr]


def test_put_rejects_unknown_type(store: AvatarStore) -> None:
    with pytest.raises(UnsupportedImageError):
        store.put(b"not an image")


def test_path_for_missing_and_illegal(store: AvatarStore) -> None:
    assert store.path_for("0000000000000000.png") is None
    for bad in ("../x.png", "x.png", "0000000000000000.gif"):
        with pytest.raises(ValueError):
            store.path_for(bad)


def test_file_store_does_not_rewrite_existing(tmp_path: Path) -> None:
    store = FileAvatarStore(tmp_path / "avatars")
    a = store.put(PNG)
    p = tmp_path / "avatars" / a
    before = p.stat().st_mtime_ns
    assert store.put(PNG) == a
    assert p.stat().st_mtime_ns == before
    assert not list((tmp_path / "avatars").glob("*.tmp"))
