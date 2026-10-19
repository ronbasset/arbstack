"""Performance statistics, yearly / regime breakdowns."""
from __future__ import annotations

import numpy as np
import pandas as pd


def summarize(equity: pd.Series, trades: pd.DataFrame, exposure: pd.Series, bars_per_year=252) -> dict:
    eq = equity.dropna()
    r = eq.pct_change().dropna()
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    total = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    dd = eq / eq.cummax() - 1
    sd = r.std()
    dsd = r[r < 0].std()
    out = dict(
        total_return=total, cagr=cagr, max_drawdown=dd.min(),
        sharpe=(r.mean() / sd * np.sqrt(bars_per_year)) if sd > 0 else np.nan,
        sortino=(r.mean() / dsd * np.sqrt(bars_per_year)) if dsd and dsd > 0 else np.nan,
        ann_vol=sd * np.sqrt(bars_per_year),
        n_trades=len(trades),
        exposure_avg=float(exposure.mean()) if len(exposure) else 0.0,
        pct_days_invested=float((exposure > 0).mean()) if len(exposure) else 0.0,
        years=years,
    )
    if len(trades):
        w = trades[trades.pnl > 0]
        l = trades[trades.pnl <= 0]
        out.update(
            win_rate=len(w) / len(trades),
            avg_win_R=w.R.mean() if len(w) else np.nan,
            avg_loss_R=l.R.mean() if len(l) else np.nan,
            expectancy_R=trades.R.mean(),
            profit_factor=(w.pnl.sum() / -l.pnl.sum()) if len(l) and l.pnl.sum() < 0 else np.inf,
            avg_bars=trades.bars.mean(),
            median_bars=trades.bars.median(),
            trades_per_year=len(trades) / years,
            pct_partial=trades.partial.mean(),
        )
    else:
        out.update(win_rate=np.nan, avg_win_R=np.nan, avg_loss_R=np.nan, expectancy_R=np.nan,
                   profit_factor=np.nan, avg_bars=np.nan, median_bars=np.nan, trades_per_year=0, pct_partial=np.nan)
    return out


def buy_and_hold(bench: pd.Series, equity: pd.Series, bars_per_year=252) -> dict:
    b = bench.reindex(equity.index).ffill().dropna()
    b = b / b.iloc[0] * equity.dropna().iloc[0]
    return summarize(b, pd.DataFrame(), pd.Series(1.0, index=b.index), bars_per_year)


def yearly(equity: pd.Series, bench: pd.Series | None = None, trades: pd.DataFrame | None = None) -> pd.DataFrame:
    eq = equity.dropna()
    ye = eq.groupby(eq.index.year).agg(["first", "last"])
    # chain: year return uses previous year's last value where available
    prev = ye["last"].shift(1).fillna(ye["first"])
    df = pd.DataFrame({"strategy": ye["last"] / prev - 1})
    dd = eq / eq.cummax() - 1
    df["strategy_max_dd_in_year"] = (eq / eq.groupby(eq.index.year).cummax() - 1).groupby(eq.index.year).min()
    if bench is not None:
        b = bench.reindex(eq.index).ffill()
        yb = b.groupby(b.index.year).agg(["first", "last"])
        prevb = yb["last"].shift(1).fillna(yb["first"])
        df["benchmark"] = yb["last"] / prevb - 1
    if trades is not None and len(trades):
        g = trades.groupby(trades.exit_date.dt.year)
        df["trades"] = g.size()
        df["win_rate"] = g.apply(lambda x: (x.pnl > 0).mean())
        df["avg_R"] = g.R.mean()
    return df


def regime_table(equity: pd.Series, bench: pd.Series, sma=200) -> pd.DataFrame:
    """Split days by whether the benchmark closes above its 200-bar SMA (uptrend) or not."""
    eq = equity.dropna()
    b = bench.reindex(eq.index).ffill()
    b_full = bench.ffill()
    above = (b_full > b_full.rolling(sma).mean()).reindex(eq.index).fillna(False)
    r = eq.pct_change().fillna(0)
    rb = b.pct_change().fillna(0)
    rows = []
    for name, mask in [("benchmark above 200-SMA (uptrend)", above), ("benchmark below 200-SMA (down/sideways)", ~above)]:
        n = int(mask.sum())
        if n == 0:
            continue
        rows.append(dict(regime=name, days=n, pct_of_days=n / len(eq),
                         strategy_total=(1 + r[mask]).prod() - 1,
                         strategy_ann=((1 + r[mask]).prod()) ** (252 / n) - 1 if n > 20 else np.nan,
                         benchmark_total=(1 + rb[mask]).prod() - 1,
                         benchmark_ann=((1 + rb[mask]).prod()) ** (252 / n) - 1 if n > 20 else np.nan))
    return pd.DataFrame(rows)


def drawdown(equity: pd.Series) -> pd.Series:
    eq = equity.dropna()
    return eq / eq.cummax() - 1
