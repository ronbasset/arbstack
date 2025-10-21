#!/usr/bin/env python3
import asyncio
import websockets
import json
import pandas as pd
from datetime import datetime
from core.storage import write_tick
from core.metrics import ticks
import argparse
import os
from dotenv import load_dotenv

load_dotenv()

async def binance_recorder(pair: str):
    """Binance Spot WebSocket"""
    symbol = pair + 'USDT'
    uri = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@bookTicker"
    
    async with websockets.connect(uri) as ws:
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=30)
                data = json.loads(msg)
                df = pd.DataFrame([{
                    'ts': datetime.utcnow(),
                    'bid': float(data['b']),
                    'ask': float(data['a']),
                    'venue': 'binance',
                    'pair': pair
                }])
                write_tick(df, 'binance', pair)
                ticks.labels(venue='binance', pair=pair).inc()
            except asyncio.TimeoutError:
                print(f"Timeout on {pair}, reconnecting...")
            except Exception as e:
                print(f"Error: {e}")

async def kraken_recorder(pair: str):
    """Kraken Futures WebSocket"""
    symbol = f"PI_{pair}USD"  # Perpetual
    uri = f"wss://ws.kraken.com"
    
    async with websockets.connect(uri) as ws:
        subscribe = {
            "event": "subscribe",
            "pair": [symbol],
            "subscription": {"name": "book", "depth": 10}
        }
        await ws.send(json.dumps(subscribe))
        
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=30)
                data = json.loads(msg)
                if isinstance(data, list) and len(data) > 1:
                    # Parse book data
                    book = data[1]
                    df = pd.DataFrame([{
                        'ts': datetime.utcnow(),
                        'bid': float(book['as'][0][0]) if book['as'] else 0,
                        'ask': float(book['bs'][0][0]) if book['bs'] else 0,
                        'venue': 'kraken',
                        'pair': pair
                    }])
                    write_tick(df, 'kraken', pair)
                    ticks.labels(venue='kraken', pair=pair).inc()
            except Exception as e:
                print(f"Error: {e}")

async def main(args):
    tasks = []
    for pair in args.pairs.split(','):
        if args.venue == 'binance':
            tasks.append(asyncio.create_task(binance_recorder(pair)))
        elif args.venue == 'kraken':
            tasks.append(asyncio.create_task(kraken_recorder(pair)))
    
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--venue', required=True, choices=['binance', 'kraken'])
    parser.add_argument('--pairs', default='BTC,ETH,SOL')
    args = parser.parse_args()
    asyncio.run(main(args))
