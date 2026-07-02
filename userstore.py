"""多用户账户与设置存储 (userstore.py)
=====================================
后端无关的用户系统, 支持两种存储后端:

  - 本地 JSON (users.json)  —— 开发/单机/兜底, 无需任何外部服务。
  - Supabase (Postgres)     —— 云端持久化 + 自带 Dashboard 当"用户后台"。
    云端只需在 Streamlit Secrets 配 SUPABASE_URL / SUPABASE_KEY 即自动启用。

设计要点:
  - 密码用标准库 pbkdf2_hmac(sha256, 20万轮) + 每用户随机 salt, 不存明文, 无第三方依赖。
  - 注册需邀请码 (INVITE_CODES, 逗号分隔), 管理员邮箱 (ADMIN_EMAILS) 免邀请码且享管理权限。
  - profile 字段: 邮箱 / 微信 SendKey / 通知邮箱 / 自选股文本 / 是否管理员 / 时间戳。

用户隐私(邮箱/SendKey)只写到私有后端, 绝不进公开仓库。
"""
from __future__ import annotations

import os
import json
import hmac
import base64
import hashlib
import datetime as dt

_LOCAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")

# profile 对外暴露时要隐藏的敏感字段
_SECRET_FIELDS = ("pw_hash", "salt")


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 密码哈希
def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if salt is None:
        salt = base64.b64encode(os.urandom(16)).decode()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return base64.b64encode(dk).decode(), salt


def verify_password(password: str, pw_hash: str, salt: str) -> bool:
    if not pw_hash or not salt:
        return False
    calc, _ = hash_password(password, salt)
    return hmac.compare_digest(calc, pw_hash)


# ---------------------------------------------------------------- 配置读取
def _get_secret(name: str, default: str = "") -> str:
    try:
        import streamlit as st
        v = st.secrets.get(name, None)
        if v:
            return str(v)
    except Exception:
        pass
    return os.getenv(name, default)


def admin_emails() -> set[str]:
    raw = _get_secret("ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def valid_invite_codes() -> set[str]:
    raw = _get_secret("INVITE_CODES", "")
    return {c.strip() for c in raw.split(",") if c.strip()}


def using_supabase() -> bool:
    return bool(_get_secret("SUPABASE_URL") and _get_secret("SUPABASE_KEY"))


def backend_name() -> str:
    return "supabase" if using_supabase() else "local"


# ---------------------------------------------------------------- 本地 JSON 后端
def _local_load() -> dict:
    try:
        with open(_LOCAL_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _local_save(data: dict) -> None:
    with open(_LOCAL_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- Supabase 后端 (PostgREST)
def _sb_headers() -> dict:
    key = _get_secret("SUPABASE_KEY")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _sb_url(path: str) -> str:
    base = _get_secret("SUPABASE_URL").rstrip("/")
    return f"{base}/rest/v1/{path}"


def _sb_get(email: str) -> dict | None:
    import requests
    r = requests.get(_sb_url(f"users?email=eq.{email}&select=*"),
                     headers=_sb_headers(), timeout=15)
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else None


def _sb_insert(rec: dict) -> None:
    import requests
    r = requests.post(_sb_url("users"), headers=_sb_headers(),
                      data=json.dumps(rec), timeout=15)
    r.raise_for_status()


def _sb_update(email: str, fields: dict) -> None:
    import requests
    r = requests.patch(_sb_url(f"users?email=eq.{email}"), headers=_sb_headers(),
                       data=json.dumps(fields), timeout=15)
    r.raise_for_status()


def _sb_list() -> list[dict]:
    import requests
    r = requests.get(_sb_url("users?select=*&order=created_at.desc"),
                     headers=_sb_headers(), timeout=15)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------- 统一记录读写
def _new_record(email: str, password: str, is_admin: bool) -> dict:
    pw_hash, salt = hash_password(password)
    return {
        "email": email,
        "pw_hash": pw_hash,
        "salt": salt,
        "watchlist_text": "",
        "sendkey": "",
        "notify_email": email,
        "is_admin": is_admin,
        "created_at": _now(),
        "last_login": None,
    }


def get_record(email: str) -> dict | None:
    email = (email or "").strip().lower()
    if not email:
        return None
    if using_supabase():
        try:
            return _sb_get(email)
        except Exception:
            return None
    return _local_load().get(email)


def _save_record(rec: dict) -> None:
    if using_supabase():
        _sb_insert(rec)
    else:
        data = _local_load()
        data[rec["email"]] = rec
        _local_save(data)


def _patch_record(email: str, fields: dict) -> None:
    if using_supabase():
        _sb_update(email, fields)
    else:
        data = _local_load()
        if email in data:
            data[email].update(fields)
            _local_save(data)


def _public(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k not in _SECRET_FIELDS}


# ---------------------------------------------------------------- 对外 API
def create_user(email: str, password: str, invite_code: str = "") -> tuple[bool, str]:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False, "请输入有效邮箱。"
    if len(password or "") < 6:
        return False, "密码至少 6 位。"
    if get_record(email):
        return False, "该邮箱已注册, 请直接登录。"

    is_admin = email in admin_emails()
    if not is_admin:
        codes = valid_invite_codes()
        if not codes:
            return False, "当前未开放注册 (未配置邀请码)。请联系管理员。"
        if invite_code.strip() not in codes:
            return False, "邀请码无效。"

    try:
        _save_record(_new_record(email, password, is_admin))
    except Exception as e:
        return False, f"注册失败(后端错误): {e}"
    return True, "注册成功, 请登录。"


def verify_login(email: str, password: str) -> tuple[bool, str]:
    email = (email or "").strip().lower()
    rec = get_record(email)
    if not rec:
        return False, "用户不存在, 请先注册。"
    if not verify_password(password, rec.get("pw_hash", ""), rec.get("salt", "")):
        return False, "密码错误。"
    try:
        _patch_record(email, {"last_login": _now()})
    except Exception:
        pass
    return True, "登录成功。"


def update_profile(email: str, *, watchlist_text: str | None = None,
                   sendkey: str | None = None, notify_email: str | None = None) -> bool:
    email = (email or "").strip().lower()
    fields = {}
    if watchlist_text is not None:
        fields["watchlist_text"] = watchlist_text
    if sendkey is not None:
        fields["sendkey"] = sendkey
    if notify_email is not None:
        fields["notify_email"] = notify_email
    if not fields:
        return True
    try:
        _patch_record(email, fields)
        return True
    except Exception:
        return False


def change_password(email: str, new_password: str) -> tuple[bool, str]:
    email = (email or "").strip().lower()
    if len(new_password or "") < 6:
        return False, "新密码至少 6 位。"
    pw_hash, salt = hash_password(new_password)
    try:
        _patch_record(email, {"pw_hash": pw_hash, "salt": salt})
        return True, "密码已更新。"
    except Exception as e:
        return False, f"更新失败: {e}"


def get_profile(email: str) -> dict | None:
    rec = get_record(email)
    return _public(rec) if rec else None


def list_users() -> list[dict]:
    """管理员用: 返回所有用户(不含密码哈希)。"""
    if using_supabase():
        try:
            rows = _sb_list()
        except Exception:
            rows = []
    else:
        rows = list(_local_load().values())
    return [_public(r) for r in rows]


def count_users() -> int:
    return len(list_users())


def is_admin(email: str) -> bool:
    email = (email or "").strip().lower()
    if email in admin_emails():
        return True
    rec = get_record(email)
    return bool(rec and rec.get("is_admin"))


if __name__ == "__main__":
    # 本地快速自测 (使用 local JSON 后端)
    os.environ["INVITE_CODES"] = "TEST123"
    os.environ["ADMIN_EMAILS"] = "admin@demo.com"
    print("backend =", backend_name())
    print(create_user("admin@demo.com", "secret123"))          # 管理员免邀请码
    print(create_user("u1@demo.com", "pass123", "TEST123"))    # 带邀请码
    print(create_user("u2@demo.com", "pass123", "WRONG"))      # 邀请码错误
    print(verify_login("u1@demo.com", "pass123"))
    print(verify_login("u1@demo.com", "bad"))
    update_profile("u1@demo.com", sendkey="SCT_xxx", watchlist_text="AAPL 苹果\nNVDA 英伟达")
    print("admin? u1 =", is_admin("u1@demo.com"), " admin =", is_admin("admin@demo.com"))
    print("users =", [u["email"] for u in list_users()])
