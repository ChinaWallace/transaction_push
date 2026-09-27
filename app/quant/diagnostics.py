"""Read-only endpoint diagnostics using exactly the configured application transport."""
from urllib.parse import urlsplit
from datetime import datetime, timezone
from .transport import PublicMarketClient, MarketDataError
from app.core.runtime_config import get_runtime_settings


def diagnose():
    settings=get_runtime_settings()
    proxy=urlsplit(settings.proxy_url or "")
    result={"checked_at":datetime.now(timezone.utc).isoformat(),
            "configuration":settings.public_status(),
            "proxy_port":proxy.port if settings.proxy_enabled else None,
            "endpoint":"/fapi/v1/time", "authenticated_account_tested":False}
    try:
        with PublicMarketClient(settings) as client:
            response=client.get("/fapi/v1/time")
        if not isinstance(response,dict) or not isinstance(response.get("serverTime"),int):
            raise MarketDataError("Unexpected time endpoint response")
        result.update(connected=True,status="public_api_connected",server_time=response["serverTime"])
    except MarketDataError as exc:
        message=str(exc)
        result.update(connected=False,status="region_restricted" if "451" in message else "connection_failed",
                      error=message,network_response_received="451" in message,
                      next_step="A 451 eligibility refusal needs Binance access eligibility/IP-classification review; API keys do not repair it"
                                if "451" in message else "Check configured proxy listener and endpoint reachability")
    return result
