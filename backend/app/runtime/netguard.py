"""Provider api_base 的内网地址守卫（issue #120）：BYOK 固有的 SSRF 入口，公网多租户部署可
通过 AGENTHOWL_BLOCK_PRIVATE_API_BASE=1 拒绝指向本机 / 内网 / 链路本地 / 云元数据地址的 api_base。
默认关闭——本地 Ollama 就在 127.0.0.1。"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit

_ENV = "AGENTHOWL_BLOCK_PRIVATE_API_BASE"


def private_api_base_blocking_enabled() -> bool:
    return os.environ.get(_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _bad_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def private_api_base_reason(url: str | None) -> str | None:
    """api_base 指向不该从服务端访问的地址时给出原因，否则 None。纯函数 + 只读 DNS。"""
    if not url:
        return None
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return "无法解析的 URL"
    if not host:
        return "缺少主机名"
    lowered = host.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith(".localhost"):
        return "本机地址"
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        ip = None
    if ip is not None:
        return "内网 / 本机 / 保留地址" if _bad_ip(ip) else None
    try:
        infos = socket.getaddrinfo(lowered, None)
    except OSError:
        return None  # 解析不了交给后续真实调用去报错
    for info in infos:
        try:
            if _bad_ip(ipaddress.ip_address(info[4][0])):
                return f"域名解析到内网 / 本机地址（{info[4][0]}）"
        except ValueError:
            continue
    return None
