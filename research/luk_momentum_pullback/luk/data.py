"""Data loading.

Two sources, both free and GitHub-hosted (see fetch_data.py):

* Stocks  - Johnbrick123/sp500-data: point-in-time S&P 500 membership + daily
            OHLCV for every member (incl. delisted names) + ETFs, 1996-today.
* Crypto  - Speirsy11/crypto-dataset: Binance 1d candles for 10 majors
            (2017-08 -> today) and mdeacey/binance-crypto-coins-prices:
            234 Binance USDT pairs, 1d, 2017-08 -> 2024-03-13.

Everything is returned as a `MarketData` bundle of wide (date x symbol)
DataFrames so the feature engine can work on numpy arrays.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

OHLC = ["open", "high", "low", "close"]

SECTOR_ETF = {
    "Information Technology": "XLK", "Health Care": "XLV", "Financials": "XLF",
    "Consumer Discretionary": "XLY", "Communication Services": "XLC",
    "Industrials": "XLI", "Consumer Staples": "XLP", "Energy": "XLE",
    "Utilities": "XLU", "Real Estate": "XLRE", "Materials": "XLB",
}

# Not "crypto momentum" candidates: stablecoins, wrapped/duplicate assets,
# leveraged tokens and dated contracts.
CRYPTO_EXCLUDE_BASES = {
    "USDC", "TUSD", "BUSD", "FDUSD", "DAI", "USDP", "PAX", "USDS", "USDSB", "SUSD",
    "UST", "USTC", "EUR", "GBP", "AUD", "BRL", "TRY", "RUB", "UAH", "BIDR", "IDRT",
    "NGN", "ZAR", "VAI", "PAXG", "WBTC", "WBETH", "BETH", "STETH", "AEUR", "USD1",
    "BTCST", "COCOS",  # odd listings
}


@dataclass
class MarketData:
    name: str
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame          # raw units (shares / coins)
    dollar_volume: pd.DataFrame   # raw close * raw volume
    member: pd.DataFrame          # bool: symbol is in the tradable universe that day
    benchmark: pd.Series          # buy-and-hold reference (SPY / BTC)
    benchmark_name: str
    theme: pd.DataFrame | None = None   # 0/1 theme-strength proxy per symbol-day
    notes: list = field(default_factory=list)

    @property
    def dates(self):
        return self.close.index

    @property
    def symbols(self):
        return list(self.close.columns)


# --------------------------------------------------------------------------
# Stocks
# --------------------------------------------------------------------------
def load_stocks(data_dir: str, start="2018-01-01", end=None, include_etfs=False) -> MarketData:
    import pyarrow.parquet as pq

    path = os.path.join(data_dir, "sp500_prices.parquet")
    flt = [("date", ">=", pd.Timestamp(start))]
    if end:
        flt.append(("date", "<=", pd.Timestamp(end)))
    px = pq.read_table(path, filters=flt).to_pandas()
    px["date"] = pd.to_datetime(px["date"])
    px["ticker"] = px["ticker"].astype(str)

    notes = []
    # Rows the dataset flags as halts / suspensions carried at the prior close: not tradable.
    nt_path = os.path.join(data_dir, "no_trade_days.csv")
    if os.path.exists(nt_path):
        nt = pd.read_csv(nt_path, usecols=["ticker", "date"])
        nt["date"] = pd.to_datetime(nt["date"])
        nt["_nt"] = 1
        px = px.merge(nt, on=["ticker", "date"], how="left")
        n_drop = int(px["_nt"].notna().sum())
        px = px[px["_nt"].isna()].drop(columns="_nt")
        notes.append(f"dropped {n_drop} no-trade (carried) rows")

    # Rows without OHLC (CRSP close-only patches) cannot be traded with this strategy.
    n0 = len(px)
    px = px.dropna(subset=OHLC + ["volume", "adj_close"])
    px = px[(px["high"] >= px["low"]) & (px["close"] > 0) & (px["volume"] >= 0)]
    notes.append(f"dropped {n0 - len(px)} rows lacking OHLCV")

    # Split + dividend adjusted OHLC (total-return convention, like Yahoo 'Adj Close').
    factor = px["adj_close"] / px["close"]
    for c in OHLC:
        px["a_" + c] = px[c] * factor
    # Dollar volume from the *stored* close x volume: both columns are consistently
    # split-adjusted (Yahoo rows) or consistently raw (Tiingo rows), so the product is right.
    px["dvol"] = px["close"] * px["volume"]

    mem = pd.read_parquet(os.path.join(data_dir, "membership_intervals.parquet"))
    mem["start"] = pd.to_datetime(mem["start"])
    mem["end"] = pd.to_datetime(mem["end"])
    member_tickers = set(mem["ticker"])
    recycled = os.path.join(data_dir, "recycled_tickers.csv")
    if os.path.exists(recycled):
        rc = pd.read_csv(recycled)
        if len(rc):
            px = px[~px["ticker"].isin(set(rc["ticker"]))]
            notes.append(f"excluded {len(rc)} recycled tickers")

    keep = px["ticker"].isin(member_tickers)
    if include_etfs:
        keep |= ~px["ticker"].isin(member_tickers)
    px_u = px[keep]

    def wide(col):
        return px_u.pivot(index="date", columns="ticker", values=col).sort_index()

    o, h, l, c = (wide("a_" + k) for k in OHLC)
    v, dv = wide("volume"), wide("dvol")
    dates = c.index
    # Point-in-time membership mask ([start, end) spans).
    member = pd.DataFrame(False, index=dates, columns=c.columns)
    for row in mem.itertuples(index=False):
        if row.ticker not in member.columns:
            continue
        e = row.end if pd.notna(row.end) else dates[-1] + pd.Timedelta(days=1)
        m = (dates >= row.start) & (dates < e)
        if m.any():
            member.loc[m, row.ticker] = True
    if include_etfs:
        etf_cols = [t for t in c.columns if t not in member_tickers]
        member.loc[:, etf_cols] = c[etf_cols].notna()
    member &= c.notna()

    # Benchmark and sector-theme proxy.
    spy = px[px["ticker"] == "SPY"].set_index("date")["adj_close"].sort_index()
    spy = spy.reindex(dates).ffill()
    theme = _sector_theme(px, dates, c.columns, data_dir)

    # Drop symbols that are never members in the window (saves memory).
    ever = member.any(axis=0)
    cols = ever[ever].index
    md = MarketData(
        name="US stocks (point-in-time S&P 500)",
        open=o[cols], high=h[cols], low=l[cols], close=c[cols], volume=v[cols],
        dollar_volume=dv[cols], member=member[cols], benchmark=spy, benchmark_name="SPY",
        theme=theme[cols] if theme is not None else None, notes=notes,
    )
    md.notes.append(f"{len(cols)} symbols, {len(dates)} bars, {dates[0].date()} -> {dates[-1].date()}")
    return md


def _sector_theme(px, dates, columns, data_dir):
    """1 when the stock's sector ETF has beaten SPY over the trailing 63 bars.

    Sector labels come from the *current* constituents file, so delisted names
    (and anything not in it) get no bonus. This is only a tie-break in ranking.
    """
    cpath = os.path.join(data_dir, "constituents.csv")
    if not os.path.exists(cpath):
        return None
    cons = pd.read_csv(cpath)
    cons["Symbol"] = cons["Symbol"].str.replace(".", "-", regex=False)
    sector = dict(zip(cons["Symbol"], cons["GICS Sector"]))
    etfs = sorted(set(SECTOR_ETF.values())) + ["SPY"]
    e = px[px["ticker"].isin(etfs)].pivot(index="date", columns="ticker", values="adj_close")
    e = e.reindex(dates).ffill()
    r63 = e.pct_change(63)
    strong = r63[list(SECTOR_ETF.values())].gt(r63["SPY"], axis=0)
    theme = pd.DataFrame(0.0, index=dates, columns=columns)
    for t in columns:
        s = sector.get(t)
        etf = SECTOR_ETF.get(s) if s else None
        if etf and etf in strong.columns:
            theme[t] = strong[etf].astype(float).values
    return theme


# --------------------------------------------------------------------------
# Crypto
# --------------------------------------------------------------------------
def _is_excluded_pair(sym: str) -> bool:
    if not sym.endswith("USDT") or "_" in sym:
        return True
    base = sym[:-4]
    if base in CRYPTO_EXCLUDE_BASES or base.startswith("USD"):
        return True
    if base.endswith(("UP", "DOWN", "BULL", "BEAR")) and base not in {"SUP"}:
        return True
    return False


def load_crypto(data_dir: str, start="2018-01-01", end=None, majors_only=False) -> MarketData:
    import pyarrow.dataset as ds

    frames = {}
    notes = []
    majors_root = os.path.join(data_dir, "crypto_majors", "interval_id=1d")
    if os.path.isdir(majors_root):
        tab = ds.dataset(majors_root, format="parquet", partitioning="hive").to_table()
        df = tab.to_pandas()
        df["date"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(None).dt.normalize()
        for sym, g in df.groupby("symbol"):
            g = g.drop_duplicates("date").set_index("date").sort_index()
            frames[str(sym)] = g[["open", "high", "low", "close", "volume"]].astype(float)
        notes.append(f"{len(frames)} Binance majors from Speirsy11/crypto-dataset "
                     f"({df['date'].min().date()} -> {df['date'].max().date()})")

    if not majors_only:
        n_alt = 0
        for f in sorted(glob.glob(os.path.join(data_dir, "crypto_alts", "*_D1.csv"))):
            sym = os.path.basename(f).replace("_D1.csv", "")
            if sym in frames or _is_excluded_pair(sym):
                continue
            g = pd.read_csv(f, parse_dates=["datetime"]).rename(columns={"datetime": "date"})
            g = g.drop_duplicates("date").set_index("date").sort_index()
            g = g[(g["close"] > 0) & (g["high"] >= g["low"])]
            if len(g) < 200:
                continue
            frames[sym] = g[["open", "high", "low", "close", "volume"]].astype(float)
            n_alt += 1
        notes.append(f"{n_alt} Binance alt pairs from mdeacey/binance-crypto-coins-prices "
                     f"(daily, ends 2024-03-13)")

    if not frames:
        raise FileNotFoundError("no crypto data found under " + data_dir)

    def wide(col):
        return pd.concat({s: f[col] for s, f in frames.items()}, axis=1).sort_index()

    o, h, l, c, v = (wide(k) for k in ["open", "high", "low", "close", "volume"])
    sel = (c.index >= pd.Timestamp(start))
    if end:
        sel &= (c.index <= pd.Timestamp(end))
    o, h, l, c, v = (x[sel] for x in (o, h, l, c, v))
    dv = c * v
    member = c.notna()
    btc = c["BTCUSDT"].ffill()
    # Theme proxy: "alt season" when ETH/BTC has risen over 63 bars -> alts get the
    # bonus; otherwise BTC/ETH get it. Crude stand-in for category clusters.
    eth_btc = (c["ETHUSDT"] / c["BTCUSDT"]).pct_change(63)
    alt_season = (eth_btc > 0).astype(float)
    theme = pd.DataFrame(np.repeat(alt_season.values[:, None], c.shape[1], axis=1),
                         index=c.index, columns=c.columns)
    theme[["BTCUSDT", "ETHUSDT"]] = 1.0 - theme[["BTCUSDT", "ETHUSDT"]]
    md = MarketData(
        name="Crypto (Binance USDT spot)", open=o, high=h, low=l, close=c, volume=v,
        dollar_volume=dv, member=member, benchmark=btc, benchmark_name="BTC",
        theme=theme, notes=notes,
    )
    md.notes.append(f"{c.shape[1]} symbols, {len(c)} bars, {c.index[0].date()} -> {c.index[-1].date()}")
    return md
