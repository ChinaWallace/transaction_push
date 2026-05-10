# Freqtrade Integration

This project integrates Freqtrade as an external execution engine through Docker.
The local app remains the signal and notification layer; Freqtrade handles data
download, backtesting, dry-run, and optional live trading.

## Files

- `freqtrade/docker-compose.yml`: Docker service for Freqtrade.
- `freqtrade/user_data/config.dryrun.example.json`: safe dry-run config.
- `freqtrade/user_data/strategies/TransactionPushBridgeStrategy.py`: starter strategy.
- `app/api/freqtrade.py`: API endpoints under `/api/freqtrade`.

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
  -d "{\"strategy\":\"TransactionPushBridgeStrategy\",\"timeframe\":\"5m\",\"timerange\":\"20240101-20240501\"}"
```

Start dry-run bot:

```powershell
curl -X POST http://localhost:8000/api/freqtrade/bot/start `
  -H "Content-Type: application/json" `
  -d "{\"mode\":\"dry_run\"}"
```

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

