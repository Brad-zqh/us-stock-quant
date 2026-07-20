"""登录门与会话 (auth.py)
========================
在 Streamlit 里做一个轻量登录门:

  - 未启用多用户 (本地开发/未配置) → 直接放行, 保持原单用户模式, 不打扰。
  - 启用多用户 (配置了 Supabase 或 REQUIRE_LOGIN) → 未登录则渲染登录/注册界面并 st.stop()。
  - 登录成功后把签名凭证保存在浏览器 localStorage，刷新、关闭网页或重启 App 均可自动登录。

凭证不保存明文密码且没有固定到期日；主动退出、修改密码或删除账户后失效。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import streamlit as st

import userstore

try:
    from streamlit_local_storage import LocalStorage
    _HAS_LS = True
except Exception:
    _HAS_LS = False


_AUTH_KEY = "hg_auth_token_v1"
_AUTH_SET_KEY = "hg_auth_set"
_AUTH_DEL_KEY = "hg_auth_del"
_AUTH_MOUNT_KEY = "hg_auth_mount"
_AUTH_TOKEN_VERSION = 2


def _store():
    if not _HAS_LS:
        return None
    if "_hg_auth_ls" not in st.session_state:
        try:
            st.session_state["_hg_auth_ls"] = LocalStorage(key=_AUTH_MOUNT_KEY)
        except Exception:
            st.session_state["_hg_auth_ls"] = None
    return st.session_state["_hg_auth_ls"]


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64u_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + pad).encode())


def _secret_for_record(rec: dict) -> str:
    return f"{rec.get('pw_hash', '')}::{rec.get('salt', '')}"


def _make_token(email: str) -> str | None:
    rec = userstore.get_record(email)
    if not rec:
        return None
    payload = {
        "email": email.strip().lower(),
        # v2 intentionally has no fixed expiry. Changing the password changes
        # the signing secret, so an existing token is still revoked immediately.
        "v": _AUTH_TOKEN_VERSION,
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(_secret_for_record(rec).encode("utf-8"), body, hashlib.sha256).digest()
    return f"{_b64u(body)}.{_b64u(sig)}"


def _parse_token(token: str) -> str | None:
    try:
        body64, sig64 = str(token or "").split(".", 1)
        body = _b64u_decode(body64)
        payload = json.loads(body.decode("utf-8"))
        email = str(payload.get("email", "")).strip().lower()
    except Exception:
        return None
    if not email:
        return None
    # Keep accepting the previously deployed 30-day token long enough to
    # migrate it. New v2 tokens deliberately omit "exp".
    if "exp" in payload:
        try:
            if int(payload["exp"]) <= int(time.time()):
                return None
        except (TypeError, ValueError):
            return None
    rec = userstore.get_record(email)
    if not rec:
        return None
    want = hmac.new(_secret_for_record(rec).encode("utf-8"), body, hashlib.sha256).digest()
    try:
        got = _b64u_decode(sig64)
    except Exception:
        return None
    if not hmac.compare_digest(got, want):
        return None
    return email


def _save_token(email: str) -> None:
    store = _store()
    token = _make_token(email)
    if store is None or not token:
        return
    try:
        store.setItem(_AUTH_KEY, token, key=_AUTH_SET_KEY)
    except Exception:
        pass


def _delete_token() -> None:
    store = _store()
    if store is None:
        return
    try:
        store.deleteItem(_AUTH_KEY, key=_AUTH_DEL_KEY)
    except Exception:
        pass


def _restore_login() -> str | None:
    store = _store()
    if store is None:
        return None
    try:
        token = store.getItem(_AUTH_KEY)
    except Exception:
        return None
    email = _parse_token(token)
    if email:
        st.session_state["auth_email"] = email
        st.session_state["auth_ok"] = True
        # Transparently replace an old 30-day token with the permanent v2 one.
        _save_token(email)
        return email
    if token:
        _delete_token()
    return None


def auth_enabled() -> bool:
    if userstore.using_supabase():
        return True
    return userstore._get_secret("REQUIRE_LOGIN", "").strip().lower() in ("1", "true", "yes", "on")


def current_user() -> str | None:
    return st.session_state.get("auth_email")


def is_admin() -> bool:
    email = current_user()
    return bool(email and userstore.is_admin(email))


def logout() -> None:
    for key in ("auth_email", "auth_ok"):
        st.session_state.pop(key, None)
    _delete_token()
    # app.py 会立即 st.rerun；在下一轮再渲染一次删除组件，确保浏览器已真正清除。
    st.session_state["_auth_pending_delete"] = True


def _render_login_form() -> None:
    st.markdown("## 📈 皓量化 · 登录")
    st.caption("多因子量化分析 · 美股 / A股。请登录后使用；新用户凭邀请码注册。")

    tab_login, tab_reg = st.tabs(["🔑 登录", "🆕 注册"])

    with tab_login:
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input("邮箱", key="li_email", placeholder="you@example.com")
            pw = st.text_input("密码", type="password", key="li_pw")
            st.caption("在本设备登录一次后会自动保持登录；请在公用设备上使用“退出”。")
            ok = st.form_submit_button("登录", type="primary", use_container_width=True)
        if ok:
            good, msg = userstore.verify_login(email, pw)
            if good:
                email = email.strip().lower()
                st.session_state["auth_email"] = email
                st.session_state["auth_ok"] = True
                # 下一轮完整渲染时再写入，避免紧接着的 st.rerun 抢在浏览器落盘之前。
                st.session_state["_auth_pending_save"] = email
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    with tab_reg:
        codes = userstore.valid_invite_codes()
        if not codes and not userstore.using_supabase():
            st.info("当前未配置邀请码，管理员邮箱可直接注册。")
        with st.form("reg_form", clear_on_submit=False):
            r_email = st.text_input("邮箱", key="rg_email", placeholder="you@example.com")
            r_pw = st.text_input("设置密码 (≥6位)", type="password", key="rg_pw")
            r_pw2 = st.text_input("确认密码", type="password", key="rg_pw2")
            r_code = st.text_input("邀请码", key="rg_code", help="向管理员索取；管理员邮箱可留空。")
            ok2 = st.form_submit_button("注册", use_container_width=True)
        if ok2:
            if r_pw != r_pw2:
                st.error("两次密码不一致。")
            else:
                good, msg = userstore.create_user(r_email, r_pw, r_code)
                (st.success if good else st.error)(msg)
                if good:
                    st.info("现在切到「🔑 登录」标签登录即可。")


def login_gate() -> str | None:
    """返回当前登录邮箱；启用登录且未登录时渲染登录页并停止其余页面。"""
    if not auth_enabled():
        return None

    if st.session_state.pop("_auth_pending_delete", False):
        _delete_token()

    email = st.session_state.get("auth_email")
    if email:
        pending_email = st.session_state.pop("_auth_pending_save", None)
        if pending_email == email:
            _save_token(email)
        return email

    restored = _restore_login()
    if restored:
        return restored

    _left, center, _right = st.columns([1, 1.4, 1])
    with center:
        _render_login_form()
    st.stop()
