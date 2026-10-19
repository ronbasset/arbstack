"""Download the free, GitHub-hosted datasets used by the backtest into ./data (gitignored).

Sources (all public, no API keys):
  * Stocks : https://github.com/Johnbrick123/sp500-data  (release asset `prices.parquet`,
             point-in-time S&P 500 membership, daily OHLCV incl. delisted names, ETFs)
  * Crypto : https://github.com/Speirsy11/crypto-dataset  (Binance 1d candles, 10 majors,
             2017-08 -> today, Git-LFS parquet partitions)
             https://github.com/mdeacey/binance-crypto-coins-prices (234 Binance USDT pairs,
             daily CSV, 2017-08 -> 2024-03-13)
  * Sectors: https://github.com/datasets/s-and-p-500-companies (current GICS sectors)

Run:  python fetch_data.py            (~260 MB total)
"""
from __future__ import annotations

import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

SP500_RELEASE = "https://github.com/Johnbrick123/sp500-data/releases/download/data/"
SP500_FILES = {"prices.parquet": "sp500_prices.parquet", "membership_intervals.parquet": "membership_intervals.parquet",
               "no_trade_days.csv": "no_trade_days.csv", "recycled_tickers.csv": "recycled_tickers.csv",
               "exit_gaps.csv": "exit_gaps.csv"}
CONSTITUENTS = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
CRYPTO_MAJORS_REPO = "https://github.com/Speirsy11/crypto-dataset"
CRYPTO_MAJORS_LFS = "https://media.githubusercontent.com/media/Speirsy11/crypto-dataset/main/"
CRYPTO_ALTS_REPO = "https://github.com/mdeacey/binance-crypto-coins-prices"


def download(url, dest, quiet=False):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not quiet:
        print(f"  {url} -> {dest}")
    with urllib.request.urlopen(url, timeout=120) as r, open(dest + ".tmp", "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    os.replace(dest + ".tmp", dest)
    return dest


def sparse_clone(repo, dest, patterns):
    """Shallow, blob-less clone with a sparse checkout of `patterns` (no LFS smudge)."""
    if os.path.isdir(os.path.join(dest, ".git")):
        return
    env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1")
    subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout", repo, dest], check=True, env=env)
    subprocess.run(["git", "-C", dest, "sparse-checkout", "init", "--no-cone"], check=True)
    subprocess.run(["git", "-C", dest, "sparse-checkout", "set"] + patterns, check=True)
    subprocess.run(["git", "-C", dest, "checkout", "HEAD"], check=True, env=env)


def fetch_stocks():
    print("[stocks] S&P 500 point-in-time dataset")
    for src, dst in SP500_FILES.items():
        download(SP500_RELEASE + src, os.path.join(DATA, dst))
    download(CONSTITUENTS, os.path.join(DATA, "constituents.csv"))


def fetch_crypto_majors():
    print("[crypto] Binance majors (Speirsy11/crypto-dataset, daily partitions via Git LFS)")
    tmp = os.path.join(DATA, "_crypto_majors_repo")
    sparse_clone(CRYPTO_MAJORS_REPO, tmp, ["data/interval_id=1d/*"])
    root = os.path.join(tmp, "data", "interval_id=1d")
    n = 0
    for dirpath, _, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".parquet"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), tmp)
            dest = os.path.join(DATA, "crypto_majors", os.path.relpath(os.path.join(dirpath, fn), os.path.join(tmp, "data")))
            if os.path.exists(dest) and os.path.getsize(dest) > 200:
                continue
            # the checkout holds LFS pointer stubs; the real bytes come from the media host
            download(CRYPTO_MAJORS_LFS + rel, dest, quiet=True)
            n += 1
    print(f"  fetched {n} parquet partitions")


def fetch_crypto_alts():
    print("[crypto] Binance alt pairs (mdeacey/binance-crypto-coins-prices, daily CSV)")
    tmp = os.path.join(DATA, "_crypto_alts_repo")
    sparse_clone(CRYPTO_ALTS_REPO, tmp, ["csv/*_D1.csv"])
    dest = os.path.join(DATA, "crypto_alts")
    os.makedirs(dest, exist_ok=True)
    n = 0
    for fn in os.listdir(os.path.join(tmp, "csv")):
        if fn.endswith("_D1.csv"):
            src = os.path.join(tmp, "csv", fn)
            dst = os.path.join(dest, fn)
            if not os.path.exists(dst):
                os.replace(src, dst)
                n += 1
    print(f"  staged {n} daily CSVs")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    os.makedirs(DATA, exist_ok=True)
    if which in ("all", "stocks"):
        fetch_stocks()
    if which in ("all", "crypto"):
        fetch_crypto_majors()
        fetch_crypto_alts()
    print("done ->", DATA)
