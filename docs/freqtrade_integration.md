# Freqtrade Integration

This project integrates Freqtrade as an external execution engine. It prefers
Docker when available, and falls back to the native `freqtrade` CLI installed in
the project venv. The local app remains the signal and notification layer;
Freqtrade handles data download, backtesting, dry-run, and optional live trading.

## Files

- `freqtrade/docker-compose.yml`: Docker service for Freqtrade.
- `freqtrade/user_data/config.dryrun.example.json`: safe dry-run config.
- `freqtrade/user_data/strategies/OpenSourceTrendStrategy.py`: default conservative
  replacement strategy using common open-source Freqtrade building blocks.
- `freqtrade/user_data/strategies/TransactionPushSignalStrategy.py`: Freqtrade-native
  strategy input for the project signal stack, kept for comparison backtests.
- `freqtrade/user_data/strategies/TransactionPushBridgeStrategy.py`: conservative
  starter strategy kept for sanity checks.
- `scripts/freqtrade_signal_backtest.py`: multi-pair long-range backtest runner
  and losing-logic filter report.
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

The checked-in dry-run config includes `aiohttp_proxy` set to
`http://127.0.0.1:7890`, matching this project's local proxy setup. Remove or
change that value if your machine does not use that proxy.

## Typical Flow

Check readiness:

```powershell
curl http://localhost:8000/api/freqtrade/status
```

Download futures data:

```powershell
curl -X POST http://localhost:8000/api/freqtrade/download-data `
  -H "Content-Type: application/json" `
  -d "{\"pairs\":[\"BTC-USDT-SWAP\",\"ETH-USDT-SWAP\"],\"timeframes\":[\"5m\",\"1h\"],\"timerange\":\"20240101-20240501\"}"
```

Run a backtest:

```powershell
curl -X POST http://localhost:8000/api/freqtrade/backtest `
  -H "Content-Type: application/json" `
  -d "{\"strategy\":\"OpenSourceTrendStrategy\",\"timeframe\":\"1h\",\"timerange\":\"20230101-20260501\"}"
```

Run the old project signal strategy across a wider coin basket and filter
losing logic:

```powershell
.\.venv\Scripts\python.exe scripts\freqtrade_signal_backtest.py `
  --timerange 20230101-20260501 `
  --timeframe 1h `
  --enable-protections
```

The script downloads the requested futures data unless `--skip-download` is
provided, runs the `baseline`, `strict_quality`, and `trend_follow` threshold
variants, then writes a report under `backtest_results/freqtrade_signal_filter_*`.
Use the report's `losing_pairs` and negative variant totals to remove weak coin
selection or threshold logic before dry-run trading.

Run the selective 4h optimized portfolio:

```powershell
.\.venv\Scripts\python.exe -m freqtrade backtesting `
  --config freqtrade\user_data\config.portfolio4h.optimized.example.json `
  --userdir freqtrade\user_data `
  --strategy CoreAltPortfolio4hOptimizedStrategy `
  --timeframe 4h `
  --timerange 20230101-20260501 `
  --cache none `
  --enable-protections `
  --export trades `
  --pairs BTC/USDT:USDT ZEC/USDT:USDT
```

Start dry-run bot:

```powershell
curl -X POST http://localhost:8000/api/freqtrade/bot/start `
  -H "Content-Type: application/json" `
  -d "{\"mode\":\"dry_run\"}"
```

Without Docker, this starts a native detached Freqtrade process. Native stop is
not managed by this project yet; Docker backend supports `/bot/stop`.

Stop bot:

```powershell
curl -X POST http://localhost:8000/api/freqtrade/bot/stop
```

## Live Trading Guardrails

Do not edit the checked-in dry-run config for real keys. Copy it locally:

```powershell
Copy-Item freqtrade\user_data\config.dryrun.example.json freqtrade\user_data\config.local.json
```

Then set real exchange keys in `config.local.json`, set `"dry_run": false`, and
review risk settings. Live trading is blocked unless the API request includes
`"confirm_live": true`, and it refuses to use `config.dryrun.example.json`.
