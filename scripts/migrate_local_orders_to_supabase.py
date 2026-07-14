#!/usr/bin/env python3
"""把本机 orders.json 中未完成的订单迁移到 Supabase。

用法:
  python scripts/migrate_local_orders_to_supabase.py

需要先在环境变量或 config.json 配好 SUPABASE_URL / SUPABASE_KEY。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import orderstore  # noqa: E402
import userstore  # noqa: E402


ALTER_QTY_SQL = "alter table orders alter column qty type double precision using qty::double precision;"
DISABLE_RLS_SQL = "alter table users disable row level security;\nalter table orders disable row level security;"


def main() -> int:
    if not userstore.using_supabase():
        print("未配置 Supabase。请先设置 SUPABASE_URL / SUPABASE_KEY 或 config.json 的 supabase。")
        return 2

    rows = orderstore._local_load()
    open_rows = [
        r for r in rows
        if r.get("status") in {
            orderstore.STATUS_PENDING,
            orderstore.STATUS_APPROVED,
            orderstore.STATUS_EXECUTING,
        }
    ]
    if not open_rows:
        print("本机没有需要迁移的未完成订单。")
        return 0

    inserted = 0
    skipped = 0
    for row in open_rows:
        try:
            exists = orderstore._sb_query(f"id=eq.{row['id']}&select=id")
            if exists:
                skipped += 1
                continue
            orderstore._sb_insert_many([row])
            inserted += 1
        except Exception as e:
            print(f"迁移失败 {row.get('ticker')} {row.get('id')}: {e}")
            msg = str(e)
            if "invalid input syntax for type integer" in msg or "Bad Request" in msg:
                print("看起来 Supabase orders.qty 仍是 integer。请在 Supabase SQL Editor 运行:")
                print(ALTER_QTY_SQL)
                print("运行后再执行本迁移脚本。")
            elif "Unauthorized" in msg or "row-level security" in msg:
                print("看起来 Supabase 表开启了 RLS, 当前项目未接 Supabase Auth, 无法写入订单。")
                print("请在 Supabase SQL Editor 运行:")
                print(DISABLE_RLS_SQL)
                print("运行后再执行本迁移脚本。")
            return 1

    print(f"迁移完成: 新增 {inserted} 笔, 已存在跳过 {skipped} 笔。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
