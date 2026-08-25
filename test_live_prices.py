"""Quick test to verify live prices from Angel One API"""
import yaml
from core.angel_client import AngelClient
from core.data_fetcher import DataFetcher

# Load config
with open('config/config.yaml') as f:
    cfg = yaml.safe_load(f)

# Login
client = AngelClient(**cfg['angel'], demo_mode=False)
if not client.login():
    print("Login failed!")
    exit(1)

print(f"✅ Logged in as {client.client_id}")

# Fetch 5 stocks only
fetcher = DataFetcher(client, max_stocks=5, rate_delay=1.0)
data = fetcher.fetch_all_ohlcv()

print(f"\n📊 Fetched {len(data)} stocks\n")
print(f"{'Stock':<15} {'Last Close':>12} {'High':>12} {'Low':>12}")
print("-" * 55)

for sym, df in data.items():
    close = df['close'].iloc[-1]
    high = df['high'].iloc[-1]
    low = df['low'].iloc[-1]
    print(f"{sym:<15} ₹{close:>11,.2f} ₹{high:>10,.2f} ₹{low:>10,.2f}")
