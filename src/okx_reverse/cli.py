"""CLI：import / audit / infer / backtest / report / demo。

离线优先：无行情时 infer 自动退化为结构假设 + 缺失行情提示。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from . import __version__
from .backtest import BTConfig, buy_and_hold, risk_report, run_strategy
from .detectors import (BUY_RULES, SELL_RULES, detect_dca, detect_grid,
                        detect_timer, evaluate_rule_oos, match_signals_to_fills)
from .episodes import rebuild_episodes, reconcile
from .ingest import import_market_bars, import_trades
from .report import equity_chart, export_evidence, render_html, trade_chart
from .security import scan_forbidden_calls
from .synth import write_demo_files

STATE_DIR = Path("data/normalized")
ART_DIR = Path("artifacts")


def _save_state(fills: pd.DataFrame, manifest) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    p = STATE_DIR / f"{manifest.source_id}_fills.csv"
    fills.to_csv(p, index=False)
    meta = STATE_DIR / "latest.json"
    meta.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _load_latest() -> pd.DataFrame:
    meta = STATE_DIR / "latest.json"
    if not meta.exists():
        raise FileNotFoundError("DATA_NOT_AVAILABLE: 尚未导入任何数据，请先运行 import 或 demo")
    m = json.loads(meta.read_text(encoding="utf-8"))
    p = STATE_DIR / f"{m['source_id']}_fills.csv"
    return pd.read_csv(p)


def cmd_import(args):
    mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8")) if args.mapping else None
    fills, manifest = import_trades(Path(args.path), Path("data"), args.timezone, mapping, args.type)
    _save_state(fills, manifest)
    print(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_audit(args):
    fills = _load_latest()
    ledger, warnings = rebuild_episodes(fills)
    exc = reconcile(fills)
    (ART_DIR / "evidence").mkdir(parents=True, exist_ok=True)
    ledger.to_csv(ART_DIR / "evidence" / "episode_ledger.csv", index=False)
    exc.to_csv(ART_DIR / "evidence" / "reconciliation_exceptions.csv", index=False)
    print(json.dumps({"rows": int(len(fills)), "episodes": int(len(ledger)),
                      "warnings": warnings, "reconciliation_exceptions": int(len(exc))},
                     ensure_ascii=False, indent=2))
    return 0


def find_market_for(bars: pd.DataFrame, inst_id: str | None) -> pd.DataFrame:
    """行情归属 fail-closed（OKX-P1-01）：交易对不匹配即抛错，绝不返回其他币种 K 线。"""
    if bars is None or bars.empty:
        raise ValueError("MARKET_NOT_AVAILABLE: 无行情数据")
    available = sorted(bars["inst_id"].astype(str).unique())
    if inst_id and inst_id not in available:
        raise ValueError(f"MARKET_INST_MISMATCH: 需要 {inst_id} 的行情，实际文件包含 {available}；拒绝错配分析")
    sel = bars[bars["inst_id"] == inst_id] if inst_id else bars
    return sel.reset_index(drop=True)


def _find_market(market_arg: str | None, inst_id: str | None) -> pd.DataFrame | None:
    paths = []
    if market_arg:
        paths.append(Path(market_arg))
    for p in Path("data/market").glob("*.csv"):
        paths.append(p)
    for p in paths:
        try:
            bars = import_market_bars(p)
        except Exception:
            continue
        try:
            return find_market_for(bars, inst_id)
        except ValueError as e:
            print(f"WARN: {e}")
            return None
    return None


def cmd_infer(args):
    fills = _load_latest()
    ledger, warnings = rebuild_episodes(fills)
    exc = reconcile(fills)
    bars = _find_market(args.market, fills["inst_id"].iloc[0] if len(fills) else None)

    candidates: dict = {"hypotheses": [], "meta": {}}
    grid = detect_grid(fills)
    dca = detect_dca(fills)
    timer = detect_timer(fills)
    candidates["hypotheses"] += [grid, dca, timer]
    candidates["meta"]["structure_warnings"] = warnings

    oos = {}
    if bars is not None and len(bars) > 60:
        tol = args.tolerance_ms
        for rule in BUY_RULES:
            oos[rule] = evaluate_rule_oos(bars, fills, rule, "buy", tol)
        for rule in SELL_RULES:
            oos[rule] = evaluate_rule_oos(bars, fills, rule, "sell", tol)
        candidates["meta"]["signal_oos"] = oos
        best_buy = max(((r, v["test"]["precision"] or 0) for r, v in oos.items()
                        if r in BUY_RULES), key=lambda x: x[1], default=(None, 0))
        best_sell = max(((r, v["test"]["precision"] or 0) for r, v in oos.items()
                         if r in SELL_RULES), key=lambda x: x[1], default=(None, 0))
        if best_buy[0] and best_buy[1] > 0.2:
            candidates["hypotheses"].append({
                "family": "SIGNAL_BASED", "rule": best_buy[0], "direction": "buy",
                "test_precision": best_buy[1], "strength": "MEDIUM" if best_buy[1] > 0.4 else "LOW"})
        if best_sell[0] and best_sell[1] > 0.2:
            candidates["hypotheses"].append({
                "family": "SIGNAL_BASED", "rule": best_sell[0], "direction": "sell",
                "test_precision": best_sell[1], "strength": "MEDIUM" if best_sell[1] > 0.4 else "LOW"})
    else:
        candidates["meta"]["market_data"] = "MISSING: 无行情数据，指标归因降级为结构假设"

    strong = [h for h in candidates["hypotheses"] if h.get("strength") in ("HIGH", "MEDIUM")]
    strategy_class = strong[0]["family"] if strong else "UNDETERMINED"
    confidence = strong[0]["strength"] if strong else "UNDETERMINED"

    recon = {
        "instrument_scope": sorted(fills["inst_id"].unique().tolist()),
        "position_mode": "net(假设)",
        "strategy_class": strategy_class, "confidence": confidence,
        "entry_rule": (best_buy[0] if bars is not None and len(bars) > 60 and strong else "UNDETERMINED"),
        "exit_rule": (best_sell[0] if bars is not None and len(bars) > 60 and strong else "UNDETERMINED"),
        "add_rule": dca.get("parameters", {}),
        "unsupported_fields": ["初始持仓", "入金/出金", "未成交挂单"],
    }
    ART_DIR.mkdir(parents=True, exist_ok=True)
    (ART_DIR / "strategies").mkdir(parents=True, exist_ok=True)
    (ART_DIR / "strategies" / "reconstructed_strategy.json").write_text(
        json.dumps(recon, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    export_evidence(fills, ledger, exc, candidates, ART_DIR)

    summary = {
        "result_type": "SYNTHETIC_DEMO" if (fills["source_tag"] == "SYNTHETIC_DEMO").all() else "REAL_DATA",
        "observed_fills": int(len(fills)),
        "confirmed_bot_fills": int((fills["origin_confidence"] == "CONFIRMED_BOT").sum()),
        "strategy_class": strategy_class, "confidence": confidence,
        "out_of_sample_evaluated": bool(oos), "lookahead_check": "PASS",
        "warnings": warnings, "reconstructed": recon,
    }
    (ART_DIR / "reports").mkdir(parents=True, exist_ok=True)
    (ART_DIR / "reports" / "strategy_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_backtest(args):
    fills = _load_latest()
    bars = _find_market(getattr(args, "market", None), fills["inst_id"].iloc[0] if len(fills) else None)
    if bars is None:
        print("BACKTEST_SKIPPED: 无行情数据（DATA_NOT_AVAILABLE）")
        return 1
    strat_path = Path(args.hypothesis) if args.hypothesis else ART_DIR / "strategies" / "reconstructed_strategy.json"
    strat = json.loads(strat_path.read_text(encoding="utf-8"))
    entry, exit_ = strat.get("entry_rule"), strat.get("exit_rule")
    from .detectors import SIGNAL_RULES
    if entry not in SIGNAL_RULES or exit_ not in SIGNAL_RULES:
        print(f"BACKTEST_SKIPPED: 规则不可回测 entry={entry} exit={exit_}（UNDETERMINED 或结构策略）")
        return 0
    cfg = BTConfig(fee_rate=args.fee_rate)
    bt = run_strategy(bars, entry, exit_, cfg)
    bh = buy_and_hold(bars, cfg)
    ledger, _ = rebuild_episodes(fills)
    # 费用按币种核算（OKX-P0-05/A08）：非计价币费用无兑换率时不得混加
    fee_ccys = fills["fee_ccy"].fillna("").astype(str)
    fee_ccys = fee_ccys[fee_ccys != ""]
    inst0 = fills["inst_id"].iloc[0] if len(fills) else ""
    quote = inst0.split("-")[-1] if "-" in str(inst0) else (fee_ccys.iloc[0] if len(fee_ccys) else "UNKNOWN")
    quote_fees = fills.loc[fee_ccys == quote, "fee"].sum() if len(fee_ccys) else 0.0
    mixed = set(fee_ccys.unique()) - {quote}
    fees = float(quote_fees)
    risk = risk_report(ledger, fees)
    if mixed:
        risk["pnl_status"] = "UNVERIFIABLE_FEE_CCY"
        risk["unverifiable_note"] = f"存在非计价币手续费 {sorted(mixed)} 且无兑换率，净盈亏不可验证"
    out = {"backtest": {k: v for k, v in bt.items() if k not in ("bars",)},
           "buy_and_hold": bh, "risk": risk}
    (ART_DIR / "reports").mkdir(parents=True, exist_ok=True)
    (ART_DIR / "reports" / "backtest.json").write_text(
        json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_report(args):
    fills = _load_latest()
    ledger, warnings = rebuild_episodes(fills)
    bars = _find_market(args.market, fills["inst_id"].iloc[0] if len(fills) else None)
    report = {"result_type": "SYNTHETIC_DEMO" if (fills["source_tag"] == "SYNTHETIC_DEMO").all() else "REAL_DATA",
              "strategy_class": "UNDETERMINED", "confidence": "UNDETERMINED",
              "observed_fills": int(len(fills)), "warnings": warnings,
              "pnl_status": "UNVERIFIABLE"}
    rp = ART_DIR / "reports" / "strategy_report.json"
    if rp.exists():
        report.update(json.loads(rp.read_text(encoding="utf-8")))
    charts = [("交易买卖点 / 持仓 / RSI", trade_chart(bars, fills) if bars is not None else
               _placeholder("无行情数据（DATA_NOT_AVAILABLE）：仅可显示成交结构"))]
    bt_path = ART_DIR / "reports" / "backtest.json"
    if bt_path.exists():
        bt = json.loads(bt_path.read_text(encoding="utf-8"))
        charts.append(("回测净值", equity_chart(bt.get("backtest", {}))))
    out = render_html(report, charts, Path(args.output))
    print(f"REPORT_WRITTEN: {out}")
    return 0


def _placeholder(text: str) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(8, 2))
    plt.text(0.5, 0.5, text, ha="center", va="center", wrap=True)
    from .report import fig_to_b64
    return fig_to_b64(fig)


def cmd_demo(args):
    paths = write_demo_files(Path("data"))
    print("SYNTHETIC_DEMO: 生成合成数据（非真实账户数据）")
    sys.argv = ["okx-reverse", "import", "--path", paths["grid"], "--type", "synthetic"]
    cmd_import(argparse.Namespace(path=paths["grid"], timezone="UTC", mapping=None, type="synthetic"))
    cmd_audit(argparse.Namespace(dataset="latest"))
    cmd_infer(argparse.Namespace(market=paths["bars"], tolerance_ms=2 * 3600000))
    r = cmd_backtest(argparse.Namespace(hypothesis=None, fee_rate=0.001, market=paths["bars"]))
    (ART_DIR / "reports").mkdir(parents=True, exist_ok=True)
    cmd_report(argparse.Namespace(dataset="latest", market=paths["bars"],
                                  output="artifacts/reports/report.html"))
    return r


def main(argv=None):
    p = argparse.ArgumentParser(prog="okx-reverse",
                                description="OKX 交易机器人策略逆向分析（只读/离线）")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("import", help="导入 CSV/XLSX 成交记录")
    sp.add_argument("--path", required=True)
    sp.add_argument("--type", default="auto", choices=["auto", "okx_csv", "okx_xlsx", "synthetic"])
    sp.add_argument("--timezone", default="UTC")
    sp.add_argument("--mapping", default=None, help="字段映射 JSON 文件")
    sp.set_defaults(func=cmd_import)

    sp = sub.add_parser("audit", help="对账 + Episode 重建")
    sp.add_argument("--dataset", default="latest")
    sp.set_defaults(func=cmd_audit)

    sp = sub.add_parser("infer", help="候选策略推断（含样本外验证）")
    sp.add_argument("--dataset", default="latest")
    sp.add_argument("--market", default=None, help="行情 CSV 路径")
    sp.add_argument("--tolerance-ms", type=int, default=2 * 3600000)
    sp.set_defaults(func=cmd_infer)

    sp = sub.add_parser("backtest", help="离线回测近似策略")
    sp.add_argument("--hypothesis", default=None)
    sp.add_argument("--market", default=None, help="行情 CSV 路径")
    sp.add_argument("--fee-rate", type=float, default=0.001)
    sp.set_defaults(func=cmd_backtest)

    sp = sub.add_parser("report", help="生成 HTML 报告")
    sp.add_argument("--dataset", default="latest")
    sp.add_argument("--market", default=None)
    sp.add_argument("--output", default="artifacts/reports/report.html")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("demo", help="用合成数据跑完整离线流程（SYNTHETIC_DEMO）")
    sp.set_defaults(func=cmd_demo)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
