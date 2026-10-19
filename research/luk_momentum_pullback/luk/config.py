"""All tunable parameters in one place.

Every rule in the strategy write-up maps to a field here, so sensitivity tests
are just `replace(Params(), stop_pct=0.03)`.
"""
from dataclasses import dataclass, asdict, replace, field


@dataclass(frozen=True)
class Params:
    # ---- universe / liquidity -------------------------------------------
    min_price: float = 5.0            # skip penny stocks (stocks only, crypto ignores)
    min_adv_shares: float = 1_000_000 # 20-day average volume (shares); crypto ignores
    min_adv_dollars: float = 10_000_000  # 20-day average dollar volume
    liq_window: int = 20
    vol_hist_window: int = 120
    min_vol_ratio: float = 0.30       # adv20 / adv120 must exceed this ("very low volume vs history")
    max_atr_pct: float = 0.08         # ATR14 / close above this = "extreme" volatility, skip

    # ---- relative strength ranking -----------------------------------------
    rs_horizons: tuple = (21, 63, 126)  # 1m / 3m / 6m in trading bars
    rs_rank_threshold: float = 0.70     # composite percentile rank must be >= (top 30%)
    rs_min_return: float = 0.30         # up >= 30% on at least one horizon
    theme_weight: float = 0.10          # score bonus when sector/theme proxy is strong

    # ---- "resting, not falling" structure ----------------------------------
    ema_fast: int = 9
    ema_mid: int = 21
    ema_slow: int = 50
    ema_fast_tolerance: float = 0.03    # setup-day close may sit up to 3% under EMA9 (a tag of the 21-EMA zone)
    ema_slope_bars: int = 5             # EMA21 must be higher than this many bars ago
    pivot_k: int = 3                    # pivot = extreme of +/- k bars (confirmed k bars later)
    hl_last_window: int = 30            # last confirmed pivot low must be within this many bars
    hl_prev_window: int = 60            # the previous one within this many bars
    vcp_fast: int = 5
    vcp_slow: int = 20
    vcp_ratio: float = 0.90             # mean TR(5) < ratio * mean TR(20)  => contraction
    not_new_high_window: int = 10       # setup day must not be a fresh N-day high (it is a pullback)

    # ---- support / confluence zone ----------------------------------------
    zone_tol_pct: float = 0.015         # levels within 1.5% of each other cluster
    zone_tol_atr: float = 0.5           # tolerance = max(zone_tol_pct, zone_tol_atr * ATR14 / close); scales with volatility
    zone_min_levels: int = 3
    level_lookback: int = 60            # pivots considered as levels
    gap_lookback: int = 90              # unfilled gaps considered as levels
    min_gap_pct: float = 0.005
    avwap_lookback: int = 120           # anchor = lowest low in this window (start of advance)
    touch_window: int = 20
    max_prior_touches: int = 8          # first retest is preferred via the score; reject only well-tested (choppy) zones

    # ---- entry trigger -----------------------------------------------------
    entry_mode: str = "breakout"        # "breakout": buy-stop above the setup bar high; "zone_open": buy next open after the hold
    trigger_buffer: float = 0.001       # buy-stop just above the setup bar high
    max_gap_pct: float = 0.02           # skip if open gaps more than this above the trigger
    reentry_cooldown: int = 5           # bars after an exit before the same name can be re-entered

    # ---- risk / sizing -----------------------------------------------------
    stop_pct: float = 0.0275            # hard stop distance from entry
    stop_mode: str = "fixed"            # "fixed" or "tighter" (min of fixed and zone low)
    risk_pct: float = 0.005             # 0.5% of equity per trade
    max_positions: int = 8
    max_gross_exposure: float = 1.0     # 1.0 = no leverage
    max_position_pct: float = 0.30      # single-name notional cap (fraction of equity)
    min_fill_fraction: float = 0.5      # skip if cash allows less than this fraction of the intended size
    fractional_shares: bool = False

    # ---- exits -------------------------------------------------------------
    partial_R: float = 3.0              # scale out at this R-multiple
    partial_frac: float = 0.5           # fraction sold at the partial
    breakeven_after_partial: bool = True
    trail_activate_R: float = 0.0       # >0: EMA trail also arms once close >= entry + R * this; 0 = only after the partial
    ext_atr_mult: float = 0.0           # >0: sell ext_frac when close > EMA9 + mult*ATR (0 = off)
    ext_frac: float = 0.25
    stall_bars: int = 15                # exit if trade never reached +1R after this many bars
    max_hold_bars: int = 60

    # ---- costs & account ---------------------------------------------------
    cost_bps_per_side: float = 5.0      # commission + spread per side (0.10% round trip)
    stop_slip_bps: float = 10.0         # extra slippage on stop fills
    initial_equity: float = 100_000.0
    bars_per_year: int = 252            # 365 for crypto

    def with_(self, **kw):
        return replace(self, **kw)

    def to_dict(self):
        return asdict(self)


STOCK_DEFAULTS = Params()
CRYPTO_DEFAULTS = Params(
    min_price=0.0, min_adv_shares=0.0, min_adv_dollars=10_000_000,
    max_atr_pct=0.15, cost_bps_per_side=10.0, stop_slip_bps=20.0,
    fractional_shares=True, bars_per_year=365,
)
