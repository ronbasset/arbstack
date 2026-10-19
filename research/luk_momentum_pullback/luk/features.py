"""Turn the discretionary playbook into per-bar boolean/float arrays.

All arrays are (T x N): T trading bars (rows of the wide frames) and N symbols.
Every value at row t uses data up to and including bar t (no look-ahead); the
engine then acts on bar t+1.

Pipeline per bar t:
  1. eligible  : member & liquidity & price & volatility sanity
  2. rs_rank   : cross-sectional composite percentile of 1m/3m/6m returns
  3. structure : above EMAs, EMA21 rising, higher lows, volatility contraction, not at a fresh high
  4. zone      : >=3 of {EMA9, EMA21, EMA50, AVWAP, swing highs/lows, unfilled gaps}
                 cluster within zone_tol and the bar's low tags that cluster while the close holds it
  5. setup     : 3 & 4 & touches <= max  -> trigger = bar high (buy-stop for bar t+1)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from .config import Params
from .data import MarketData


@dataclass
class Features:
    dates: pd.DatetimeIndex
    symbols: list
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    ema_fast: np.ndarray
    atr: np.ndarray
    eligible: np.ndarray      # bool
    rs_rank: np.ndarray       # composite percentile 0..1 (nan if not eligible)
    rs_maxret: np.ndarray     # best of the horizon returns
    structure: np.ndarray     # bool
    setup: np.ndarray         # bool: structure & valid zone & touches ok
    trigger: np.ndarray       # buy-stop level (setup-bar high)
    zone_lo: np.ndarray
    zone_hi: np.ndarray
    n_levels: np.ndarray
    touches: np.ndarray
    score: np.ndarray         # ranking score for candidates (higher = better)
    stats: dict


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _ema(df: pd.DataFrame, n: int) -> pd.DataFrame:
    return df.ewm(span=n, adjust=False).mean()


def _true_range(h, l, c):
    pc = c.shift(1)
    tr = np.fmax(np.fmax((h - l).values, (h - pc).abs().values), (l - pc).abs().values)
    return pd.DataFrame(tr, index=c.index, columns=c.columns)


def _pivots(x: np.ndarray, k: int, kind: str):
    """Return (pivot_idx, confirm_idx, pivot_val) for confirmed pivots in a 1-D series.

    A pivot low at i is the minimum of bars [i-k, i+k]; it is only *known* at bar i+k.
    """
    T = len(x)
    if T < 2 * k + 1:
        return np.array([], int), np.array([], int), np.array([], float)
    win = sliding_window_view(x, 2 * k + 1)
    center = x[k:T - k]
    with np.errstate(invalid="ignore"):
        ext = np.nanmin(win, axis=1) if kind == "low" else np.nanmax(win, axis=1)
    is_piv = (center == ext) & ~np.isnan(center)
    pidx = np.where(is_piv)[0] + k
    # collapse flat runs: keep the last bar of consecutive equal pivots
    if len(pidx) > 1:
        keep = np.ones(len(pidx), bool)
        keep[:-1] = ~((np.diff(pidx) == 1) & (np.diff(x[pidx]) == 0))
        pidx = pidx[keep]
    cidx = pidx + k
    return pidx, cidx, x[pidx]


def _anchored_vwap(h, l, c, v, L):
    """VWAP anchored at the lowest low of the trailing L bars (start of the current advance)."""
    T = len(c)
    out = np.full(T, np.nan)
    if T < L:
        return out
    tp = (h + l + c) / 3.0
    tpv = np.nan_to_num(tp * v)
    vv = np.nan_to_num(v)
    ctpv = np.concatenate([[0.0], np.cumsum(tpv)])
    cv = np.concatenate([[0.0], np.cumsum(vv)])
    lo = np.where(np.isnan(l), np.inf, l)
    win = sliding_window_view(lo, L)                      # rows t-L+1..t for t = L-1..T-1
    anchor = np.argmin(win, axis=1) + np.arange(T - L + 1)
    t = np.arange(L - 1, T)
    denom = cv[t + 1] - cv[anchor]
    with np.errstate(divide="ignore", invalid="ignore"):
        out[t] = np.where(denom > 0, (ctpv[t + 1] - ctpv[anchor]) / denom, np.nan)
    return out


def _gaps(h, l, min_gap):
    """Gap-ups: (bar i, bottom=high[i-1], top=low[i], filled_at) ; filled_at = first bar > i with low <= bottom."""
    T = len(h)
    with np.errstate(invalid="ignore"):
        gi = np.where(l[1:] > h[:-1] * (1 + min_gap))[0] + 1
    out = []
    for i in gi:
        bottom, top = h[i - 1], l[i]
        later = l[i + 1:]
        hit = np.where(later <= bottom)[0]
        filled_at = (i + 1 + hit[0]) if len(hit) else T + 1
        out.append((i, bottom, top, filled_at))
    return out


def _cluster(levels: np.ndarray, tol: float):
    """Largest group of levels within a relative band of `tol`. Returns (lo, hi, count)."""
    lv = np.sort(levels[~np.isnan(levels)])
    if len(lv) == 0:
        return np.nan, np.nan, 0
    best = (np.nan, np.nan, 0)
    j = 0
    for i in range(len(lv)):
        while j < len(lv) and lv[j] <= lv[i] * (1 + tol):
            j += 1
        cnt = j - i
        if cnt > best[2]:
            best = (lv[i], lv[j - 1], cnt)
    return best


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def build_features(md: MarketData, p: Params, verbose=True) -> Features:
    O, H, L, C, V, DV = md.open, md.high, md.low, md.close, md.volume, md.dollar_volume
    T, N = C.shape
    dates, symbols = C.index, list(C.columns)

    # ---- indicators (vectorised across symbols) ----------------------------
    ema_f, ema_m, ema_s = _ema(C, p.ema_fast), _ema(C, p.ema_mid), _ema(C, p.ema_slow)
    tr = _true_range(H, L, C)
    atr = tr.ewm(alpha=1.0 / 14, adjust=False).mean()
    tr_fast = tr.rolling(p.vcp_fast).mean()
    tr_slow = tr.rolling(p.vcp_slow).mean()
    adv = V.rolling(p.liq_window).mean()
    advd = DV.rolling(p.liq_window).mean()
    adv_hist = V.rolling(p.vol_hist_window, min_periods=p.liq_window * 2).mean()
    prior_high = H.rolling(p.not_new_high_window).max().shift(1)

    # ---- 1. eligibility ----------------------------------------------------
    eligible = md.member.values & C.notna().values & (C.values >= p.min_price)
    eligible &= (adv.values >= p.min_adv_shares) & (advd.values >= p.min_adv_dollars)
    with np.errstate(invalid="ignore", divide="ignore"):
        eligible &= ((atr / C).values <= p.max_atr_pct)
        vr = (adv / adv_hist).values
    eligible &= np.isnan(vr) | (vr >= p.min_vol_ratio)
    eligible &= ema_s.notna().values & (C.rolling(max(p.rs_horizons) + 1).count().values >= max(p.rs_horizons) * 0.9)

    # ---- 2. relative-strength composite rank (cross-sectional) --------------
    ranks, rets = [], []
    for hzn in p.rs_horizons:
        r = C.pct_change(hzn)
        r = r.where(eligible)
        rets.append(r.values)
        ranks.append(r.rank(axis=1, pct=True).values)
    rs_rank = np.nanmean(np.stack(ranks), axis=0)
    rs_maxret = np.nanmax(np.stack(rets), axis=0)

    # ---- 3. structure --------------------------------------------------------
    Cv, Hv, Lv = C.values, H.values, L.values
    ef, em, es = ema_f.values, ema_m.values, ema_s.values
    with np.errstate(invalid="ignore"):
        structure = (Cv > em) & (Cv >= ef * (1 - p.ema_fast_tolerance)) & (ef >= em * (1 - p.ema_fast_tolerance))
        structure &= (em > np.roll(em, p.ema_slope_bars, axis=0))
        structure &= (tr_fast.values < p.vcp_ratio * tr_slow.values)
        structure &= (Hv < prior_high.values)                # it is a pullback, not a breakout day
    structure[: p.ema_slope_bars] = False

    # per-symbol event lists (pivots, gaps, avwap) --------------------------
    k = p.pivot_k
    piv_lo, piv_hi, gaps = [], [], []
    avwap = np.full((T, N), np.nan)
    hl_ok = np.zeros((T, N), bool)
    tt = np.arange(T)
    for n in range(N):
        lo_i, lo_c, lo_v = _pivots(Lv[:, n], k, "low")
        hi_i, hi_c, hi_v = _pivots(Hv[:, n], k, "high")
        piv_lo.append((lo_i, lo_c, lo_v))
        piv_hi.append((hi_i, hi_c, hi_v))
        gaps.append(_gaps(Hv[:, n], Lv[:, n], p.min_gap_pct))
        avwap[:, n] = _anchored_vwap(Hv[:, n], Lv[:, n], Cv[:, n], V.values[:, n], p.avwap_lookback)
        # higher lows: last two *confirmed* pivot lows ascending, recent, and the
        # current bar's low above the last one (the new pullback low is higher).
        if len(lo_c) >= 2:
            ev = np.searchsorted(lo_c, tt, side="right") - 1
            ok = ev >= 1
            e1 = np.clip(ev, 0, None)
            e0 = np.clip(ev - 1, 0, None)
            with np.errstate(invalid="ignore"):
                ok &= (lo_i[e1] >= tt - p.hl_last_window) & (lo_i[e0] >= tt - p.hl_prev_window)
                ok &= (lo_v[e1] > lo_v[e0]) & (Lv[:, n] > lo_v[e1])
            hl_ok[:, n] = ok
    structure &= hl_ok

    # ---- 4. confluence zone on pre-filtered bars ----------------------------
    pre = structure & eligible
    zone_lo = np.full((T, N), np.nan)
    zone_hi = np.full((T, N), np.nan)
    n_levels = np.zeros((T, N), np.int16)
    touches = np.zeros((T, N), np.int16)
    setup = np.zeros((T, N), bool)
    atrv = atr.values
    for n in range(N):
        ts = np.where(pre[:, n])[0]
        if len(ts) == 0:
            continue
        lo_i, lo_c, lo_v = piv_lo[n]
        hi_i, hi_c, hi_v = piv_hi[n]
        g = gaps[n]
        lcol, ccol = Lv[:, n], Cv[:, n]
        for t in ts:
            low_t, close_t = lcol[t], ccol[t]
            tol = p.zone_tol_pct
            if p.zone_tol_atr > 0 and not np.isnan(atrv[t, n]):
                tol = max(tol, p.zone_tol_atr * atrv[t, n] / close_t)
            lv = [ef[t, n], em[t, n], es[t, n], avwap[t, n]]
            # confirmed swing levels within lookback (only those near price matter for clustering)
            a, b = np.searchsorted(lo_c, t - p.level_lookback), np.searchsorted(lo_c, t, side="right")
            lv.extend(lo_v[a:b][-3:])
            a, b = np.searchsorted(hi_c, t - p.level_lookback), np.searchsorted(hi_c, t, side="right")
            lv.extend(hi_v[a:b][-3:])
            lv.extend(top for (i, bottom, top, filled) in g if t - p.gap_lookback <= i < t and filled > t)
            lv = np.array(lv, float)
            lv = lv[(lv > close_t * 0.85) & (lv < close_t * 1.05)]   # only levels near price
            zlo, zhi, cnt = _cluster(lv, tol)
            if cnt < p.zone_min_levels:
                continue
            # the bar must tag the zone from above and close at/above its floor
            if not (low_t <= zhi * (1 + 0.25 * tol) and low_t >= zlo * (1 - tol) and close_t >= zlo):
                continue
            w0 = max(0, t - p.touch_window)
            prev = lcol[w0:t]
            tch = int(np.sum((prev <= zhi * (1 + 0.25 * tol)) & (prev >= zlo * (1 - tol))))
            zone_lo[t, n], zone_hi[t, n], n_levels[t, n], touches[t, n] = zlo, zhi, cnt, tch
            if tch <= p.max_prior_touches:
                setup[t, n] = True

    theme = md.theme.values if md.theme is not None else np.zeros((T, N))
    with np.errstate(invalid="ignore"):
        score = (np.nan_to_num(rs_rank) + p.theme_weight * np.nan_to_num(theme)
                 + 0.10 * (touches == 0) + 0.03 * np.clip(n_levels - p.zone_min_levels, 0, 3))

    stats = dict(
        bars=T, symbols=N,
        eligible_symbol_days=int(eligible.sum()),
        structure_days=int((structure & eligible).sum()),
        setups=int(setup.sum()),
        rs_pass_setups=int((setup & (rs_rank >= p.rs_rank_threshold) & (rs_maxret >= p.rs_min_return)).sum()),
    )
    if verbose:
        print(f"[features] {md.name}: {stats}")
    return Features(
        dates=dates, symbols=symbols, open=O.values, high=Hv, low=Lv, close=Cv,
        ema_fast=ef, atr=atr.values, eligible=eligible, rs_rank=rs_rank, rs_maxret=rs_maxret,
        structure=structure, setup=setup, trigger=Hv, zone_lo=zone_lo, zone_hi=zone_hi,
        n_levels=n_levels, touches=touches, score=score, stats=stats,
    )
