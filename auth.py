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
import secrets
import time

import streamlit as st

import userstore
import ui_i18n

T = ui_i18n.t

try:
    from streamlit_local_storage import LocalStorage
    _HAS_LS = True
except Exception:
    _HAS_LS = False


_AUTH_KEY = "hg_auth_token_v1"
_AUTH_SET_KEY = "hg_auth_set"
_AUTH_DEL_KEY = "hg_auth_del"
_AUTH_MOUNT_KEY = "hg_auth_mount"
_AUTH_TOKEN_VERSION = 3
_RECOVERY_TOKEN_VERSION = 4
_RECOVERY_CODE_TTL = 10 * 60
_RECOVERY_SEND_COOLDOWN = 60


class _AuthBackendUnavailable(RuntimeError):
    """旧版凭证暂时无法向账户后端完成校验。"""


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


def _app_token_secret() -> str:
    """返回可跨后端故障验证凭证的稳定密钥。

    AUTH_TOKEN_SECRET 最佳；为兼容现有部署，缺省复用仅在服务端使用的
    Supabase key。切换 Supabase 项目前应先配置独立 AUTH_TOKEN_SECRET。
    """
    return (
        userstore._get_secret("AUTH_TOKEN_SECRET", "").strip()
        or userstore._get_secret("SUPABASE_SERVICE_KEY", "").strip()
        or userstore._get_secret("SUPABASE_KEY", "").strip()
    )


def _revocation_tag(rec: dict, secret: str) -> str:
    """生成不泄露密码哈希的短标签；后端在线时用于使改密立即失效。"""
    return hmac.new(
        secret.encode("utf-8"),
        _secret_for_record(rec).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:24]


def _recovery_email_config() -> dict:
    """读取邮件恢复配置；优先 Streamlit Secrets，再回退本地 config.json。"""
    try:
        section = st.secrets.get("email", {})
        cfg = dict(section) if section else {}
    except Exception:
        cfg = {}
    if not cfg:
        try:
            import notify
            cfg = dict(notify.load_config().get("email", {}) or {})
        except Exception:
            cfg = {}
    aliases = {
        "smtp": ("EMAIL_SMTP", "SMTP_HOST"),
        "port": ("EMAIL_PORT", "SMTP_PORT"),
        "user": ("EMAIL_USER", "SMTP_USER"),
        "password": ("EMAIL_PASSWORD", "SMTP_PASSWORD"),
        "to": ("EMAIL_TO", "AUTH_RECOVERY_EMAILS"),
    }
    for field, names in aliases.items():
        if cfg.get(field):
            continue
        for name in names:
            value = userstore._get_secret(name, "").strip()
            if value:
                cfg[field] = value
                break
    return cfg


def _recovery_admin_emails() -> set[str]:
    """仅允许显式管理员或邮件配置所有者使用恢复登录。"""
    emails = set(userstore.admin_emails())
    raw = userstore._get_secret("AUTH_RECOVERY_EMAILS", "")
    emails.update(e.strip().lower() for e in raw.split(",") if e.strip())
    cfg = _recovery_email_config()
    for key in ("to", "user"):
        value = str(cfg.get(key, "")).strip().lower()
        if value and "@" in value:
            emails.add(value)
    return emails


def _make_recovery_token(email: str) -> str | None:
    secret = _app_token_secret()
    email = (email or "").strip().lower()
    if not secret or email not in _recovery_admin_emails():
        return None
    payload = {
        "email": email,
        "v": _RECOVERY_TOKEN_VERSION,
        "mode": "email_recovery",
        "iat": int(time.time()),
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return f"{_b64u(body)}.{_b64u(sig)}"


def _recovery_code_digest(email: str, code: str) -> str:
    secret = _app_token_secret()
    return hmac.new(
        secret.encode("utf-8"),
        f"{email.strip().lower()}:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _send_recovery_code(email: str) -> tuple[bool, str]:
    email = (email or "").strip().lower()
    if email not in _recovery_admin_emails():
        return False, "该邮箱未配置为管理员恢复邮箱。"
    if not _app_token_secret():
        return False, "未配置登录签名密钥，暂时无法发送验证码。"
    now = int(time.time())
    last_sent = int(st.session_state.get("_auth_recovery_last_sent", 0) or 0)
    if now - last_sent < _RECOVERY_SEND_COOLDOWN:
        return False, f"请在 {_RECOVERY_SEND_COOLDOWN - (now - last_sent)} 秒后重新发送。"
    cfg = _recovery_email_config()
    if not all(cfg.get(key) for key in ("smtp", "user", "password")):
        return False, "管理员恢复邮件尚未配置。"

    code = f"{secrets.randbelow(1_000_000):06d}"
    send_cfg = dict(cfg)
    send_cfg["to"] = email
    send_cfg["cc"] = ""
    try:
        import notify
        result = notify.send_email(
            "皓量化登录验证码",
            f"你的皓量化登录验证码是：{code}\n\n验证码 10 分钟内有效。如非本人操作，请忽略。",
            cfg=send_cfg,
        )
    except Exception as exc:
        return False, f"验证码发送失败：{exc}"
    if not str(result).startswith("✅"):
        return False, str(result)

    st.session_state["_auth_recovery_email"] = email
    st.session_state["_auth_recovery_digest"] = _recovery_code_digest(email, code)
    st.session_state["_auth_recovery_expires"] = now + _RECOVERY_CODE_TTL
    st.session_state["_auth_recovery_attempts"] = 0
    st.session_state["_auth_recovery_last_sent"] = now
    return True, "验证码已发送到管理员邮箱，10 分钟内有效。"


def _verify_recovery_code(email: str, code: str) -> tuple[bool, str]:
    email = (email or "").strip().lower()
    code = (code or "").strip()
    target = st.session_state.get("_auth_recovery_email", "")
    expires = int(st.session_state.get("_auth_recovery_expires", 0) or 0)
    attempts = int(st.session_state.get("_auth_recovery_attempts", 0) or 0)
    if email != target or email not in _recovery_admin_emails():
        return False, "请先向该管理员邮箱发送验证码。"
    if int(time.time()) > expires:
        return False, "验证码已过期，请重新发送。"
    if attempts >= 5:
        return False, "验证码尝试次数过多，请重新发送。"
    st.session_state["_auth_recovery_attempts"] = attempts + 1
    expected = str(st.session_state.get("_auth_recovery_digest", ""))
    if not code or not hmac.compare_digest(_recovery_code_digest(email, code), expected):
        return False, "验证码错误。"
    token = _make_recovery_token(email)
    if not token:
        return False, "无法生成登录凭证，请检查恢复配置。"

    st.session_state["auth_email"] = email
    st.session_state["auth_ok"] = True
    st.session_state["_auth_recovery_admin"] = True
    st.session_state["_auth_pending_token"] = token
    for key in (
        "_auth_recovery_email", "_auth_recovery_digest",
        "_auth_recovery_expires", "_auth_recovery_attempts",
    ):
        st.session_state.pop(key, None)
    return True, "验证成功，正在登录。"


def _make_token(email: str) -> str | None:
    rec = userstore.get_record(email)
    secret = _app_token_secret()
    if not rec or not secret:
        return None
    payload = {
        "email": email.strip().lower(),
        "v": _AUTH_TOKEN_VERSION,
        "rv": _revocation_tag(rec, secret),
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return f"{_b64u(body)}.{_b64u(sig)}"


def _parse_token(token: str) -> str | None:
    try:
        body64, sig64 = str(token or "").split(".", 1)
        body = _b64u_decode(body64)
        payload = json.loads(body.decode("utf-8"))
        email = str(payload.get("email", "")).strip().lower()
        version = int(payload.get("v", 1))
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
    try:
        got = _b64u_decode(sig64)
    except Exception:
        return None

    if version >= 3:
        secret = _app_token_secret()
        if not secret:
            return None
        want = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        if not hmac.compare_digest(got, want):
            return None
        if version >= _RECOVERY_TOKEN_VERSION and payload.get("mode") == "email_recovery":
            return email if email in _recovery_admin_emails() else None
        try:
            rec = userstore.get_record(email, strict=True)
        except userstore.AccountBackendError:
            # 凭证签名已通过：数据库短暂掉线时允许已登录设备继续使用。
            return email
        if not rec:
            return None
        if not hmac.compare_digest(
            str(payload.get("rv", "")), _revocation_tag(rec, secret)
        ):
            return None
        return email

    # 兼容 v1/v2：旧凭证以用户密码哈希签名，必须访问账户后端验证。
    try:
        rec = userstore.get_record(email, strict=True)
    except userstore.AccountBackendError as exc:
        raise _AuthBackendUnavailable from exc
    if not rec:
        return None
    want = hmac.new(_secret_for_record(rec).encode("utf-8"), body, hashlib.sha256).digest()
    if not hmac.compare_digest(got, want):
        return None
    return email


def _save_token_value(token: str | None) -> None:
    store = _store()
    if store is None or not token:
        return
    try:
        store.setItem(_AUTH_KEY, token, key=_AUTH_SET_KEY)
    except Exception:
        pass


def _save_token(email: str) -> None:
    _save_token_value(_make_token(email))


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
    try:
        email = _parse_token(token)
    except _AuthBackendUnavailable:
        # 保留旧凭证，等账户服务恢复后再迁移，不能把短暂断线当作登出。
        return None
    if email:
        st.session_state["auth_email"] = email
        st.session_state["auth_ok"] = True
        if email in _recovery_admin_emails():
            st.session_state["_auth_recovery_admin"] = True
        # 有账户记录时透明升级旧凭证；恢复凭证在数据库离线时保持原样。
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
    return bool(
        email
        and (
            st.session_state.get("_auth_recovery_admin")
            or email in _recovery_admin_emails()
            or userstore.is_admin(email)
        )
    )


def logout() -> None:
    for key in ("auth_email", "auth_ok", "_auth_recovery_admin", "_auth_pending_token"):
        st.session_state.pop(key, None)
    _delete_token()
    # app.py 会立即 st.rerun；在下一轮再渲染一次删除组件，确保浏览器已真正清除。
    st.session_state["_auth_pending_delete"] = True


def _render_login_form() -> None:
    st.markdown(T("## 📈 皓量化", "## 📈 Brad Quant"))
    st.caption(T("美股 / A股多因子量化分析", "Multi-factor analysis for U.S. equities and China A-shares"))

    tab_login, tab_reg = st.tabs([T("🔑 登录", "🔑 Sign in"), T("🆕 注册", "🆕 Register")])

    with tab_login:
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input(T("邮箱", "Email"), key="li_email", placeholder="you@example.com")
            pw = st.text_input(T("密码", "Password"), type="password", key="li_pw")
            st.caption(T("本设备会保持登录；公用设备请退出。",
                         "You will stay signed in on this device; sign out on shared devices."))
            ok = st.form_submit_button(T("登录", "Sign in"), type="primary", use_container_width=True)
        if ok:
            good, msg = userstore.verify_login(email, pw)
            if good:
                email = email.strip().lower()
                st.session_state["auth_email"] = email
                st.session_state["auth_ok"] = True
                # 下一轮完整渲染时再写入，避免紧接着的 st.rerun 抢在浏览器落盘之前。
                st.session_state["_auth_pending_save"] = email
                st.success(T(msg, "Signed in successfully."))
                st.rerun()
            else:
                st.error(T(msg, "Could not sign in. Check your email and password."))

        with st.expander(T("管理员无法登录？使用邮箱验证码恢复",
                           "Administrator recovery by email code")):
            if "auth_recovery_input" not in st.session_state:
                st.session_state["auth_recovery_input"] = st.session_state.get("li_email", "")
            recovery_email = st.text_input(
                T("管理员邮箱", "Administrator email"), key="auth_recovery_input",
                placeholder="you@example.com",
            )
            if st.button(T("发送验证码", "Send verification code"),
                         key="auth_recovery_send", use_container_width=True):
                sent, send_msg = _send_recovery_code(recovery_email)
                (st.success if sent else st.error)(
                    T(send_msg, "Verification code sent." if sent else "Could not send verification code.")
                )
            recovery_code = st.text_input(
                T("6位验证码", "6-digit code"), key="auth_recovery_code",
                max_chars=6,
            )
            if st.button(T("验证码登录", "Sign in with code"),
                         key="auth_recovery_verify", type="primary",
                         use_container_width=True):
                verified, verify_msg = _verify_recovery_code(recovery_email, recovery_code)
                if verified:
                    st.success(T(verify_msg, "Verified. Signing in."))
                    st.rerun()
                st.error(T(verify_msg, "The verification code is invalid or expired."))

    with tab_reg:
        codes = userstore.valid_invite_codes()
        if not codes and not userstore.using_supabase():
            st.info(T("当前未配置邀请码，管理员邮箱可直接注册。",
                      "No invitation code is configured; the administrator email can register directly."))
        with st.form("reg_form", clear_on_submit=False):
            r_email = st.text_input(T("邮箱", "Email"), key="rg_email", placeholder="you@example.com")
            r_pw = st.text_input(T("设置密码（至少6位）", "Password (6+ characters)"), type="password", key="rg_pw")
            r_pw2 = st.text_input(T("确认密码", "Confirm password"), type="password", key="rg_pw2")
            r_code = st.text_input(T("邀请码", "Invitation code"), key="rg_code",
                                   help=T("请向管理员索取。", "Ask the administrator."))
            ok2 = st.form_submit_button(T("注册", "Register"), use_container_width=True)
        if ok2:
            if r_pw != r_pw2:
                st.error(T("两次密码不一致。", "The passwords do not match."))
            else:
                good, msg = userstore.create_user(r_email, r_pw, r_code)
                (st.success if good else st.error)(
                    T(msg, "Registration successful." if good else "Could not register this account."))
                if good:
                    st.info(T("现在切到“登录”标签即可登录。", "Switch to the Sign in tab to continue."))


def login_gate() -> str | None:
    """返回当前登录邮箱；启用登录且未登录时渲染登录页并停止其余页面。"""
    if not auth_enabled():
        return None

    if st.session_state.pop("_auth_pending_delete", False):
        _delete_token()

    email = st.session_state.get("auth_email")
    if email:
        pending_token = st.session_state.pop("_auth_pending_token", None)
        if pending_token:
            _save_token_value(pending_token)
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
