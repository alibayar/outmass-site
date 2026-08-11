"""Refuse to let a test Stripe key run quietly against the real database.

On 2026-04-17 a checkout ran with TEST Stripe keys while SUPABASE_URL pointed
at production. It wrote a customer id and a subscription id onto
outmass.review@outlook.com that exist in no live Stripe account. Nothing
failed, nobody was charged, and nobody noticed — for nearly four months the
row was counted as a paying Pro subscriber by daily_report, which defines a
real payer as "paid plan + a non-null stripe_subscription_id". It surfaced
on 2026-08-11 only because an unrelated investigation happened to read that
table.

The same class reappeared the night before: the Railway WORKER service was
still carrying TEST values for STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET
alongside a production database. Twice is a pattern, and both times the
signal was silence.

So this is a startup check, not a runtime one. It only observes: it logs and
pings the operator, and never refuses to boot. A Stripe misconfiguration
must not be able to take down sign-in and sending, which have nothing to do
with billing — the cost of this bug is that it goes unnoticed, not that it
happens fast.

Both directions are wrong and both are checked:

  * TEST key + production database — writes fictional billing state into
    real rows. This is what happened.
  * LIVE key + throwaway database — charges real cards against data nobody
    intends to keep. Rarer, and worse.
"""
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Hosts that are definitely NOT production. Anything not listed here counts
# as production, deliberately: an unrecognised host should raise a false
# alarm rather than wave a real misconfiguration through. The failure this
# guards against is silence, so bias toward noise.
_NON_PRODUCTION_DB_HOSTS = frozenset({
    "fake.supabase.co",
    "test.supabase.co",
    "example.com",
    "localhost",
    "127.0.0.1",
})


def _db_looks_production(supabase_url: str) -> bool:
    host = (urlparse(supabase_url or "").hostname or "").lower()
    if not host:
        return False
    return host not in _NON_PRODUCTION_DB_HOSTS


def _stripe_mode(secret_key: str) -> str | None:
    """'test', 'live', or None when unset/unrecognised.

    Restricted keys (rk_) carry the same marker and the same hazard, so they
    are read the same way. None means "cannot tell" — an unconfigured
    service is not a misconfiguration, and guessing would make every worker
    that does not touch Stripe emit an alert.
    """
    key = secret_key or ""
    for prefix, mode in (("sk_test_", "test"), ("rk_test_", "test"),
                         ("sk_live_", "live"), ("rk_live_", "live")):
        if key.startswith(prefix):
            return mode
    return None


def stripe_mode_mismatch(secret_key: str, supabase_url: str) -> str | None:
    """The message to raise, or None when the pairing is coherent."""
    mode = _stripe_mode(secret_key)
    if mode is None:
        return None
    production_db = _db_looks_production(supabase_url)

    if mode == "test" and production_db:
        return (
            "STRIPE_SECRET_KEY is a TEST key but SUPABASE_URL points at the "
            "production database. Checkouts will write customer and "
            "subscription ids that exist in no live Stripe account, and "
            "daily_report will count those rows as paying subscribers. This "
            "is what happened on 2026-04-17."
        )
    if mode == "live" and not production_db:
        return (
            "STRIPE_SECRET_KEY is a LIVE key but SUPABASE_URL is not a "
            "production database. Real cards can be charged against data "
            "nobody intends to keep."
        )
    return None


def check_stripe_mode(secret_key: str, supabase_url: str) -> str | None:
    """Run the check and report it. Returns the message so callers can test
    it; reporting is a side effect, never an exception."""
    message = stripe_mode_mismatch(secret_key, supabase_url)
    if not message:
        return None

    logger.error("CONFIG MISMATCH — %s", message)
    try:
        # Lazy, and inside its own try: an alerting failure must not be able
        # to break startup. _telegram_alert already degrades to an error log
        # when the token is missing, which is what happens on a dev machine.
        from routers.billing import _telegram_alert

        _telegram_alert("🚨 OutMass CONFIG MISMATCH\n\n" + message)
    except Exception:  # noqa: BLE001
        logger.exception("Could not deliver the config-mismatch alert")
    return message


def run_startup_checks() -> None:
    """Called once from main.py at import. Kept separate from the pure
    functions above so tests can drive the logic without importing the app."""
    from config import STRIPE_SECRET_KEY, SUPABASE_URL

    check_stripe_mode(STRIPE_SECRET_KEY, SUPABASE_URL)
