# -*- coding: utf-8 -*-
"""
离线资源管理：把 Bootstrap / Plotly.js 从 CDN 下载到本地，供报告内联，
实现"完全离线"（生成的 HTML 不再依赖任何外部网络即可打开）。

用法（需联网，仅首次）：
    python -m astock_watch.assets           # 下载资源到 astock_watch/assets/
之后生成报告时加 --offline，即把资源内联进 HTML。

设计：下载失败/未下载时，报告自动回退 CDN，绝不报错。
"""
from __future__ import annotations

import os

from . import config as C
from .utils import logger

# 资源键 -> (CDN url, 本地文件名)
ASSETS = {
    "plotly_js": (C.CDN["plotly_js"], "plotly.min.js"),
    "bootstrap_css": (C.CDN["bootstrap_css"], "bootstrap.min.css"),
}
DEFAULT_DIR = os.path.join(os.path.dirname(__file__), "assets")

_CACHE = {}


def download(dest: str = DEFAULT_DIR) -> int:
    """下载全部资源到 dest，返回成功数。需联网。"""
    import requests
    os.makedirs(dest, exist_ok=True)
    ok = 0
    # 优先从已安装的 plotly 包直接复制 plotly.min.js（若用户装了 plotly）
    _try_copy_plotly_from_package(dest)
    for key, (url, fn) in ASSETS.items():
        path = os.path.join(dest, fn)
        if key == "plotly_js" and os.path.exists(path) and os.path.getsize(path) > 100_000:
            ok += 1
            continue
        try:
            r = requests.get(url, timeout=90, headers={"User-Agent": C.USER_AGENT})
            r.raise_for_status()
            with open(path, "w", encoding="utf-8") as f:
                f.write(r.text)
            print(f"  ✓ {fn}  ({len(r.text) // 1024} KB)")
            ok += 1
        except Exception as e:                       # noqa: BLE001
            print(f"  ✗ {fn}: {e}")
    print(f"完成：{ok}/{len(ASSETS)} 个资源就绪于 {dest}")
    return ok


def _try_copy_plotly_from_package(dest: str) -> None:
    """若本机已装 plotly 包，直接复制其内置 plotly.min.js，免去下载。"""
    try:
        import plotly
        for sub in ("package_data/plotly.min.js", "offline/plotly.min.js"):
            src = os.path.join(os.path.dirname(plotly.__file__), *sub.split("/"))
            if os.path.exists(src):
                with open(src, encoding="utf-8") as fr, \
                     open(os.path.join(dest, "plotly.min.js"), "w", encoding="utf-8") as fw:
                    fw.write(fr.read())
                print("  ✓ plotly.min.js（来自本机 plotly 包）")
                return
    except Exception:
        pass


def load_inline(dest: str = DEFAULT_DIR) -> dict:
    """读取本地资源内容，返回 {key: 内容或 None}。带缓存避免重复读大文件。"""
    if dest in _CACHE:
        return _CACHE[dest]
    out = {}
    for key, (_url, fn) in ASSETS.items():
        path = os.path.join(dest, fn)
        try:
            out[key] = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        except Exception:                            # noqa: BLE001
            out[key] = None
    _CACHE[dest] = out
    return out


def available(dest: str = DEFAULT_DIR) -> bool:
    """是否所有离线资源都已就绪。"""
    return all(os.path.exists(os.path.join(dest, fn)) for _key, (_u, fn) in ASSETS.items())


if __name__ == "__main__":
    print("正在下载离线资源（Bootstrap / Plotly.js）...")
    download()
