"""待确认交易信箱 (orderstore.py)
==================================
手机端半自动确认的"信箱": 本地机器人把拟下单写进来, 手机端 App 审批, 机器人再执行。

流程:
  1. 电脑 futu_trader.py --push  → create_orders() 写入一批 status='pending' 的单
  2. 手机 App「📱 待确认」 tab   → 用户点 确认/拒绝 → set_status('approved'/'rejected')
  3. 电脑轮询 poll_batch()        → 见 'approved' 就下单 → set_status('done'/'failed')

后端与 userstore 一致 (本地 JSON orders.json / Supabase orders 表), 复用其 Secrets 与 PostgREST 封装。
纯工具, 不构成投资建议。
"""
from __future__ import annotations

import os
import json
import uuid
import datetime as dt

import userstore   # 复用 _get_secret / using_supabase / _now / _sb_headers / _sb_url

_LOCAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orders.json")

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

_OPEN = (STATUS_PENDING, STATUS_APPROVED)


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def using_supabase() -> bool:
    return userstore.using_supabase()


def backend_name() -> str:
    return "supabase" if using_supabase() else "local"


# ---------------------------------------------------------------- 本地 JSON 后端
def _local_load() -> list[dict]:
    try:
        with open(_LOCAL_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _local_save(rows: list[dict]) -> None:
    with open(_LOCAL_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- Supabase 后端
def _sb_insert_many(recs: list[dict]) -> None:
    import requests
    r = requests.post(userstore._sb_url("orders"), headers=userstore._sb_headers(),
                      data=json.dumps(recs), timeout=15)
    r.raise_for_status()


def _sb_query(qs: str) -> list[dict]:
    import requests
    r = requests.get(userstore._sb_url(f"orders?{qs}"), headers=userstore._sb_headers(),
                     timeout=15)
    r.raise_for_status()
    return r.json()


def _sb_patch(order_id: str, fields: dict) -> None:
    import requests
    r = requests.patch(userstore._sb_url(f"orders?id=eq.{order_id}"),
                       headers=userstore._sb_headers(),
                       data=json.dumps(fields), timeout=15)
    r.raise_for_status()


# ---------------------------------------------------------------- 对外 API
def create_orders(user_email: str, orders: list[dict], env: str = "paper") -> str:
    """写入一批待确认单, 返回 batch_id。orders 每项含 side/ticker/qty/price/amount/reason。"""
    user_email = (user_email or "").strip().lower()
    batch_id = dt.datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    recs = []
    for o in orders:
        recs.append({
            "id": uuid.uuid4().hex,
            "batch_id": batch_id,
            "user_email": user_email,
            "side": o["side"],
            "ticker": o["ticker"],
            "name": o.get("name", ""),
            "qty": int(o["qty"]),
            "price": float(o["price"]),
            "amount": float(o.get("amount", o["qty"] * o["price"])),
            "reason": o.get("reason", ""),
            "env": env,
            "status": STATUS_PENDING,
            "result": "",
            "created_at": _now(),
            "decided_at": None,
        })
    if not recs:
        return batch_id
    if using_supabase():
        _sb_insert_many(recs)
    else:
        rows = _local_load()
        rows.extend(recs)
        _local_save(rows)
    return batch_id


def list_pending(user_email: str) -> list[dict]:
    """某用户所有待确认(pending)的单, 供手机端展示。"""
    user_email = (user_email or "").strip().lower()
    if using_supabase():
        return _sb_query(
            f"user_email=eq.{user_email}&status=eq.{STATUS_PENDING}&order=created_at.asc")
    return [r for r in _local_load()
            if r.get("user_email") == user_email and r.get("status") == STATUS_PENDING]


def list_recent(user_email: str, limit: int = 30) -> list[dict]:
    """某用户最近的单(任意状态), 供手机端历史查看。"""
    user_email = (user_email or "").strip().lower()
    if using_supabase():
        return _sb_query(
            f"user_email=eq.{user_email}&order=created_at.desc&limit={limit}")
    rows = [r for r in _local_load() if r.get("user_email") == user_email]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows[:limit]


def get_batch(batch_id: str) -> list[dict]:
    """一批单的当前状态, 供电脑机器人轮询。"""
    if using_supabase():
        return _sb_query(f"batch_id=eq.{batch_id}&order=created_at.asc")
    return [r for r in _local_load() if r.get("batch_id") == batch_id]


def set_status(order_id: str, status: str, result: str = "") -> bool:
    fields = {"status": status, "decided_at": _now()}
    if result:
        fields["result"] = result
    try:
        if using_supabase():
            _sb_patch(order_id, fields)
        else:
            rows = _local_load()
            for r in rows:
                if r.get("id") == order_id:
                    r.update(fields)
                    break
            _local_save(rows)
        return True
    except Exception:
        return False


def decide_all(user_email: str, approve: bool) -> int:
    """把某用户所有 pending 单一次性 批准/拒绝, 返回处理条数。"""
    target = STATUS_APPROVED if approve else STATUS_REJECTED
    n = 0
    for o in list_pending(user_email):
        if set_status(o["id"], target):
            n += 1
    return n


def batch_settled(batch_id: str) -> bool:
    """一批单是否都已离开 pending/approved (即全部执行完或被拒)。"""
    rows = get_batch(batch_id)
    return bool(rows) and all(r.get("status") not in _OPEN for r in rows)


if __name__ == "__main__":
    # 本地自测 (走 orders.json)
    email = "demo@example.com"
    b = create_orders(email, [
        {"side": "BUY", "ticker": "AAPL", "name": "苹果", "qty": 10, "price": 200.0,
         "amount": 2000.0, "reason": "综合分65"},
        {"side": "SELL", "ticker": "TSLA", "name": "特斯拉", "qty": 5, "price": 250.0,
         "amount": 1250.0, "reason": "综合分40清仓"},
    ], env="paper")
    print("batch:", b)
    pend = list_pending(email)
    assert len(pend) == 2, pend
    print("pending:", len(pend))
    # 批准一笔, 拒绝一笔
    set_status(pend[0]["id"], STATUS_APPROVED)
    set_status(pend[1]["id"], STATUS_REJECTED)
    assert len(list_pending(email)) == 0
    assert batch_settled(b) is False  # approved 仍算未 settle (还没下单)
    set_status(pend[0]["id"], STATUS_DONE, "已提交 order_id=123")
    assert batch_settled(b) is True
    print("recent:", [(r["ticker"], r["status"]) for r in list_recent(email)])
    print("orderstore 自测通过")
    # 清理测试文件
    try:
        os.remove(_LOCAL_PATH)
    except Exception:
        pass
