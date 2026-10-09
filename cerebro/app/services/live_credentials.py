import os


def configured_unlock_hash():
    """Return the optional server-side Moomoo trade-unlock MD5 value.

    The value is supplied by the container environment and never persisted in
    Cerebro's database or exposed by an API response.
    """
    value = os.getenv("MOOMOO_TRADING_PASSWORD_MD5", "").strip()
    return value or None
