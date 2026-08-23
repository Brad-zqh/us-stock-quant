"""Small, dependency-free UI language helper for the Streamlit app."""

from __future__ import annotations

import streamlit as st


ZH = "zh"
EN = "en"
_STATE_KEY = "_ui_language"


def init_language() -> str:
    """Initialize the session language from ``?lang=``; Chinese is the default."""
    if _STATE_KEY not in st.session_state:
        try:
            requested = str(st.query_params.get("lang", "")).lower()
        except Exception:
            requested = ""
        st.session_state[_STATE_KEY] = EN if requested == EN else ZH
    return st.session_state[_STATE_KEY]


def language() -> str:
    return init_language()


def is_english() -> bool:
    return language() == EN


def t(zh: str, en: str) -> str:
    """Return one language only, never a Chinese/English mixed label."""
    return en if is_english() else zh


def set_language(value: str) -> None:
    value = EN if value == EN else ZH
    st.session_state[_STATE_KEY] = value
    # These widgets use localized option values. Clearing them avoids carrying a
    # Chinese option into an English-only rerun (or the reverse).
    for key in ("fav_mkt", "pf_w", "ai_market", "fund_mkt"):
        st.session_state.pop(key, None)
    # Generated commentary is language-specific and must be regenerated.
    for key in list(st.session_state):
        if str(key).startswith(("newsdigest_", "aireview_")):
            st.session_state.pop(key, None)
    try:
        st.query_params["lang"] = value
    except Exception:
        pass


def render_language_switcher() -> None:
    """Render a compact two-button language switch at the top of the sidebar."""
    current = language()
    st.sidebar.caption("🌐 " + t("界面语言", "Interface language"))
    zh_col, en_col = st.sidebar.columns(2)
    if zh_col.button(
        "中文",
        key="ui_language_zh",
        type="primary" if current == ZH else "secondary",
        use_container_width=True,
    ):
        if current != ZH:
            set_language(ZH)
            st.rerun()
    if en_col.button(
        "English",
        key="ui_language_en",
        type="primary" if current == EN else "secondary",
        use_container_width=True,
    ):
        if current != EN:
            set_language(EN)
            st.rerun()
    st.sidebar.divider()
