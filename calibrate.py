# -*- coding: utf-8 -*-
"""因子权重校准 (IC 分析, 非机器学习, 可解释)。

思路: 用历史数据检验每个"可回测的技术因子"对未来收益的预测力。
  - 每隔一段时间取一个截面, 计算当时的因子分 (只用截至当日的数据, 无未来函数);
  - 与之后 H 个交易日的远期收益配对;
  - 算 Spearman 秩相关 (IC): IC 越高 = 该因子越能预测未来涨跌;
  - 按各因子的正 IC 相对大小, 在"技术因子预算"内温和再分配权重
    (与现权重 50/50 混合, 保持稳健、可解释, 不推翻原模型)。

只校准能从历史价格算出的 5 个技术因子: 趋势/动量/强弱/相对大盘/风险。
基本面/分析师/资金流/筹码面/盈利质量/新闻情绪用的是当前快照数据,
无历史序列可回测, 权重保持不变。

用法:
    python calibrate.py                 # 默认 US+A股池, H=21日, 月度截面
    python calibrate.py --horizon 21 --step 21 --apply
    --apply  把校准后的权重写入 calibrated_weights.json (engine 若存在会自动加载)
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

import engine

TECH_FACTORS = ["趋势", "动量", "强弱", "相对大盘", "风险"]


def _pairs_for_pool(watchlist, benchmark, period, horizon, step, min_hist):
    """返回 DataFrame: 每行一个 (因子分..., fwd) 观测。"""
    tickers = list(watchlist.keys())
    data = engine.fetch(tickers + [benchmark], period=period)
    bench_df = data.get(benchmark)
    bench = bench_df["Close"] if bench_df is not None and not bench_df.empty else None
    rows = []
    for t in tickers:
        df = data.get(t)
        if df is None or df.empty or len(df) < min_hist + horizon + 5:
            print(f"  跳过 {t}: 数据不足 ({0 if df is None else len(df)} 行)")
            continue
        d = engine.add_indicators(df)
        b = bench.reindex(d.index).ffill() if bench is not None else None
        n = len(d)
        i = min_hist
        while i < n - horizon:
            sub = d.iloc[: i + 1]
            bsub = b.iloc[: i + 1] if b is not None else None
            try:
                f = engine.score_factors(sub, bsub)
            except Exception:
                i += step
                continue
            c0 = d["Close"].iloc[i]
            c1 = d["Close"].iloc[i + horizon]
            if c0 and np.isfinite(c0) and np.isfinite(c1):
                fwd = c1 / c0 - 1.0
                row = {k: f.get(k) for k in TECH_FACTORS}
                row["fwd"] = fwd
                rows.append(row)
            i += step
        print(f"  {t}: 采集 {sum(1 for r in rows)} (累计)")
    return pd.DataFrame(rows)


def compute_ic(df: pd.DataFrame) -> dict:
    ic = {}
    for k in TECH_FACTORS:
        if k in df.columns:
            s = df[[k, "fwd"]].dropna()
            if len(s) >= 30:
                # Spearman 秩相关 = 对秩做 Pearson 相关 (无需 scipy)
                ic[k] = float(s[k].rank().corr(s["fwd"].rank()))
            else:
                ic[k] = float("nan")
    return ic


def calibrate_weights(ic: dict, blend: float = 0.5) -> dict:
    """在技术因子的现有权重预算内, 按正 IC 相对大小温和再分配。
       blend: 0=完全用现权重, 1=完全用IC建议; 0.5=各一半 (推荐, 稳健)。
       非技术因子权重不动。"""
    cur = dict(engine.WEIGHTS)
    tech_budget = sum(cur.get(k, 0.0) for k in TECH_FACTORS)
    pos = {k: max(ic.get(k, 0.0) or 0.0, 0.0) for k in TECH_FACTORS}
    tot_pos = sum(pos.values())
    new = dict(cur)
    if tech_budget > 0 and tot_pos > 0:
        for k in TECH_FACTORS:
            cur_rel = cur.get(k, 0.0) / tech_budget       # 现有相对占比
            ic_rel = pos[k] / tot_pos                      # IC 建议相对占比
            mixed = (1 - blend) * cur_rel + blend * ic_rel
            new[k] = round(tech_budget * mixed, 4)
    # 归一化到总和=1 (数值稳健)
    s = sum(new.values()) or 1
    return {k: round(v / s, 4) for k, v in new.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="5y")
    ap.add_argument("--horizon", type=int, default=21, help="远期收益的交易日数")
    ap.add_argument("--step", type=int, default=21, help="截面采样间隔 (交易日)")
    ap.add_argument("--min-hist", type=int, default=220, help="起始最少历史 (需算SMA200)")
    ap.add_argument("--blend", type=float, default=0.5, help="IC建议与现权重混合比 0~1")
    ap.add_argument("--us-only", action="store_true")
    ap.add_argument("--apply", action="store_true", help="写 calibrated_weights.json")
    args = ap.parse_args()

    lines = []
    def log(m=""):
        print(m); lines.append(str(m))

    log("===== 因子权重校准 (IC 分析) =====")
    log(f"period={args.period} horizon={args.horizon}日 step={args.step}日 blend={args.blend}")

    pools = [(engine.DEFAULT_WATCHLIST, engine.BENCHMARK, "美股科技池")]
    if not args.us_only:
        pools.append((engine.A_SHARE_WATCHLIST, engine.A_BENCHMARK, "A股龙头池"))

    all_df = []
    for wl, bench, label in pools:
        log(f"\n-- {label} (基准 {bench}) --")
        df = _pairs_for_pool(wl, bench, args.period, args.horizon, args.step, args.min_hist)
        log(f"  {label} 观测数: {len(df)}")
        if not df.empty:
            all_df.append(df)

    if not all_df:
        log("没有采集到任何观测, 退出 (可能行情源限流, 稍后重试)。")
        _write_report(lines)
        os._exit(1)

    data = pd.concat(all_df, ignore_index=True)
    log(f"\n总观测数: {len(data)}")

    ic = compute_ic(data)
    log("\n各技术因子 IC (Spearman 秩相关, 越高越能预测未来收益):")
    for k in TECH_FACTORS:
        v = ic.get(k, float('nan'))
        tag = "  ✅正向" if (v or 0) > 0.02 else ("  ⚠️弱/负" if (v or 0) <= 0 else "")
        log(f"  {k:<6} IC = {v:+.4f}{tag}")

    new_w = calibrate_weights(ic, blend=args.blend)
    log("\n权重对比 (现有 -> 校准后; 只动技术因子, 其余不变):")
    for k in engine.WEIGHTS:
        old = engine.WEIGHTS[k]
        nw = new_w.get(k, old)
        mark = "  <= 变化" if abs(nw - old) >= 0.005 and k in TECH_FACTORS else ""
        log(f"  {k:<6} {old:.4f} -> {nw:.4f}{mark}")
    log(f"\n权重合计: {sum(new_w.values()):.4f}")

    if args.apply:
        out = {"weights": new_w, "ic": ic,
               "meta": {"period": args.period, "horizon": args.horizon,
                        "step": args.step, "blend": args.blend,
                        "observations": int(len(data))}}
        with open("calibrated_weights.json", "w", encoding="utf-8") as fp:
            json.dump(out, fp, ensure_ascii=False, indent=2)
        log("\n已写入 calibrated_weights.json (engine 启动时会自动加载覆盖默认权重)。")
    else:
        log("\n(未加 --apply, 仅演算, 未写文件)")

    _write_report(lines)
    os._exit(0)


def _write_report(lines):
    try:
        with open("calibrate_report.txt", "w", encoding="utf-8") as fp:
            fp.write("\n".join(lines))
    except Exception:
        pass


if __name__ == "__main__":
    main()