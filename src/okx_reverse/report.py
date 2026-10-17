"""T10：可视化与报告 —— 买卖点图、仓位曲线、HTML 报告、证据导出。"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager as _fm
for _f in ("Microsoft YaHei", "SimHei", "DengXian"):
    if any(_f.lower() in f.name.lower() for f in _fm.fontManager.ttflist):
        matplotlib.rcParams["font.sans-serif"] = [_f, "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
        break
import matplotlib.pyplot as plt
import pandas as pd

from .features import build_features


def fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def trade_chart(bars: pd.DataFrame, fills: pd.DataFrame) -> str:
    """面板1：价格 + 买卖点；面板2：累计持仓；面板3：RSI。"""
    f = build_features(bars)
    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1, 1]})
    x = pd.to_datetime(f["bar_start_ms"], unit="ms")
    axes[0].plot(x, f["close"], lw=0.8, color="#3355aa", label="close")
    if fills is not None and len(fills):
        b = fills[fills["side"] == "buy"]
        s = fills[fills["side"] == "sell"]
        bt = pd.to_datetime(pd.to_numeric(b["ts_ms"], errors="coerce"), unit="ms")
        st = pd.to_datetime(pd.to_numeric(s["ts_ms"], errors="coerce"), unit="ms")
        axes[0].scatter(bt, b["fill_price"], marker="^", color="green", s=28, label="buy", zorder=3)
        axes[0].scatter(st, s["fill_price"], marker="v", color="red", s=28, label="sell", zorder=3)
    axes[0].legend(loc="upper left"); axes[0].set_title("价格与买卖点 (SYNTHETIC_DEMO 数据时会有标注)")
    if fills is not None and len(fills):
        signed = fills.copy()
        signed["ts"] = pd.to_numeric(signed["ts_ms"], errors="coerce")
        signed["q"] = signed["fill_qty"] * signed["side"].map({"buy": 1, "sell": -1})
        signed = signed.dropna(subset=["ts"]).sort_values("ts")
        axes[1].plot(pd.to_datetime(signed["ts"], unit="ms"),
                     signed["q"].cumsum(), drawstyle="steps-post", color="purple")
        axes[1].set_ylabel("净持仓")
    axes[2].plot(x, f["rsi_14"], lw=0.8, color="orange", label="RSI14")
    axes[2].axhline(30, ls="--", c="g", lw=0.7); axes[2].axhline(70, ls="--", c="r", lw=0.7)
    axes[2].legend(loc="upper left")
    fig.tight_layout()
    return fig_to_b64(fig)


def equity_chart(bt: dict) -> str:
    fig, ax = plt.subplots(figsize=(10, 3.5))
    eq = bt.get("equity") or []
    if eq:
        ax.plot(eq, lw=1.0, color="#aa3355")
        ax.set_title(f"回测净值 ({bt['entry_rule']}→{bt['exit_rule']}) final={bt['final_equity']:.2f}")
    fig.tight_layout()
    return fig_to_b64(fig)


def render_html(report: dict, charts: list[tuple[str, str]], out_path: Path) -> Path:
    sections = "".join(
        f'<h2>{t}</h2><img src="data:image/png;base64,{b64}" style="max-width:100%"/>' for t, b64 in charts)
    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>OKX 策略逆向分析报告</title>
<style>body{{font-family:system-ui,'Microsoft YaHei';margin:2em;max-width:1100px}}
pre{{background:#f4f4f4;padding:1em;overflow-x:auto}}table{{border-collapse:collapse}}
td,th{{border:1px solid #ccc;padding:4px 8px}}</style></head><body>
<h1>OKX 交易机器人策略逆向分析报告</h1>
<p>结果类型：<b>{report.get('result_type')}</b>｜策略类别：<b>{report.get('strategy_class')}</b>
｜置信度：<b>{report.get('confidence')}</b></p>
<pre>{json.dumps(report, ensure_ascii=False, indent=2, default=str)}</pre>
{sections}
<p><i>免责声明：离线研究工具。历史回测不构成未来盈利保证。无实盘下单功能。</i></p>
</body></html>"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def export_evidence(fills: pd.DataFrame, ledger: pd.DataFrame, exceptions: pd.DataFrame,
                    candidates: dict, art_dir: Path) -> dict:
    art = Path(art_dir)
    for sub in ("evidence", "strategies", "reports", "charts"):
        (art / sub).mkdir(parents=True, exist_ok=True)
    paths = {}
    fills.to_csv(art / "evidence" / "normalized_trades.csv", index=False)
    ledger.to_csv(art / "evidence" / "episode_ledger.csv", index=False)
    exceptions.to_csv(art / "evidence" / "reconciliation_exceptions.csv", index=False)
    (art / "strategies" / "candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    paths.update({"fills": str(art / 'evidence' / 'normalized_trades.csv'),
                  "ledger": str(art / 'evidence' / 'episode_ledger.csv'),
                  "exceptions": str(art / 'evidence' / 'reconciliation_exceptions.csv'),
                  "candidates": str(art / 'strategies' / 'candidates.json')})
    return paths
