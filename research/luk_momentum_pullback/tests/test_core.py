"""Sanity tests for the feature primitives and the engine's fill logic.
Run:  python -m pytest tests/  (or: python tests/test_core.py)"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from luk.config import Params                                   # noqa: E402
from luk.data import MarketData                                 # noqa: E402
from luk.engine import run_backtest                             # noqa: E402
from luk.features import Features, _cluster, _pivots, _anchored_vwap, _gaps  # noqa: E402


def test_cluster_finds_largest_group():
    lv = np.array([100.0, 101.0, 101.5, 110.0, 110.4, 130.0])
    lo, hi, n = _cluster(lv, 0.02)
    assert (lo, hi, n) == (100.0, 101.5, 3)
    assert _cluster(np.array([np.nan]), 0.02)[2] == 0


def test_pivots_are_confirmed_k_bars_later():
    x = np.array([5, 4, 3, 2, 3, 4, 5, 6, 5, 4, 3, 4, 5, 6, 7], float)
    pidx, cidx, val = _pivots(x, 3, "low")
    assert list(pidx) == [3, 10] and list(cidx) == [6, 13] and list(val) == [2.0, 3.0]
    hidx, hc, hv = _pivots(x, 3, "high")
    assert list(hidx) == [7] and list(hv) == [6.0]


def test_anchored_vwap_from_lowest_low():
    h = np.array([10, 9, 8, 9, 10, 11.0]); l = h - 1; c = h - 0.5; v = np.ones(6)
    out = _anchored_vwap(h, l, c, v, 4)
    # at t=5 the lowest low in the trailing 4 bars is bar 2 -> VWAP of bars 2..5 typical prices
    tp = (h + l + c) / 3
    assert np.isclose(out[5], tp[2:6].mean())
    assert np.isnan(out[2])


def test_gaps_and_fill_detection():
    h = np.array([10, 10, 12, 12.5, 12, 11.0]); l = np.array([9, 9.5, 11, 12, 11.5, 9.0])
    g = _gaps(h, l, 0.005)
    assert len(g) == 1 and g[0][0] == 2 and g[0][1] == 10 and g[0][2] == 11 and g[0][3] == 5


def _synthetic_features(T=30):
    """One symbol: a setup on bar 4, trigger taken out on bar 5, then a run to 3R and a stop."""
    dates = pd.bdate_range("2024-01-01", periods=T)
    O = np.full((T, 1), 100.0); H = O + 1; L = O - 1; C = O.copy()
    setup = np.zeros((T, 1), bool); setup[4, 0] = True
    H[4, 0] = 101.0; O[5, 0] = 100.5; H[5, 0] = 102.0; L[5, 0] = 100.0; C[5, 0] = 101.5   # entry bar
    entry = 101.0 * 1.001; R = entry * 0.03
    for t in range(6, 12):                                 # grind up to beyond 3R
        O[t, 0] = C[t - 1, 0]; C[t, 0] = C[t - 1, 0] + R; H[t, 0] = C[t, 0] + 0.2; L[t, 0] = O[t, 0] - 0.2
    O[12, 0] = C[11, 0]; L[12, 0] = 50.0; H[12, 0] = O[12, 0]; C[12, 0] = 60.0   # crash through the stop
    for t in range(13, T):
        O[t, 0] = H[t, 0] = L[t, 0] = C[t, 0] = 60.0
    ones = np.ones((T, 1))
    F = Features(dates=dates, symbols=["X"], open=O, high=H, low=L, close=C, ema_fast=C - 50, atr=ones,
                 eligible=ones.astype(bool), rs_rank=ones, rs_maxret=ones, structure=setup, setup=setup,
                 trigger=H, zone_lo=O - 2, zone_hi=O - 1, n_levels=ones.astype(int) * 3,
                 touches=np.zeros((T, 1), int), score=ones, stats={})
    return F, entry, R


def test_engine_fills_partial_then_breakeven_stop():
    F, entry, R = _synthetic_features()
    p = Params(stop_pct=0.03, risk_pct=0.01, partial_R=3.0, partial_frac=0.5, cost_bps_per_side=0,
               stop_slip_bps=0, fractional_shares=True, stall_bars=100, max_hold_bars=100, max_position_pct=1.0)
    res = run_backtest(F, p)
    tr = res.trades
    assert len(tr) == 1
    t = tr.iloc[0]
    assert np.isclose(t.entry, entry) and np.isclose(t.stop, entry * 0.97)
    assert t.partial and t.exit_reason == "stop"
    # half sold at 3R; the stop then sits at breakeven and the crash bar (open above it,
    # low far below) fills the rest at the stop price itself -> zero P&L on that half
    shares = 1000.0 / R
    exp_pnl = 0.5 * shares * 3 * R
    assert np.isclose(t.pnl, exp_pnl)
    assert np.isclose(res.equity.iloc[-1], 100_000 + exp_pnl)


def test_engine_respects_gross_exposure_cap():
    F, entry, R = _synthetic_features()
    p = Params(stop_pct=0.03, risk_pct=0.05, max_position_pct=1.0, max_gross_exposure=1.0,
               cost_bps_per_side=0, stop_slip_bps=0, fractional_shares=True, min_fill_fraction=0.0)
    res = run_backtest(F, p)
    t = res.trades.iloc[0]
    assert np.isclose(t.shares * t.entry, 100_000)          # wanted 5%/3% = 167% notional, capped at 100%


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
