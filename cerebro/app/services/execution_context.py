import hashlib


def build_execution_context(*, mode: str, account: dict | None):
    """Return a stable non-secret execution-context identity for one broker account.

    The raw account id is deliberately not exposed in the public decision context.
    A hash over environment + broker + account id lets Cerebro bind a proposal to
    the exact account/environment that generated it and reject later cross-context
    approvals.
    """
    environment = str(mode or "").strip().upper()
    account = account or {}
    account_id = str(account.get("account_id") or "").strip()
    security_firm = str(account.get("security_firm") or "").strip().upper()

    if environment not in {"PAPER", "LIVE"}:
        raise RuntimeError(f"Unsupported execution environment {environment or 'UNKNOWN'}")
    if not account_id:
        raise RuntimeError("Execution account id is unavailable")

    digest_input = f"{environment}|{security_firm}|{account_id}".encode("utf-8")
    digest = hashlib.sha256(digest_input).hexdigest()[:24]
    masked = account.get("account_id_masked") or f"••••{account_id[-4:]}"

    return {
        "environment": environment,
        "context_id": f"{environment.lower()}:{digest}",
        "account_id_masked": masked,
        "security_firm": security_firm or None,
    }
