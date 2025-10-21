def mid(bid: float, ask: float) -> float:
    return (bid + ask) / 2.0

def basis_decimal(spot_mid: float, fut_mid: float, usdt_usd: float = 1.0) -> float:
    adj_spot = spot_mid * usdt_usd
    return (fut_mid - adj_spot) / adj_spot
