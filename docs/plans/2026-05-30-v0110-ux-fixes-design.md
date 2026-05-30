# v0.1.10 — UX Fixes (Merge Tag, Failed Contacts, Manual Promo) — Design

> **Date:** 2026-05-30
> **Status:** Approved (brainstorming)
> **Next:** writing-plans → implementation plan
> **Version:** v0.1.10 (extension), Migration 019 (backend)

## Problem

Our first real users hit avoidable friction (see HANDOFF user state):
1. **Abid** ran 8 campaigns; 4 failed because his email body used `{{First Name}}` (space) or `{{FirstName}}` (PascalCase) while the correct tag is `{{firstName}}`. The backend rejected the send with a raw English string the user didn't understand.
2. Two of his campaigns went **partial** — 10-12 contacts stuck in `pending`. The send loop never marks failed contacts, so we can't tell transient (rate-limit) from permanent (bad address) failures, and analytics undercount the problem.
3. We gave Abid a 30-day Starter promo by hand-editing the DB, which requires a manual calendar reminder to revert — error-prone.

## Goals

Three independent fixes shipping together as v0.1.10:

### Fix 1 — Merge Tag UX
Replace raw-string merge-tag validation errors with structured, localized, actionable messages so users understand exactly how to fix a tag mismatch.

### Fix 2 — Failed Contact States
Introduce a 4-state contact model so we distinguish permanent from transient failures, keep Resume working for recoverable contacts, and make analytics accurate.

### Fix 3 — Manual Promo Expiry
Add `users.manual_promo_until` + a daily beat task that auto-reverts expired manual promos (skipping real Stripe subscribers), eliminating manual calendar reminders.

## Non-Goals
- Live merge-tag validation while composing (v0.1.11+).
- Promo-expiry email / conversion nudge (revisit with PostHog data).
- Self-service promo admin UI (SQL is fine for now).
- Hand-classifying every Graph error code beyond the transient/permanent split.

---

## Fix 1 — Merge Tag UX

**Backend** (`routers/campaigns.py`): the two validation sites (`send_campaign` ~line 519-541: malformed + unknown; `test-send` ~line 699: malformed) change their `HTTPException` detail from a raw string to a structured object, following the existing `feature_locked`/`limit_exceeded` pattern that `background.js` already understands:

```python
# unknown tag
detail={
  "error": "unknown_merge_tags",
  "tags": ["FirstName"],
  "field": "body",
  "message": "Unknown merge tags (not in CSV): FirstName"  # English fallback
}
# malformed tag
detail={
  "error": "malformed_merge_tag",
  "tag": "{{First Name}}",
  "field": "subject",
  "message": "Malformed merge tag in subject: {{First Name}}"
}
```

`message` is always a readable English fallback for **backward compat**: an un-upgraded v0.1.8/v0.1.9 client that doesn't recognize the new code can still surface `message`; the new client localizes via the code.

**Frontend** (`sidebar.js`): when `resp.error === "unknown_merge_tags"` / `"malformed_merge_tag"`, show a localized actionable message built from `resp.detail.tags`/`tag`:
- unknown: "Your CSV has no column named 'FirstName'. Either add that column to your CSV, or remove {{FirstName}} from your email. Tip: the standard tag is {{firstName}} (lowercase, no spaces)."
- malformed: "Your email has a broken tag: {{First Name}}. Tags can't contain spaces. The correct form is {{firstName}}."

**i18n:** new keys in all 10 locales (en, tr, de, fr, es, ru, ar, hi, zh_CN, ja), with `{tag}` placeholder substitution.

**Scope:** `send_campaign` + `test-send`. Not `create_campaign` (no validation there; caught at send).

**Testing:** backend unit tests assert the structured detail shape on both error paths. Frontend is manual (alert text per locale).

---

## Fix 2 — Failed Contact States

**Model:** `contacts.status` gains two values (it's `TEXT`, no migration needed):

| status | meaning | Resume includes? | analytics |
|---|---|---|---|
| `pending` | not yet attempted | yes | — |
| `sent` | delivered (202) | — | sent_count |
| `deferred` | transient failure (429/5xx/network/timeout, retries exhausted, address still valid) | yes (retry) | transient |
| `failed` | permanent failure (4xx except 429 — invalid recipient, forbidden) | no | permanent |

**Classification:** `_send_single_email` (`campaigns.py` ~line 1116) adds `status_code` to its failure return: `{"success": False, "error": ..., "status_code": resp.status_code}`. The send loop classifies:
- 4xx except 429 → `failed` (permanent)
- 429 / 5xx / network-or-timeout exception → `deferred` (transient)

`graph_retry.post_with_retry` already retries 429/5xx/network 3×, so reaching this point means the transient condition persisted — still treated as `deferred` (recoverable by a later Resume), not permanent.

**New model fn** `contact.mark_failed(contact_id, status)` where status ∈ {`deferred`, `failed`}. Called in the send-loop error + exception branches (`campaigns.py` ~638-643). Also wired into the other send paths that use `_send_single_email`: `scheduled_worker.py`, `followup_worker.py` (verify and apply the same classification).

**Resume:** `get_pending_contacts` → new `get_resumable_contacts` returning `status IN ('pending','deferred')`. The send loop's contact-fetch and the resume endpoint use it. `failed` contacts are excluded (retrying is futile).

**Analytics:** `send_failed` event gains `failure_type: "permanent" | "transient"` so PostHog shows whether partial sends are bad addresses vs rate limits.

**No `last_error` column** (YAGNI — error detail already lives in `send_failed` event + audit_log).

**Migration:** none (status is free-text TEXT; no existing rows hold the new values).

**Testing:** backend unit tests for `mark_failed`, `get_resumable_contacts`, and the classification (4xx→failed, 429/5xx→deferred) using the FakeSupabase fixture.

---

## Fix 3 — Manual Promo Expiry

**Migration 019:** `ALTER TABLE users ADD COLUMN IF NOT EXISTS manual_promo_until TIMESTAMPTZ;` (nullable, reversible via DROP COLUMN). **Backfill:** set `manual_promo_until = '2026-06-12'` for Abid's row (`abidalibalospura@outlook.com`) so the beat task auto-reverts him — this replaces the manual calendar reminder.

**Beat task** `scheduled_worker.expire_manual_promos` (daily, ~04:45 UTC, after the inactivity tasks):
```sql
UPDATE users SET plan='free', manual_promo_until=NULL
WHERE manual_promo_until IS NOT NULL
  AND manual_promo_until < now()
  AND plan != 'free'
  AND stripe_subscription_id IS NULL   -- never touch a real paying customer
```
Each reverted user gets an `audit_log` entry (`event_type='manual_promo_expired'` or reuse `subscription_canceled` with metadata). No email (Abid's apology mail already told him; conversion nudge revisited later). No feature flag (logic is safe and scoped — only affects rows with `manual_promo_until` set and no Stripe sub).

**Granting a promo** (documented in HANDOFF, manual SQL):
```sql
UPDATE users SET plan='starter', emails_sent_this_month=0,
                 manual_promo_until = now() + interval '30 days'
WHERE email='<user>';
```

**Testing:** backend unit test for `expire_manual_promos` — reverts expired non-Stripe promo, skips expired-but-Stripe-subscribed, skips not-yet-expired, skips already-free.

---

## Rollout & Risk

- **Version:** extension → v0.1.10 (manifest bump). Backend deploy via Railway on push. Migration 019 applied manually by user (like 018).
- **User-impact (CLAUDE.md):**
  - Fix 1: improves an error message — strictly better UX. Backward-compat via `message` fallback. No notification needed.
  - Fix 2: internal state refinement; Resume behavior preserved (still retries recoverable contacts). Invisible to users except more-accurate Reports counts.
  - Fix 3: invisible; only affects manually-promoted users (Abid), reverting as already promised.
- **Reversible:** Migration 019 DROP COLUMN; Fix 2 is additive code; Fix 1 keeps English fallback.
- **Rollback:** revert commits + republish prior ZIP; migration down = drop column.

## Order of Implementation
1. Fix 2 backend (model + classification + tests) — foundational, no UI.
2. Fix 1 backend (structured errors + tests).
3. Fix 1 frontend (i18n, 10 locales).
4. Fix 2 frontend (`send_failed` failure_type prop).
5. Fix 3 (migration 019 + beat task + tests + backfill).
6. Manifest v0.1.10 + CHANGELOG. Self-test. ZIP. Merge.
