"""Event-driven portfolio simulation on daily bars.

Per bar t (in this order):
  1. exits for open positions using bar t's OHLC
     stop (gap-through fills at the open) -> partial at k*R -> optional extension
     sell -> EMA trail (close below EMA9, armed after +1R or the partial) -> time stops
  2. entries: setups from bar t-1 whose trigger (setup-bar high) is taken out on bar t,
     ranked by score, limited by free slots, cash and the gross-exposure cap
  3. mark to market at the close
Sizing: shares = (risk_pct * equity) / (entry - stop); 'equity' is last close's mark.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import Params
from .features import Features


@dataclass
class Position:
    sym: int
    entry_idx: int
    entry_px: float
    stop: float
    R: float                 # per-share risk at entry
    risk_dollars: float
    shares: float
    init_shares: float
    stop_init: float = 0.0
    partial_done: bool = False
    trail_on: bool = False
    ext_done: bool = False
    realized: float = 0.0
    costs: float = 0.0
    max_close: float = 0.0
    exits: list = field(default_factory=list)


@dataclass
class Result:
    equity: pd.Series
    exposure: pd.Series       # gross notional / equity
    n_positions: pd.Series
    trades: pd.DataFrame
    params: Params
    label: str = ""


def run_backtest(F: Features, p: Params, label="", start=None, end=None) -> Result:
    O, H, L, C = F.open, F.high, F.low, F.close
    T, N = C.shape
    dates = F.dates
    t0 = 1 if start is None else max(1, dates.searchsorted(pd.Timestamp(start)))
    t1 = T if end is None else min(T, dates.searchsorted(pd.Timestamp(end), side="right"))

    cost = p.cost_bps_per_side / 1e4
    slip = p.stop_slip_bps / 1e4
    cash = p.initial_equity
    equity_prev = cash
    positions: dict[int, Position] = {}
    last_px = np.full(N, np.nan)
    cooldown_until = np.full(N, -1)
    trades = []
    eq_hist = np.full(T, np.nan)
    exp_hist = np.zeros(T)
    npos_hist = np.zeros(T, int)
    rs_ok_all = (F.rs_rank >= p.rs_rank_threshold) & (F.rs_maxret >= p.rs_min_return)

    def book(pos: Position, t, px, qty, reason):
        nonlocal cash
        qty = min(qty, pos.shares)
        if not p.fractional_shares and qty < pos.shares:
            qty = float(np.floor(qty))
            if qty <= 0:
                return False
        proceeds = qty * px
        fee = proceeds * cost
        cash += proceeds - fee
        pos.realized += qty * (px - pos.entry_px)
        pos.costs += fee
        pos.shares -= qty
        pos.exits.append((t, reason, qty, px))
        if pos.shares <= 1e-12:
            pos.shares = 0.0
            trades.append(dict(
                symbol=F.symbols[pos.sym], entry_date=dates[pos.entry_idx], exit_date=dates[t],
                entry=pos.entry_px, stop=pos.stop_init, shares=pos.init_shares,
                risk_dollars=pos.risk_dollars, pnl=pos.realized - pos.costs, costs=pos.costs,
                R=(pos.realized - pos.costs) / pos.risk_dollars, bars=t - pos.entry_idx,
                partial=pos.partial_done, exit_reason=reason, n_exits=len(pos.exits),
            ))
            cooldown_until[pos.sym] = t + p.reentry_cooldown
            return True
        return False

    for t in range(t0, t1):
        # ---------------- 1. exits ----------------
        for sym in list(positions):
            pos = positions[sym]
            o, h, l, c = O[t, sym], H[t, sym], L[t, sym], C[t, sym]
            if np.isnan(c):
                # no bar: delisted/ended series -> close at the last known price, else carry
                if t - pos.entry_idx > 0 and np.all(np.isnan(C[t:min(T, t + 5), sym])):
                    book(pos, t, last_px[sym] * (1 - slip), pos.shares, "delisted")
                    del positions[sym]
                continue
            last_px[sym] = c
            pos.max_close = max(pos.max_close, c)
            # hard stop
            if o <= pos.stop:
                if book(pos, t, o * (1 - slip), pos.shares, "stop_gap"):
                    del positions[sym]; continue
            if l <= pos.stop:
                if book(pos, t, pos.stop * (1 - slip), pos.shares, "stop"):
                    del positions[sym]; continue
            # partial at k*R (limit fill; if the open is already above, fill at the open)
            target = pos.entry_px + p.partial_R * pos.R
            if not pos.partial_done and h >= target and p.partial_frac > 0:
                px = max(target, o)
                pos.partial_done = True
                pos.trail_on = True
                if p.breakeven_after_partial:
                    pos.stop = max(pos.stop, pos.entry_px)
                if book(pos, t, px, p.partial_frac * pos.init_shares, "partial"):
                    del positions[sym]; continue
            # extension sell (optional)
            if p.ext_atr_mult > 0 and not pos.ext_done and c > F.ema_fast[t, sym] + p.ext_atr_mult * F.atr[t, sym]:
                pos.ext_done = True
                if book(pos, t, c, p.ext_frac * pos.shares, "extension"):
                    del positions[sym]; continue
            # arm the EMA trail once the trade has worked
            if not pos.trail_on and p.trail_activate_R > 0 and c >= pos.entry_px + p.trail_activate_R * pos.R:
                pos.trail_on = True
            if pos.trail_on and c < F.ema_fast[t, sym]:
                if book(pos, t, c, pos.shares, "ema_trail"):
                    del positions[sym]; continue
            held = t - pos.entry_idx
            if held >= p.stall_bars and pos.max_close < pos.entry_px + pos.R:
                if book(pos, t, c, pos.shares, "stall"):
                    del positions[sym]; continue
            if held >= p.max_hold_bars:
                if book(pos, t, c, pos.shares, "max_hold"):
                    del positions[sym]; continue

        # ---------------- 2. entries ----------------
        free = p.max_positions - len(positions)
        if free > 0:
            trig = F.trigger[t - 1] * (1 + p.trigger_buffer)
            with np.errstate(invalid="ignore"):
                if p.entry_mode == "zone_open":
                    # the hold at the zone (close >= zone floor) is the confirmation; buy the next open
                    # as long as it is not a gap away from the zone
                    cand = F.setup[t - 1] & rs_ok_all[t - 1] & (O[t] <= F.zone_hi[t - 1] * (1 + 2 * p.zone_tol_pct)) & (O[t] >= F.zone_lo[t - 1] * (1 - p.zone_tol_pct))
                    trig = O[t]
                else:
                    cand = F.setup[t - 1] & rs_ok_all[t - 1] & (H[t] > trig) & (O[t] <= trig * (1 + p.max_gap_pct))
            cand &= cooldown_until < t
            idx = np.where(cand)[0]
            if len(idx):
                idx = idx[np.argsort(-F.score[t - 1, idx])]
                invested = sum(pos.shares * last_px[s] for s, pos in positions.items() if not np.isnan(last_px[s]))
                for sym in idx:
                    if free <= 0:
                        break
                    if sym in positions:
                        continue
                    entry = max(O[t, sym], trig[sym])
                    stop = entry * (1 - p.stop_pct)
                    if p.stop_mode == "tighter" and not np.isnan(F.zone_lo[t - 1, sym]):
                        stop = max(stop, F.zone_lo[t - 1, sym] * (1 - 0.005))
                    R = entry - stop
                    if R <= 0:
                        continue
                    risk_dollars = p.risk_pct * equity_prev
                    want = risk_dollars / R
                    cap_notional = min(p.max_position_pct * equity_prev,
                                       p.max_gross_exposure * equity_prev - invested,
                                       cash / (1 + cost))
                    shares = min(want, cap_notional / entry)
                    if not p.fractional_shares:
                        shares = np.floor(shares)
                    if shares <= 0 or shares < p.min_fill_fraction * want:
                        continue
                    notional = shares * entry
                    fee = notional * cost
                    cash -= notional + fee
                    invested += notional
                    free -= 1
                    pos = Position(sym=sym, entry_idx=t, entry_px=entry, stop=stop, R=R,
                                   risk_dollars=risk_dollars, shares=shares, init_shares=shares,
                                   costs=fee, max_close=C[t, sym])
                    pos.stop_init = stop
                    positions[sym] = pos
                    last_px[sym] = C[t, sym]

        # ---------------- 3. mark ----------------
        gross = sum(pos.shares * last_px[s] for s, pos in positions.items())
        equity_prev = cash + gross
        eq_hist[t] = equity_prev
        exp_hist[t] = gross / equity_prev if equity_prev > 0 else 0
        npos_hist[t] = len(positions)

    # close whatever is open at the end so the trade log is complete
    t = t1 - 1
    for sym, pos in list(positions.items()):
        book(pos, t, last_px[sym], pos.shares, "end")
    sl = slice(t0, t1)
    eq = pd.Series(eq_hist[sl], index=dates[sl], name="equity")
    cols = ["symbol", "entry_date", "exit_date", "entry", "stop", "shares", "risk_dollars", "pnl",
            "costs", "R", "bars", "partial", "exit_reason", "n_exits"]
    tr = pd.DataFrame(trades, columns=cols)
    return Result(equity=eq, exposure=pd.Series(exp_hist[sl], index=dates[sl]),
                  n_positions=pd.Series(npos_hist[sl], index=dates[sl]), trades=tr, params=p, label=label)
