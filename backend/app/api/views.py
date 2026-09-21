"""视角相关的序列化过滤：非 GM 视角下的事件 JSON 不外泄敏感 meta 字段（issue #60）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.engine.events import Event

PUBLIC_META_KEYS: frozenset[str] = frozenset({"wall_ts", "timeout"})


def event_json_for_viewer(event: Event, viewer: Any) -> dict[str, Any]:
    """非 GM 视角的事件 JSON：meta 只保留公开键（skills 等 runtime 标注只给 GM / 离线分析）。"""
    from app.store.event_store import event_to_json

    d = event_to_json(event)
    if viewer != "GM":
        d["meta"] = {k: v for k, v in event.meta.items() if k in PUBLIC_META_KEYS}
    return d
