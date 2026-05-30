"""Tests for the expire_manual_promos beat task (Fix 3 — manual promo expiry).

The task reverts manually-granted promos back to 'free' once
manual_promo_until passes — but never touches a real Stripe customer.
We use a recording fake users table to assert exactly which rows the
task chose to update, and with what payload.
"""
from datetime import datetime, timedelta, timezone

from tests.conftest import FakeQueryBuilder


def _ts(days_from_now: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days_from_now)).isoformat()


class _RecordingUsers(FakeQueryBuilder):
    """Records update payloads and the eq() filters used to target them,
    so a test can assert which user row was updated and how."""

    def __init__(self, rows):
        super().__init__(data=rows)
        self.update_calls = []          # list of payload dicts
        self.updated_ids = []           # ids targeted by .eq("id", <id>)

    def update(self, vals):
        self.update_calls.append(vals)
        return super().update(vals)

    def eq(self, col, val):
        if col == "id":
            self.updated_ids.append(val)
        return super().eq(col, val)


def _promo_user(*, uid, plan, expires_days, stripe_sub=None):
    return {
        "id": uid,
        "email": f"{uid}@example.com",
        "plan": plan,
        "manual_promo_until": _ts(expires_days),
        "stripe_subscription_id": stripe_sub,
    }


# ── Happy path: expired, non-Stripe, paid → reverted ──


def test_expired_promo_no_stripe_is_reverted_to_free(fake_db):
    from workers import scheduled_worker

    user = _promo_user(uid="u-expired", plan="starter", expires_days=-1)
    users = _RecordingUsers(rows=[user])
    fake_db.set_table("users", users)

    r = scheduled_worker.expire_manual_promos()

    assert r["reverted"] == 1
    assert len(users.update_calls) == 1
    payload = users.update_calls[0]
    assert payload["plan"] == "free"
    assert payload["manual_promo_until"] is None
    assert "u-expired" in users.updated_ids


def test_expired_promo_emits_audit_event(fake_db):
    from workers import scheduled_worker

    user = _promo_user(uid="u-expired", plan="starter", expires_days=-2)
    users = _RecordingUsers(rows=[user])
    fake_db.set_table("users", users)

    emitted = []

    def _fake_emit(event_type, **kwargs):
        emitted.append((event_type, kwargs))

    import models.audit as audit_mod
    orig = audit_mod.emit
    audit_mod.emit = _fake_emit
    try:
        scheduled_worker.expire_manual_promos()
    finally:
        audit_mod.emit = orig

    assert len(emitted) == 1
    event_type, kwargs = emitted[0]
    assert event_type == audit_mod.EVENT_MANUAL_PROMO_EXPIRED
    assert kwargs.get("user_id") == "u-expired"


# ── Guard: real Stripe customer is protected ──


def test_expired_promo_with_stripe_subscription_is_not_reverted(fake_db):
    from workers import scheduled_worker

    user = _promo_user(
        uid="u-paying", plan="starter", expires_days=-5, stripe_sub="sub_123"
    )
    users = _RecordingUsers(rows=[user])
    fake_db.set_table("users", users)

    r = scheduled_worker.expire_manual_promos()

    assert r["reverted"] == 0
    assert users.update_calls == []
    assert "u-paying" not in users.updated_ids


# ── Guard: promo not yet expired ──


def test_not_yet_expired_promo_is_not_reverted(fake_db):
    from workers import scheduled_worker

    user = _promo_user(uid="u-future", plan="starter", expires_days=10)
    users = _RecordingUsers(rows=[user])
    fake_db.set_table("users", users)

    r = scheduled_worker.expire_manual_promos()

    assert r["reverted"] == 0
    assert users.update_calls == []


# ── Guard: already free ──


def test_already_free_user_is_untouched(fake_db):
    from workers import scheduled_worker

    user = _promo_user(uid="u-free", plan="free", expires_days=-3)
    users = _RecordingUsers(rows=[user])
    fake_db.set_table("users", users)

    r = scheduled_worker.expire_manual_promos()

    assert r["reverted"] == 0
    assert users.update_calls == []


# ── Idempotency + mixed batch ──


def test_mixed_batch_reverts_only_eligible(fake_db):
    from workers import scheduled_worker

    rows = [
        _promo_user(uid="revert-me", plan="starter", expires_days=-1),
        _promo_user(uid="paying", plan="pro", expires_days=-1, stripe_sub="sub_x"),
        _promo_user(uid="future", plan="starter", expires_days=5),
        _promo_user(uid="already-free", plan="free", expires_days=-1),
    ]
    users = _RecordingUsers(rows=rows)
    fake_db.set_table("users", users)

    r = scheduled_worker.expire_manual_promos()

    assert r["reverted"] == 1
    assert users.updated_ids == ["revert-me"]


def test_no_promo_rows_is_noop(fake_db):
    from workers import scheduled_worker

    users = _RecordingUsers(rows=[])
    fake_db.set_table("users", users)

    r = scheduled_worker.expire_manual_promos()

    assert r["reverted"] == 0
    assert users.update_calls == []
