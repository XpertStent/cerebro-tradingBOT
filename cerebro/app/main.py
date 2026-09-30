from fastapi import FastAPI

from app.config import config
from app.services.opend import opend
from app.api.market import router as market_router
from app.api.portfolio import router as portfolio_router


NAME = config["cerebro"]["name"]


app = FastAPI(
    title="Cerebro",
    description="Trading bot control and market-data API",
    version="0.2.0"
)


app.include_router(market_router)
app.include_router(portfolio_router)


@app.get("/", tags=["System"])
def root():

    return {
        "service": NAME,
        "version": "0.2.0",
        "status_endpoint": "/system/status",
        "documentation": "/docs"
    }


@app.get("/health", tags=["System"])
def health():

    return {
        "service": NAME,
        "status": "UP"
    }


@app.get("/system/status", tags=["System"])
def system_status():

    try:

        opend_status = opend.get_status()

        quote_ready = (
            opend_status["quote_server"]
        )

        return {
            "service": NAME,

            "status":
                "READY"
                if quote_ready
                else "WAITING",

            "opend": opend_status,

            "market_data": {
                "status":
                    "READY"
                    if quote_ready
                    else "WAITING"
            },

            "trading": {
                "enabled":
                    config["trading"]["enabled"],

                "mode":
                    config["trading"]["mode"].upper()
            },

            "risk": {
                "enabled":
                    config["risk"]["enabled"],

                "max_order_value":
                    config["risk"]["max_order_value"],

                "max_daily_loss":
                    config["risk"]["max_daily_loss"]
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
                "enabled":
                    config["trading"]["enabled"],

                "mode":
                    config["trading"]["mode"].upper()
            }
        }
