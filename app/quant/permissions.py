"""Read-only permission probe for the local .env key. Never creates test or live orders."""
import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import httpx

from app.core.runtime_config import get_runtime_settings


def check_permissions(settings=None):
    settings=settings or get_runtime_settings()
    result={"configured":bool(settings.binance_api_key and settings.binance_secret_key),
            "checked_at_ms":int(time.time()*1000),"verified":False,"orders_sent":False,"credential_source":"project runtime settings"}
    if not result["configured"]:return {**result,"error":"credentials_not_configured"}
    if settings.binance_testnet:return {**result,"error":"mainnet_permission_probe_disabled_for_testnet"}
    # Signed URLs must never reach httpx INFO/debug output, including exception text.
    loggers=[logging.getLogger(n) for n in ("httpx","httpcore","httpcore.connection","httpcore.http11","httpcore.proxy")]
    disabled=[l.disabled for l in loggers]
    try:
        for logger in loggers:logger.disabled=True
        with httpx.Client(base_url="https://api.binance.com",proxy=settings.proxy_url if settings.proxy_enabled else None,
                          trust_env=False,timeout=settings.quant_http_timeout_seconds) as client:
            response=client.get("/api/v3/time")
            if not response.is_success:return {**result,"http_status":response.status_code,"error":"server_time_unavailable"}
            query=urlencode({"timestamp":response.json()["serverTime"],"recvWindow":5000})
            signature=hmac.new(settings.binance_secret_key.encode(),query.encode(),hashlib.sha256).hexdigest()
            response=client.get("/sapi/v1/account/apiRestrictions",params=query+"&signature="+signature,
                                headers={"X-MBX-APIKEY":settings.binance_api_key})
            result["http_status"]=response.status_code
            data=response.json()
            if not response.is_success:
                result.update(error_code=data.get("code"),error="permission_lookup_rejected")
                # Some credentials cannot access Wallet SAPI. Independently verify
                # futures USER_DATA, without exposing balances or assuming that
                # an account-level canTrade flag grants this API key TRADE rights.
                clock=client.get("https://fapi.binance.com/fapi/v1/time")
                if clock.is_success:
                    query=urlencode({"timestamp":clock.json()["serverTime"],"recvWindow":5000})
                    signature=hmac.new(settings.binance_secret_key.encode(),query.encode(),hashlib.sha256).hexdigest()
                    check=client.get("https://fapi.binance.com/fapi/v3/account",params=query+"&signature="+signature,
                                     headers={"X-MBX-APIKEY":settings.binance_api_key})
                    body=check.json()
                    result["futures_authentication"]={"verified":check.is_success,"http_status":check.status_code}
                    if check.is_success:
                        result["futures_authentication"]["account_can_trade"]=body.get("canTrade")
                    else:result["futures_authentication"]["error_code"]=body.get("code")
                return result
            allowed=("ipRestrict","enableReading","enableWithdrawals","enableInternalTransfer","enableMargin",
                     "enableFutures","enableSpotAndMarginTrading","enablePortfolioMarginTrading","enableVanillaOptions","permitsUniversalTransfer")
            return {**result,"verified":True,"permissions":{k:data[k] for k in allowed if isinstance(data.get(k),bool)}}
    except Exception as exc:
        return {**result,"error_type":type(exc).__name__,"error":"permission_lookup_failed"}
    finally:
        for logger,old in zip(loggers,disabled):logger.disabled=old
