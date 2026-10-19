"""Run the full study: baselines, benchmarks, yearly/regime tables, sensitivity grids.

Usage:
    python run_all.py                 # everything (stocks + crypto), writes results/
    python run_all.py --market stocks # one market
    python run_all.py --quick         # baselines only, no sensitivity grids
"""
from __future__ import annotations

import argparse
import json
import os
import time
import warnings
from dataclasses import replace

import numpy as np
import pandas as pd

from luk.config import CRYPTO_DEFAULTS, STOCK_DEFAULTS, Params
from luk.data import load_crypto, load_stocks
from luk.engine import run_backtest
from luk.features import build_features
from luk.metrics import buy_and_hold, regime_table, summarize, yearly
from luk.report import df_markdown, equity_chart, summary_markdown, yearly_chart

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "results")

START = {"stocks": "2019-01-02", "crypto": "2019-01-01"}
WARMUP = {"stocks": "2018-01-01", "crypto": "2018-01-01"}

# Sensitivity axes (one-at-a-time around the baseline) -------------------------
SENS = {
    "stop_pct": [0.02, 0.025, 0.0275, 0.03, 0.035, 0.04, 0.06, 0.08],
    "risk_pct": [0.0025, 0.005, 0.0075, 0.01],
    "partial_R": [3.0, 5.0],
    "partial_frac": [0.3, 0.5],
    "rs_rank_threshold": [0.5, 0.6, 0.7, 0.8],
    "rs_min_return": [0.2, 0.3, 0.4],
    "max_positions": [5, 8, 10],
    "max_gross_exposure": [1.0, 1.5],
    "trail_activate_R": [0.0, 1.0, 2.0],
    "entry_mode": ["breakout", "zone_open"],
    "stall_bars": [10, 15, 25],
    "max_hold_bars": [20, 60, 120],
    "ext_atr_mult": [0.0, 2.0, 3.0],
    "stop_mode": ["fixed", "tighter"],
    "vcp_ratio": [0.9, 1.0],
    "max_prior_touches": [3, 8, 20],
}
# Axes that change the feature stage (rebuild needed)
FEATURE_AXES = {"vcp_ratio", "max_prior_touches", "zone_tol_pct", "zone_min_levels", "zone_tol_atr", "ema_fast_tolerance"}
FEATURE_SENS = {"zone_tol_pct": [0.01, 0.015, 0.02], "zone_min_levels": [2, 3, 4]}


def market_setup(market: str):
    if market == "stocks":
        md = load_stocks(DATA, start=WARMUP[market])
        base = STOCK_DEFAULTS
    else:
        md = load_crypto(DATA, start=WARMUP[market])
        base = CRYPTO_DEFAULTS
    return md, base


def run_one(md, F, p, market, label):
    r = run_backtest(F, p, label=label, start=START[market])
    s = summarize(r.equity, r.trades, r.exposure, p.bars_per_year)
    return r, s


def write_baseline(md, F, p, market, tag, title):
    out = os.path.join(OUT, market)
    os.makedirs(out, exist_ok=True)
    r, s = run_one(md, F, p, market, tag)
    bh = buy_and_hold(md.benchmark, r.equity, p.bars_per_year)
    r.equity.to_frame().assign(exposure=r.exposure, n_positions=r.n_positions).to_csv(f"{out}/{tag}_equity.csv")
    r.trades.to_csv(f"{out}/{tag}_trades.csv", index=False)
    ydf = yearly(r.equity, md.benchmark, r.trades)
    ydf.index.name = "year"
    ydf.to_csv(f"{out}/{tag}_yearly.csv")
    reg = regime_table(r.equity, md.benchmark)
    reg.to_csv(f"{out}/{tag}_regime.csv", index=False)
    json.dump(dict(strategy=s, benchmark=bh, params=p.to_dict(), features=F.stats),
              open(f"{out}/{tag}_summary.json", "w"), indent=2, default=float)
    equity_chart(r.equity, md.benchmark, f"{title}: equity vs {md.benchmark_name} buy & hold",
                 f"{out}/{tag}_equity.png", bench_name=md.benchmark_name)
    yearly_chart(ydf, f"{title}: calendar-year returns", f"{out}/{tag}_yearly.png", bench_name=md.benchmark_name)
    return r, s, bh, ydf, reg


def signal_quality(F, p: Params, market: str) -> pd.DataFrame:
    """Forward close-to-close returns after a triggered entry vs. the eligible universe on the same days.

    Isolates the *selection* (setup + trigger) from the exit mechanics: if these numbers beat the
    universe but the strategy does not, the loss is in the stop/exit translation, not the screen.
    """
    C = F.close
    T = C.shape[0]
    rs = (F.rs_rank >= p.rs_rank_threshold) & (F.rs_maxret >= p.rs_min_return)
    trig = F.trigger[:-1] * (1 + p.trigger_buffer)
    with np.errstate(invalid="ignore"):
        hit = F.setup[:-1] & rs[:-1] & (F.high[1:] > trig) & (F.open[1:] <= trig * (1 + p.max_gap_pct))
    entry = np.zeros_like(F.setup)
    entry[1:] = hit                                  # entry[t]: a trade would start on bar t
    t0 = F.dates.searchsorted(pd.Timestamp(START[market]))
    rows = []
    for h in (5, 10, 20, 40):
        with np.errstate(invalid="ignore", divide="ignore"):
            fwd = C[h:] / C[:-h] - 1                 # return from close[t] to close[t+h], rows 0..T-h-1
        rows_ok = np.arange(T - h)[:, None] >= t0
        sel = fwd[entry[:T - h] & rows_ok]
        sel = sel[np.isfinite(sel)]
        univ = fwd[F.eligible[:T - h] & rows_ok]
        univ = univ[np.isfinite(univ)]
        rows.append(dict(horizon_bars=h, n_signals=len(sel), signal_mean=sel.mean(), signal_median=np.median(sel),
                         signal_hit_rate=float((sel > 0).mean()), universe_mean=univ.mean(),
                         universe_hit_rate=float((univ > 0).mean())))
    return pd.DataFrame(rows).set_index("horizon_bars")


def sensitivity(md, F_base, base: Params, market: str, feature_cache: dict):
    rows = []
    for axis, values in list(SENS.items()) + list(FEATURE_SENS.items()):
        for v in values:
            p = replace(base, **{axis: v})
            if axis in FEATURE_AXES:
                key = tuple(sorted((k, getattr(p, k)) for k in FEATURE_AXES))
                if key not in feature_cache:
                    feature_cache[key] = build_features(md, p, verbose=False)
                F = feature_cache[key]
            else:
                F = F_base
            r, s = run_one(md, F, p, market, f"{axis}={v}")
            rows.append(dict(axis=axis, value=v, is_baseline=(getattr(base, axis) == v), **s))
            print(f"  {axis:>20s}={str(v):7s} trades={s['n_trades']:4d} cagr={s['cagr']*100:6.1f}% "
                  f"dd={s['max_drawdown']*100:6.1f}% sharpe={s['sharpe']:5.2f} expR={s['expectancy_R']:5.2f}")
    return pd.DataFrame(rows)


def grid(md, F, base: Params, market: str):
    """Two-way grid: stop distance x partial level (the two exits that interact most)."""
    rows = []
    for stop in [0.02, 0.025, 0.03, 0.035, 0.04]:
        for pr in [3.0, 5.0]:
            for risk in [0.0025, 0.005, 0.01]:
                p = replace(base, stop_pct=stop, partial_R=pr, risk_pct=risk)
                r, s = run_one(md, F, p, market, "grid")
                rows.append(dict(stop_pct=stop, partial_R=pr, risk_pct=risk, **s))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["stocks", "crypto", "all"], default="all")
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    markets = ["stocks", "crypto"] if args.market == "all" else [args.market]
    os.makedirs(OUT, exist_ok=True)
    report = []

    for market in markets:
        t0 = time.time()
        md, base = market_setup(market)
        print(f"\n=== {market}: {md.notes}")
        F = build_features(md, base)
        feature_cache = {tuple(sorted((k, getattr(base, k)) for k in FEATURE_AXES)): F}

        # baseline (3R partial) and the 5R variant
        title = "US stocks" if market == "stocks" else "Crypto"
        r3, s3, bh, y3, reg3 = write_baseline(md, F, base, market, "baseline_3R", f"{title} (3R partial)")
        p5 = replace(base, partial_R=5.0)
        r5, s5, _, y5, reg5 = write_baseline(md, F, p5, market, "baseline_5R", f"{title} (5R partial)")
        print(f"[{market}] baseline 3R: {json.dumps({k: round(v, 3) for k, v in s3.items()}, default=float)}")
        print(f"[{market}] baseline 5R: {json.dumps({k: round(v, 3) for k, v in s5.items()}, default=float)}")
        print(f"[{market}] {md.benchmark_name} B&H: cagr={bh['cagr']:.3f} dd={bh['max_drawdown']:.3f} sharpe={bh['sharpe']:.2f}")

        sec = [f"## {title}\n", f"Data notes: {'; '.join(md.notes)}\n", f"Feature funnel: `{F.stats}`\n",
               "### Headline metrics\n",
               summary_markdown([("Strategy 3R partial", s3), ("Strategy 5R partial", s5), (f"{md.benchmark_name} buy & hold", bh)]),
               f"\n![equity]({market}/baseline_3R_equity.png)\n", "### Year by year (3R baseline)\n",
               df_markdown(y3, pct_cols=("strategy", "strategy_max_dd_in_year", "benchmark", "win_rate")),
               f"\n![yearly]({market}/baseline_3R_yearly.png)\n", "### Regime split (3R baseline)\n",
               df_markdown(reg3.set_index("regime"), pct_cols=("pct_of_days", "strategy_total", "strategy_ann", "benchmark_total", "benchmark_ann")),
               "### Exit reasons (3R baseline)\n",
               df_markdown(r3.trades.groupby("exit_reason").agg(n=("R", "size"), avg_R=("R", "mean"), win_rate=("pnl", lambda x: (x > 0).mean())),
                           pct_cols=("win_rate",))]

        sq = signal_quality(F, base, market)
        sq.to_csv(f"{OUT}/{market}/signal_quality.csv")
        sec += ["### Signal quality: forward returns after a triggered entry vs. the eligible universe\n",
                df_markdown(sq, pct_cols=("signal_mean", "signal_median", "signal_hit_rate", "universe_mean", "universe_hit_rate"))]

        if not args.quick:
            print(f"[{market}] sensitivity ...")
            sens = sensitivity(md, F, base, market, feature_cache)
            sens.to_csv(f"{OUT}/{market}/sensitivity.csv", index=False)
            g = grid(md, F, base, market)
            g.to_csv(f"{OUT}/{market}/grid_stop_partial_risk.csv", index=False)
            cols = ["axis", "value", "n_trades", "cagr", "max_drawdown", "sharpe", "win_rate", "expectancy_R", "profit_factor", "exposure_avg"]
            sec += ["### Sensitivity (one parameter at a time, others at baseline)\n",
                    df_markdown(sens[cols].set_index("axis"), pct_cols=("cagr", "max_drawdown", "win_rate", "exposure_avg")),
                    "### Grid: stop x partial level x risk per trade\n",
                    df_markdown(g[["stop_pct", "partial_R", "risk_pct", "n_trades", "cagr", "max_drawdown", "sharpe", "expectancy_R", "profit_factor"]].set_index("stop_pct"),
                                pct_cols=("cagr", "max_drawdown"))]
        report += sec
        print(f"[{market}] done in {time.time() - t0:.0f}s")

    with open(f"{OUT}/SUMMARY.md", "w") as f:
        f.write("# Results summary (auto-generated by run_all.py)\n\n" + "\n".join(report))
    print("wrote", f"{OUT}/SUMMARY.md")


if __name__ == "__main__":
    main()
