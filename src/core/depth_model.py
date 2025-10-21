def est_slip_bps(size_usd: float, depth_usd_near_mid: float, spread_bps: float, base_bps: float) -> float:
    pct_depth = size_usd / max(depth_usd_near_mid, 1.0)
    return (pct_depth * (spread_bps / 2.0)) + base_bps
