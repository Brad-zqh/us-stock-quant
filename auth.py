"""登录门与会话 (auth.py)
========================
在 Streamlit 里做一个轻量登录门:

  - 未启用多用户 (本地开发/未配置) → 直接放行, 保持原单用户模式, 不打扰。
  - 启用多用户 (配置了 Supabase 或 REQUIRE_LOGIN) → 未登录则渲染登录/注册界面并 st.stop()。

启用条件 (满足其一即要求登录):
  - 配置了 Supabase (SUPABASE_URL + SUPABASE_KEY)
  - Secrets/环境变量 REQUIRE_LOGIN = 1 / true / yes / on

会话保存在 st.session_state (硬刷新需重新登录, 对小规模够用)。
"""
from __future__ import annotations

import streamlit as st

import userstore


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
    for k in ("auth_email", "auth_ok"):
        st.session_state.pop(k, None)


def _render_login_form() -> None:
    st.markdown("## 📈 皓量化 · 登录")
    st.caption("多因子量化分析 · 美股 / A股。请登录后使用；新用户凭邀请码注册。")

    tab_login, tab_reg = st.tabs(["🔑 登录", "🆕 注册"])

    with tab_login:
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input("邮箱", key="li_email", placeholder="you@example.com")
            pw = st.text_input("密码", type="password", key="li_pw")
            ok = st.form_submit_button("登录", type="primary", use_container_width=True)
        if ok:
            good, msg = userstore.verify_login(email, pw)
            if good:
                st.session_state["auth_email"] = email.strip().lower()
                st.session_state["auth_ok"] = True
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    with tab_reg:
        _codes = userstore.valid_invite_codes()
        if not _codes and not userstore.using_supabase():
            st.info("当前未配置邀请码, 管理员邮箱可直接注册。")
        with st.form("reg_form", clear_on_submit=False):
            r_email = st.text_input("邮箱", key="rg_email", placeholder="you@example.com")
            r_pw = st.text_input("设置密码 (≥6位)", type="password", key="rg_pw")
            r_pw2 = st.text_input("确认密码", type="password", key="rg_pw2")
            r_code = st.text_input("邀请码", key="rg_code",
                                   help="向管理员索取；管理员邮箱可留空。")
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
    """返回当前登录邮箱; 若启用登录且未登录则渲染登录界面并停止渲染其余页面。
    未启用多用户时返回 None (单用户模式)。"""
    if not auth_enabled():
        return None
    if st.session_state.get("auth_email"):
        return st.session_state["auth_email"]

    # 居中登录卡片
    _l, _c, _r = st.columns([1, 1.4, 1])
    with _c:
        _render_login_form()
    st.stop()
