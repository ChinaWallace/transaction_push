# BTC/ETH Freqtrade Dry-run Baseline

This project uses Freqtrade for BTC/ETH data download, backtesting, and dry-run
forward validation. Live trading is deliberately disabled. The baseline is
Binance USDT perpetual futures, 4h, long-only, isolated margin, and 1x leverage.

## Files

- `freqtrade/docker-compose.yml`: Docker service for Freqtrade.
- `freqtrade/user_data/config.btc_eth.dryrun.example.json`: enforced dry-run config.
- `freqtrade/user_data/strategies/BtcEth4hStrategy.py`: default research strategy.
- `freqtrade/user_data/strategies/TransactionPushSignalStrategy.py`: Freqtrade-native
  strategy input for the project signal stack, kept for comparison backtests.
- `freqtrade/user_data/strategies/TransactionPushBridgeStrategy.py`: conservative
  starter strategy kept for sanity checks.
- `scripts/freqtrade_signal_backtest.py`: BTC/ETH backtest runner and report.
- `app/api/freqtrade.py`: API endpoints under `/api/freqtrade`.

## Backend Selection

Default backend is `auto`:

- Docker backend: used when `docker compose` is available.
- Native backend: used when Docker is missing but `.venv/Scripts/freqtrade.exe`
  or `freqtrade` on PATH is available.

You can force a backend:

```powershell
$env:FREQTRADE_BACKEND="native"
$env:FREQTRADE_BIN="D:\workProjects\transaction_push\.venv\Scripts\freqtrade.exe"
```

## Typical Flow

Check readiness:

```powershell
curl http://localhost:8000/api/freqtrade/status
```

Download futures data:

```powershell
curl -X POST http://localhost:8000/api/freqtrade/download-data `
  -H "Content-Type: application/json" `
  -d "{\"pairs\":[\"BTC-USDT-SWAP\",\"ETH-USDT-SWAP\"],\"timeframes\":[\"4h\"],\"timerange\":\"20240101-20240501\"}"
```

Run a backtest:

```powershell
curl -X POST http://localhost:8000/api/freqtrade/backtest `
  -H "Content-Type: application/json" `
  -d "{\"strategy\":\"BtcEth4hStrategy\",\"timeframe\":\"4h\",\"timerange\":\"20230101-20260501\"}"
```

Run the same baseline directly:

```powershell
.\.venv\Scripts\python.exe scripts\freqtrade_signal_backtest.py `
  --timerange 20230101-20260501 `
  --timeframe 4h
```

The script rejects every pair other than BTC and ETH, enables protections by
default, and writes a report under `backtest_results/freqtrade_signal_filter_*`.

Start dry-run bot:

```powershell
curl -X POST http://localhost:8000/api/freqtrade/bot/start `
  -H "Content-Type: application/json" `
  -d "{\"mode\":\"dry_run\"}"
```

Without Docker, this starts a native detached Freqtrade process. Both backends
support `/bot/stop`.

Stop bot:

```powershell
curl -X POST http://localhost:8000/api/freqtrade/bot/stop
```

## Safety Boundary

The application checks the config contents before every managed download,
backtest, or bot start. It requires exactly BTC and ETH, `dry_run=true`, 4h,
isolated futures, at most two positions, and a disabled Freqtrade API server.
Requests for other strategies, pairs, timeframes, configs, or live mode fail
closed. Do not put exchange keys into the checked-in example config.

Before live trading can be introduced, add authenticated administration,
testnet evidence, persistent order state, idempotency, stale-market-data checks,
daily-loss and drawdown circuit breakers, and an audited manual kill switch.
