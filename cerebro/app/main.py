from fastapi import FastAPI, HTTPException

from app.config import config
from app.services.opend import OpenDClient


NAME = config["cerebro"]["name"]

opend = OpenDClient(
    host=config["moomoo"]["host"],
    port=config["moomoo"]["port"],
    default_market=config["market_data"]["default_market"]
)

app = FastAPI(
    title="Cerebro",
    description="Trading bot control and market-data API",
    version="0.1.0"
)


@app.get("/")
def root():
    return {
        "service": NAME,
        "version": "0.1.0",
        "docs": "/docs"
    }


@app.get("/health")
def health():
    return {
        "service": NAME,
        "status": "UP"
    }


@app.get("/system/status")
def system_status():
    try:
        opend_status = opend.get_status()
        quote_ready = opend_status["quote_server"]

        return {
            "service": NAME,
            "status": "READY" if quote_ready else "WAITING",
            "opend": opend_status,
            "market_data": {
                "status": "READY" if quote_ready else "WAITING"
            },
            "trading": {
                "enabled": config["trading"]["enabled"],
                "mode": config["trading"]["mode"].upper()
            },
            "risk": {
                "enabled": config["risk"]["enabled"],
                "max_order_value": config["risk"]["max_order_value"],
                "max_daily_loss": config["risk"]["max_daily_loss"]
            }
        }

    except Exception as e:
        return {
            "service": NAME,
            "status": "DEGRADED",
            "opend": {
                "connected": False,
                "error": str(e)
            },
            "trading": {
                "enabled": config["trading"]["enabled"],
                "mode": config["trading"]["mode"].upper()
            }
        }


@app.get("/market/{symbol}")
def market_snapshot(symbol: str):
    try:
        return opend.get_snapshot(symbol)

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )
