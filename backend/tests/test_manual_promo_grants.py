"""Manual promo grants (migration 026): the gift has to undo itself exactly.

Granting a promo is DESTRUCTIVE — it clears users.stripe_subscription_id,
because expire_manual_promos skips anyone carrying one and the promo would
otherwise never end. The grant record is the only copy of that value. These
tests exist because "we'll write it down and put it back later" is the part
that does not happen on its own.

What each test pins:
  * the stashed subscription id comes back
  * the plan restored is the one recorded, not a hardcoded 'free'
  * a user who really subscribes mid-promo is never downgraded
  * rows granted before 026 keep behaving exactly as before
  * a grants-table failure still lets the promo expire
  * a stale Stripe cancellation cannot revoke a promo we promised in writing
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from tests.conftest import FakeQueryBuilder


def _ts(days_from_now: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days_from_now)).isoformat()


class _RecordingUsers(FakeQueryBuilder):
    """Users table that honours .eq() on reads and mutates rows in place.

    The stock builder lets update() replace the whole row set, which stopped
    being harmless once the task re-reads each row before writing it: the
    second user's re-read would return the FIRST user's update payload, and
    a test asserting "each user kept their own subscription id" would pass
    against code that mixed two customers up.
    """

    def __init__(self, rows):
        super().__init__(data=rows)
        self.rows = [dict(r) for r in rows]
        self.update_calls = []
        self.updated_ids = []
        self._filters = {}
        self._pending = None

    def select(self, *a, **kw):
        self._filters = {}
        self._pending = None
        return self

    def update(self, vals):
        self._filters = {}
        self._pending = dict(vals)
        self.update_calls.append(dict(vals))
        return self

    def eq(self, col, val):
        self._filters[col] = val
        if col == "id" and self._pending is not None:
            self.updated_ids.append(val)
        return self

    def limit(self, *a):
        return self

    def is_(self, *a):
        return self

    @property
    def not_(self):
        return self

    def execute(self):
        matched = [
            r for r in self.rows
            if all(r.get(k) == v for k, v in self._filters.items())
        ]
        if self._pending is not None:
            for r in matched:
                r.update(self._pending)
            self._pending = None
        return MagicMock(data=matched)


class _FakeGrants(FakeQueryBuilder):
    """A grants table that actually honours .eq() filters.

    The stock FakeQueryBuilder ignores filters and lets update() overwrite
    the row set, which would be actively misleading here: the task selects
    one user's grant and then updates it, so an unfiltered fake would hand
    the NEXT user the payload it just wrote for the previous one — and the
    test would pass while the code mixed up two customers' subscriptions.
    """

    def __init__(self, rows=None):
        super().__init__(data=list(rows or []))
        self.rows = [dict(r) for r in (rows or [])]
        self.update_calls = []
        self._filters = {}
        self._pending_update = None

    def select(self, *a, **kw):
        self._filters = {}
        self._pending_update = None
        return self

    def update(self, vals):
        self._filters = {}
        self._pending_update = dict(vals)
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, *a):
        return self

    def execute(self):
        matched = [
            r for r in self.rows
            if all(r.get(k) == v for k, v in self._filters.items())
        ]
        if self._pending_update is not None:
            for r in matched:
                r.update(self._pending_update)
            self.update_calls.append(
                (dict(self._filters), dict(self._pending_update))
            )
            self._pending_update = None
        return MagicMock(data=matched)


def _user(*, uid, plan, expires_days, stripe_sub=None):
    return {
        "id": uid,
        "email": f"{uid}@example.com",
        "plan": plan,
        "manual_promo_until": _ts(expires_days),
        "stripe_subscription_id": stripe_sub,
    }


def _grant(*, uid, granted="starter", previous="free", stashed=None, status="active"):
    return {
        "id": f"g-{uid}",
        "user_id": uid,
        "granted_plan": granted,
        "previous_plan": previous,
        "previous_stripe_subscription_id": stashed,
        "expires_at": _ts(-1),
        "status": status,
    }


# ── The core promise: what the grant took, expiry gives back ──


def test_stashed_id_is_kept_in_the_grant_and_NOT_written_back(fake_db):
    """The stash preserves the id; the user row must not get it back.

    users.stripe_subscription_id means "this user's CURRENT subscription",
    and grant_manual_promo refuses to run over a live one — so every stashed
    id is one an operator confirmed dead. Writing it back would put a false
    value into a field six readers trust, the worst of them account.py:122,
    which blocks account deletion on (paid plan AND a subscription id): a
    user could be told to cancel a subscription that does not exist before
    they may delete their own account.
    """
    from workers import scheduled_worker

    users = _RecordingUsers(rows=[_user(uid="u1", plan="starter", expires_days=-1)])
    grants = _FakeGrants([_grant(uid="u1", stashed="sub_dead_123")])
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", grants)

    r = scheduled_worker.expire_manual_promos()

    assert r["reverted"] == 1
    payload = users.update_calls[0]
    assert "stripe_subscription_id" not in payload, (
        "a dead subscription id was written back onto the live user row"
    )
    assert payload["plan"] == "free"
    assert payload["manual_promo_until"] is None
    assert grants.rows[0]["status"] == "restored"
    # Preserved, which was the whole point of the table.
    assert grants.rows[0]["previous_stripe_subscription_id"] == "sub_dead_123"


def test_expiry_restores_the_recorded_plan_not_hardcoded_free(fake_db):
    """A promo granted to someone already on a paid plan must not demote
    them. Before 026 the task wrote 'free' unconditionally."""
    from workers import scheduled_worker

    users = _RecordingUsers(rows=[_user(uid="u2", plan="pro", expires_days=-1)])
    grants = _FakeGrants(
        [_grant(uid="u2", granted="pro", previous="starter", stashed="sub_live")]
    )
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", grants)

    scheduled_worker.expire_manual_promos()

    assert users.update_calls[0]["plan"] == "starter"


def test_expiry_never_writes_the_subscription_column_at_all(fake_db):
    """Whether or not anything was stashed, the column is left alone. The
    promo cleared it and it stays cleared; the archive is the grant row."""
    from workers import scheduled_worker

    users = _RecordingUsers(rows=[_user(uid="u3", plan="starter", expires_days=-1)])
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", _FakeGrants([_grant(uid="u3")]))

    scheduled_worker.expire_manual_promos()

    assert "stripe_subscription_id" not in users.update_calls[0]


# ── Never downgrade someone who is actually paying ──


def test_real_resubscriber_is_left_alone_and_grant_superseded(fake_db):
    """A grant clears the column, so a value here was written afterwards —
    by a genuine new subscription. Their plan is theirs."""
    from workers import scheduled_worker

    users = _RecordingUsers(
        rows=[_user(uid="u4", plan="pro", expires_days=-1, stripe_sub="sub_new")]
    )
    grants = _FakeGrants([_grant(uid="u4", stashed="sub_old")])
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", grants)

    r = scheduled_worker.expire_manual_promos()

    assert r["reverted"] == 0
    assert r["superseded"] == 1
    assert grants.rows[0]["status"] == "superseded"
    # Plan untouched; only the stale marker is cleared.
    assert users.update_calls == [{"manual_promo_until": None}]


def test_running_promo_is_not_touched_at_all(fake_db):
    """Expiry must be the FIRST gate — nothing, including closing out a
    grant record, may act on a promo that is still running."""
    from workers import scheduled_worker

    users = _RecordingUsers(rows=[_user(uid="u5", plan="starter", expires_days=+30)])
    grants = _FakeGrants([_grant(uid="u5", stashed="sub_x")])
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", grants)

    r = scheduled_worker.expire_manual_promos()

    assert r["reverted"] == 0 and r["superseded"] == 0
    assert users.update_calls == []
    assert grants.rows[0]["status"] == "active"


# ── Rows that predate 026 ──


def test_legacy_row_without_grant_keeps_old_behaviour(fake_db):
    """Migration 019 backfilled a promo with no grant record. It must still
    expire, with exactly the payload it was granted under."""
    from workers import scheduled_worker

    users = _RecordingUsers(rows=[_user(uid="u6", plan="starter", expires_days=-1)])
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", _FakeGrants([]))

    r = scheduled_worker.expire_manual_promos()

    assert r["reverted"] == 1
    assert users.update_calls[0] == {"plan": "free", "manual_promo_until": None}


def test_grant_lookup_failure_still_expires_the_promo(fake_db):
    """A bookkeeping outage must not strand a user on a plan they were
    given for a fixed window. Falling back to 'free' is the pre-026
    behaviour, which is the safe direction."""
    from workers import scheduled_worker

    class _Exploding(FakeQueryBuilder):
        def execute(self):
            raise RuntimeError("grants table unavailable")

    users = _RecordingUsers(rows=[_user(uid="u7", plan="starter", expires_days=-1)])
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", _Exploding())

    r = scheduled_worker.expire_manual_promos()

    assert r["reverted"] == 1
    assert users.update_calls[0]["plan"] == "free"


def test_two_users_do_not_get_each_others_restore_targets(fake_db):
    """The failure mode the filtered fake exists to catch: one user's grant
    must never decide another user's plan."""
    from workers import scheduled_worker

    users = _RecordingUsers(rows=[
        _user(uid="ua", plan="pro", expires_days=-1),
        _user(uid="ub", plan="pro", expires_days=-1),
    ])
    grants = _FakeGrants([
        _grant(uid="ua", granted="pro", previous="starter", stashed="sub_A"),
        _grant(uid="ub", granted="pro", previous="free", stashed="sub_B"),
    ])
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", grants)

    scheduled_worker.expire_manual_promos()

    by_id = dict(zip(users.updated_ids, users.update_calls))
    assert by_id["ua"]["plan"] == "starter"
    assert by_id["ub"]["plan"] == "free"
    # And each stash stayed with its own grant.
    stashes = {g["user_id"]: g["previous_stripe_subscription_id"] for g in grants.rows}
    assert stashes == {"ua": "sub_A", "ub": "sub_B"}


def test_checkout_landing_mid_batch_is_not_overwritten(fake_db):
    """The stale-snapshot race, made concrete.

    The candidate SELECT takes one snapshot of up to 500 rows; the loop then
    makes several round-trips per row. A user whose promo expires today can
    complete a Stripe checkout while the beat is partway through the batch.
    Here the snapshot says NULL and the live row says 'sub_just_bought' —
    the code must believe the live row, or it downgrades someone moments
    after they paid.
    """
    from workers import scheduled_worker

    class _StaleSnapshotUsers(_RecordingUsers):
        """Serves the batch SELECT from a snapshot, then applies a change.

        The first version of this test simply mutated the row before the
        run, so the batch SELECT and the re-read returned the SAME new
        value — it passed against code that never re-read anything at all.
        Mutation testing caught that. The staleness has to be real: the
        broad SELECT must return the OLD row, and only afterwards does the
        checkout land.
        """

        def __init__(self, rows, lands_after_snapshot):
            super().__init__(rows)
            self._later = lands_after_snapshot
            self._snapshot_served = False

        def execute(self):
            broad_read = not self._filters and self._pending is None
            if broad_read and not self._snapshot_served:
                self._snapshot_served = True
                stale = [dict(r) for r in self.rows]
                for r in self.rows:
                    r.update(self._later)   # the checkout webhook writes now
                return MagicMock(data=stale)
            return super().execute()

    users = _StaleSnapshotUsers(
        rows=[_user(uid="uc", plan="starter", expires_days=-1)],
        lands_after_snapshot={"stripe_subscription_id": "sub_just_bought",
                              "plan": "pro"},
    )
    grants = _FakeGrants([_grant(uid="uc", stashed="sub_dead")])
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", grants)

    r = scheduled_worker.expire_manual_promos()

    assert r["reverted"] == 0
    assert r["superseded"] == 1
    assert users.rows[0]["plan"] == "pro", "a just-paid customer was downgraded"
    assert not any("plan" in c for c in users.update_calls)


def test_orphaned_grant_is_closed_by_the_sweep(fake_db):
    """The retry the candidate query cannot provide.

    Expiry is two writes and they are not atomic. If the grant close-out
    failed on an earlier run, users.manual_promo_until is already NULL, so
    that user never appears as a candidate again — and the stranded 'active'
    grant blocks the partial unique index from ever accepting another gift
    for that customer.
    """
    from workers import scheduled_worker

    users = _RecordingUsers(rows=[{
        "id": "uo", "email": "uo@example.com", "plan": "free",
        "manual_promo_until": None, "stripe_subscription_id": None,
    }])
    grants = _FakeGrants([_grant(uid="uo", stashed="sub_old")])
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", grants)

    r = scheduled_worker.expire_manual_promos()

    assert r["orphans_closed"] == 1
    assert grants.rows[0]["status"] == "restored"


def test_sweep_leaves_a_running_grant_alone(fake_db):
    from workers import scheduled_worker

    users = _RecordingUsers(rows=[{
        "id": "ur", "email": "ur@example.com", "plan": "starter",
        "manual_promo_until": _ts(+30), "stripe_subscription_id": None,
    }])
    running = _grant(uid="ur")
    running["expires_at"] = _ts(+30)
    grants = _FakeGrants([running])
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", grants)

    r = scheduled_worker.expire_manual_promos()

    assert r["orphans_closed"] == 0
    assert grants.rows[0]["status"] == "active"


def test_supersede_clears_the_marker_before_closing_the_grant(fake_db):
    """Order decides whether a half-failure can heal.

    Marker first: if it fails the grant stays 'active' and the row stays a
    candidate, so tomorrow retries. Grant first: the grant is closed, the
    lookup returns None on every later run, and the retry never happens.
    """
    from workers import scheduled_worker

    class _MarkerFails(_RecordingUsers):
        def execute(self):
            if self._pending is not None:
                self._pending = None
                raise RuntimeError("users write failed")
            return super().execute()

    users = _MarkerFails(rows=[
        _user(uid="us", plan="pro", expires_days=-1, stripe_sub="sub_real")
    ])
    grants = _FakeGrants([_grant(uid="us", stashed="sub_old")])
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", grants)

    r = scheduled_worker.expire_manual_promos()

    assert r["superseded"] == 0
    assert grants.rows[0]["status"] == "active", (
        "the grant was closed even though the marker write failed — nothing "
        "will ever retry it"
    )


# ── The webhook shield ──


def test_promo_shield_sees_a_running_promo(fake_db):
    from routers import billing

    fake_db.set_table("users", FakeQueryBuilder(data=[{
        "id": "u8", "email": "u8@example.com",
        "plan": "starter", "manual_promo_until": _ts(+30),
    }]))

    assert billing._promo_shield(fake_db, "cus_1")["id"] == "u8"


def test_promo_shield_ignores_an_expired_promo(fake_db):
    from routers import billing

    fake_db.set_table("users", FakeQueryBuilder(data=[{
        "id": "u9", "email": "u9@example.com",
        "plan": "starter", "manual_promo_until": _ts(-1),
    }]))

    assert billing._promo_shield(fake_db, "cus_1") is None


def test_promo_shield_stands_down_for_a_new_real_subscription(fake_db):
    """The gap the first version of the shield had.

    A grant clears stripe_subscription_id and grant_manual_promo refuses to
    run while a live one exists, so a value here can only mean the user
    subscribed for real DURING the promo. When that new subscription then
    fails, the shield must NOT protect them: otherwise they keep a paid tier
    for free and the dead id gets counted as revenue — the very bug this
    mechanism exists to remove, re-entering through the front door.
    """
    from routers import billing

    fake_db.set_table("users", FakeQueryBuilder(data=[{
        "id": "u8b", "email": "u8b@example.com", "plan": "pro",
        "manual_promo_until": _ts(+30),
        "stripe_subscription_id": "sub_bought_during_promo",
    }]))

    assert billing._promo_shield(fake_db, "cus_1") is None


def test_promo_shield_ignores_a_user_without_a_promo(fake_db):
    from routers import billing

    fake_db.set_table("users", FakeQueryBuilder(data=[{
        "id": "u10", "email": "u10@example.com",
        "plan": "pro", "manual_promo_until": None,
    }]))

    assert billing._promo_shield(fake_db, "cus_1") is None


def test_promo_shield_fails_open(fake_db):
    """When we cannot tell, normal billing behaviour wins. A downgrade that
    should not have happened is recoverable; one that silently did not is
    a paying-tier plan handed out for free."""
    from routers import billing

    class _Exploding(FakeQueryBuilder):
        def execute(self):
            raise RuntimeError("db down")

    fake_db.set_table("users", _Exploding())

    assert billing._promo_shield(fake_db, "cus_1") is None


def test_promo_shield_handles_no_customer_id(fake_db):
    from routers import billing

    assert billing._promo_shield(fake_db, "") is None


def test_retarget_points_the_active_grant_at_free(fake_db):
    """Their subscription died mid-promo: they keep the gift, but what they
    return to afterwards is no longer a plan they pay for."""
    from routers import billing

    grants = _FakeGrants([_grant(uid="u11", previous="pro", stashed="sub_z")])
    fake_db.set_table("manual_promo_grants", grants)

    billing._retarget_grant_to_free(fake_db, "u11")

    assert grants.rows[0]["previous_plan"] == "free"
    filters, payload = grants.update_calls[0]
    # Must be scoped to the ACTIVE grant — retargeting a restored one would
    # rewrite history for a promo that already ended.
    assert filters == {"user_id": "u11", "status": "active"}
    assert payload == {"previous_plan": "free"}


def test_shielded_cancellation_does_not_downgrade(fake_db):
    """The promise was "two months, already active". A cancellation for the
    subscription that died BEFORE the promo must not revoke it."""
    from fastapi.testclient import TestClient

    from main import app
    from routers import billing

    users = _RecordingUsers(rows=[{
        "id": "u12", "email": "u12@example.com", "stripe_customer_id": "cus_12",
        "plan": "starter", "manual_promo_until": _ts(+45),
        "stripe_subscription_id": None,
    }])
    grants = _FakeGrants([_grant(uid="u12", previous="starter")])
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", grants)

    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {"customer": "cus_12", "status": "canceled"}},
    }
    with patch("routers.billing.stripe.Webhook.construct_event", return_value=event), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"):
        resp = TestClient(app).post(
            "/billing/webhook", content=b"{}",
            headers={"stripe-signature": "sig"},
        )

    assert resp.status_code == 200
    assert not any("plan" in c for c in users.update_calls), (
        "a manual promo was revoked by a stale Stripe cancellation"
    )
    assert grants.rows[0]["previous_plan"] == "free"


def test_unshielded_cancellation_still_downgrades(fake_db):
    """The shield must not become a hole: no promo, normal downgrade."""
    from fastapi.testclient import TestClient

    from main import app

    users = _RecordingUsers(rows=[{
        "id": "u13", "email": "u13@example.com",
        "plan": "pro", "manual_promo_until": None,
    }])
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", _FakeGrants([]))

    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {"customer": "cus_13", "status": "canceled"}},
    }
    with patch("routers.billing.stripe.Webhook.construct_event", return_value=event), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"):
        resp = TestClient(app).post(
            "/billing/webhook", content=b"{}",
            headers={"stripe-signature": "sig"},
        )

    assert resp.status_code == 200
    assert any(c.get("plan") == "free" for c in users.update_calls)


def test_shield_does_not_block_a_real_new_subscription(fake_db):
    """'active' must never be shielded — a promo user who genuinely
    subscribes has to land on the plan they are paying for."""
    from fastapi.testclient import TestClient

    from main import app

    users = _RecordingUsers(rows=[{
        "id": "u14", "email": "u14@example.com",
        "plan": "starter", "manual_promo_until": _ts(+45),
    }])
    fake_db.set_table("users", users)
    fake_db.set_table("manual_promo_grants", _FakeGrants([_grant(uid="u14")]))

    event = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "customer": "cus_14",
                "status": "active",
                "items": {"data": [{"price": {"id": "price_pro"}}]},
            }
        },
    }
    with patch("routers.billing.stripe.Webhook.construct_event", return_value=event), \
         patch("routers.billing.STRIPE_WEBHOOK_SECRET", "whsec_test"):
        resp = TestClient(app).post(
            "/billing/webhook", content=b"{}",
            headers={"stripe-signature": "sig"},
        )

    assert resp.status_code == 200
    assert any(c.get("plan") in ("pro", "starter") for c in users.update_calls)
