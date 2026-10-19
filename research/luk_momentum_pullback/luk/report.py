"""Charts and tables. Palette and mark rules follow the data-viz reference palette:
strategy = blue, benchmark = orange, drawdown = red on a near-white surface."""
from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .metrics import drawdown

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#e34948"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "axes.edgecolor": GRID,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False,
    "axes.spines.right": False, "font.size": 10, "legend.frameon": False,
})


def equity_chart(equity: pd.Series, bench: pd.Series, title: str, path: str, bench_name="SPY",
                 second: pd.Series | None = None, second_name: str = ""):
    eq = equity.dropna()
    b = bench.reindex(eq.index).ffill()
    b = b / b.iloc[0] * eq.iloc[0]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.4), sharex=True,
                                   gridspec_kw=dict(height_ratios=[3, 1.2], hspace=0.08))
    ax1.plot(eq.index, eq.values, color=BLUE, lw=2, label="Strategy")
    ax1.plot(b.index, b.values, color=ORANGE, lw=2, label=f"{bench_name} buy & hold")
    if second is not None:
        s = second.dropna()
        ax1.plot(s.index, s.values, color=AQUA, lw=2, label=second_name)
    ax1.set_yscale("log")
    ax1.set_ylabel("Equity ($, log scale)")
    ax1.set_title(title, loc="left", fontsize=12, color=INK)
    ax1.legend(loc="upper left")
    for s_, col, nm in [(eq, BLUE, "Strategy"), (b, ORANGE, bench_name)]:
        ax1.annotate(f"{nm}: ${s_.iloc[-1]:,.0f}", xy=(s_.index[-1], s_.iloc[-1]), xytext=(4, 0),
                     textcoords="offset points", color=INK2, fontsize=8, va="center")
    dd_s, dd_b = drawdown(eq), drawdown(b)
    ax2.fill_between(dd_s.index, dd_s.values * 100, 0, color=BLUE, alpha=0.25, lw=0)
    ax2.plot(dd_s.index, dd_s.values * 100, color=BLUE, lw=1.2, label="Strategy drawdown")
    ax2.plot(dd_b.index, dd_b.values * 100, color=ORANGE, lw=1.2, label=f"{bench_name} drawdown")
    ax2.set_ylabel("Drawdown (%)")
    ax2.legend(loc="lower left", fontsize=8)
    fig.autofmt_xdate()
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)


def yearly_chart(ydf: pd.DataFrame, title: str, path: str, bench_name="SPY"):
    fig, ax = plt.subplots(figsize=(9, 3.8))
    x = range(len(ydf))
    w = 0.38
    ax.bar([i - w / 2 for i in x], ydf["strategy"] * 100, width=w, color=BLUE, label="Strategy")
    if "benchmark" in ydf:
        ax.bar([i + w / 2 for i in x], ydf["benchmark"] * 100, width=w, color=ORANGE, label=bench_name)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(ydf.index.astype(str))
    ax.set_ylabel("Return (%)")
    ax.set_title(title, loc="left", fontsize=12)
    ax.legend(loc="upper left")
    for i, v in enumerate(ydf["strategy"] * 100):
        ax.annotate(f"{v:+.0f}%", (i - w / 2, v), ha="center", va="bottom" if v >= 0 else "top",
                    fontsize=8, color=INK2, xytext=(0, 2 if v >= 0 else -2), textcoords="offset points")
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)


def fmt_pct(x):
    return "n/a" if pd.isna(x) else f"{x * 100:,.1f}%"


def summary_markdown(rows: list[tuple[str, dict]]) -> str:
    keys = [("total_return", "Total return", fmt_pct), ("cagr", "CAGR", fmt_pct),
            ("max_drawdown", "Max drawdown", fmt_pct), ("sharpe", "Sharpe", lambda v: f"{v:.2f}"),
            ("sortino", "Sortino", lambda v: f"{v:.2f}"), ("ann_vol", "Ann. vol", fmt_pct),
            ("n_trades", "Trades", lambda v: f"{int(v)}"), ("win_rate", "Win rate", fmt_pct),
            ("avg_win_R", "Avg win (R)", lambda v: f"{v:.2f}"), ("avg_loss_R", "Avg loss (R)", lambda v: f"{v:.2f}"),
            ("expectancy_R", "Expectancy (R)", lambda v: f"{v:.2f}"),
            ("profit_factor", "Profit factor", lambda v: f"{v:.2f}"), ("avg_bars", "Avg bars held", lambda v: f"{v:.1f}"),
            ("exposure_avg", "Avg gross exposure", fmt_pct), ("pct_days_invested", "Days with a position", fmt_pct)]
    head = "| Metric | " + " | ".join(n for n, _ in rows) + " |\n|---|" + "---|" * len(rows) + "\n"
    body = ""
    for k, label, f in keys:
        body += f"| {label} | " + " | ".join(
            ("n/a" if (k not in d or pd.isna(d[k])) else f(d[k])) for _, d in rows) + " |\n"
    return head + body


def df_markdown(df: pd.DataFrame, pct_cols=(), float_fmt="{:.2f}") -> str:
    d = df.copy()
    for c in d.columns:
        if c in pct_cols:
            d[c] = d[c].map(fmt_pct)
        elif d[c].dtype.kind == "f":
            d[c] = d[c].map(lambda v: "n/a" if pd.isna(v) else float_fmt.format(v))
    cols = [str(c) for c in d.columns]
    s = "| " + str(d.index.name or "") + " | " + " | ".join(cols) + " |\n|---|" + "---|" * len(cols) + "\n"
    for idx, row in d.iterrows():
        s += f"| {idx} | " + " | ".join(str(v) for v in row.values) + " |\n"
    return s
