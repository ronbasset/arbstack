from prometheus_client import Counter, Gauge, Summary, start_http_server

# Start server on port 8000
start_http_server(8000)

ticks = Counter("ticks_total", "Ticks ingested", ["venue", "pair"])
cycles = Counter("cycles_total", "Executable cycles", ["pair", "regime"])
rejects = Counter("rejects_total", "IOC/FOK rejects", ["venue", "pair", "reason"])
hold_s = Summary("hold_seconds", "Hold time per cycle", ["pair"])
edge_bps = Gauge("edge_bps", "Net edge per pair", ["pair"])
