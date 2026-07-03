"""收藏夹持久化 (favorites.py)
================================
把用户的自选股保存在 **本机浏览器 localStorage**, 无需登录, 每台设备
(桌面 App / 手机 App / 浏览器) 各自记住一份, 下次打开自动还原。

- load()  -> 读取本机保存的自选股文本 (无则 None)
- save(t) -> 写入本机 localStorage
- available() -> 组件是否可用

若 streamlit-local-storage 组件不可用 (老环境/未安装), 全部安全降级为
"本会话有效" —— 不报错, 只是关掉浏览器后不记住。已登录用户仍可用账户同步。
"""
from __future__ import annotations

import streamlit as st

try:
    from streamlit_local_storage import LocalStorage
    _HAS_LS = True
except Exception:  # 组件缺失时安全降级
    _HAS_LS = False

FAV_KEY = "hg_favorites_v1"      # localStorage 里的键名
_SET_KEY = "hg_ls_set"           # setItem 组件的 streamlit key (每次运行至多用一次)
_DEL_KEY = "hg_ls_del"
_MOUNT_KEY = "hg_ls_mount"


def available() -> bool:
    return _HAS_LS


def _store():
    """惰性构造 LocalStorage (每会话一次, 缓存到 session_state)。"""
    if not _HAS_LS:
        return None
    if "_hg_ls_obj" not in st.session_state:
        try:
            st.session_state["_hg_ls_obj"] = LocalStorage(key=_MOUNT_KEY)
        except Exception:
            st.session_state["_hg_ls_obj"] = None
    return st.session_state["_hg_ls_obj"]


def load() -> str | None:
    """返回本机保存的自选股文本, 无/失败则 None。"""
    s = _store()
    if s is None:
        return None
    try:
        v = s.getItem(FAV_KEY)
        return v if (v and str(v).strip()) else None
    except Exception:
        return None


def save(text: str) -> None:
    """把自选股文本写入本机 localStorage。空文本则删除。
    注意: 每次脚本运行至多调用一次 (固定 streamlit key), 由调用方保证。"""
    s = _store()
    if s is None:
        return
    try:
        t = (text or "").strip()
        if t:
            s.setItem(FAV_KEY, t, key=_SET_KEY)
        else:
            try:
                s.deleteItem(FAV_KEY, key=_DEL_KEY)
            except Exception:
                pass
    except Exception:
        pass
