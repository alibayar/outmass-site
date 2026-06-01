# Free Tier Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Raise limits — Free 50→250, Starter 2.000→2.500 monthly; upload rows aligned to monthly (Free 250, Starter 2.500, Pro 10.000) — across backend config, frontend display, docs, and store listing, all in sync.

**Architecture (PARAMETRIC — revised):** Make limits changeable WITHOUT code/extension changes.
1. **Backend config env-driven**: each limit = `int(os.getenv("NAME", "<new-default>"))` (same pattern as `INACTIVITY_PAUSE_DAYS`). Change a limit later = set a Railway env var → auto-deploy. No code edit.
2. **Backend exposes the user's limit via API**: add `monthly_limit` + `upload_limit` to `GET /settings` (computed from the user's plan via config helpers). `GET_USER_STATE` already calls `/settings`, so it gets them too.
3. **Frontend reads the limit from the backend** (no more hardcoded ternary): `sidebar.js` uses `result.monthly_limit` with a hardcoded fallback only for safety/offline. So a Railway env change updates enforcement AND display together — no extension update, no Web Store review.

Monthly reset already works (`auth.py:_check_monthly_reset` via `month_reset_date`). This parametric design also eliminates the frontend/backend drift risk (the old hardcoded numbers could lie).

**Tech Stack:** Python/FastAPI, vanilla JS (MV3), pytest, GitHub Pages HTML.

**Design doc:** `docs/plans/2026-06-01-free-tier-redesign-design.md`

**User-impact (CLAUDE.md):** Pure positive — every limit goes UP, nobody loses. Approved in brainstorming. Reversible config (but per asymmetry principle we won't lower). Backward compatible (limits server-side). No mandatory notification; optional "good news."

**New values (single source of truth):**
| Constant | Old | New |
|---|---|---|
| FREE_PLAN_MONTHLY_LIMIT | 50 | **250** |
| STARTER_PLAN_MONTHLY_LIMIT | 2000 | **2500** |
| PRO_PLAN_MONTHLY_LIMIT | 10000 | 10000 (same) |
| FREE_UPLOAD_ROW_LIMIT | 100 | **250** |
| STARTER_UPLOAD_ROW_LIMIT | 2000 | **2500** |
| PRO_UPLOAD_ROW_LIMIT | 5000 | **10000** |

**Test commands:**
- `cd D:/dev/git/outmass/backend && python -m pytest tests/<file> -v`
- `cd D:/dev/git/outmass && npm run test:unit` (baseline 297)
- `node --check extension/sidebar.js`

**Commit trailer (every commit):** `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

---

## PHASE 0 — Baseline

### Task 0.1: Confirm green
`cd D:/dev/git/outmass && npm run test:unit` → expect `297 passed`. If not, STOP.

---

## PHASE 1 — Backend Config + Enforcement (TDD)

### Task 1.1: Make config constants env-driven (parametric)

**Files:** Modify `backend/config.py` (lines ~153-167)

**Step 1:** Convert the six constants to env-driven, with the NEW values as defaults:
```python
# ── Plan Limits (env-overridable — change in Railway, no code/deploy of code) ──
FREE_PLAN_MONTHLY_LIMIT = int(os.getenv("FREE_PLAN_MONTHLY_LIMIT", "250"))
STARTER_PLAN_MONTHLY_LIMIT = int(os.getenv("STARTER_PLAN_MONTHLY_LIMIT", "2500"))
PRO_PLAN_MONTHLY_LIMIT = int(os.getenv("PRO_PLAN_MONTHLY_LIMIT", "10000"))

# Legacy alias (keep for back-compat until all code migrated)
STANDARD_PLAN_MONTHLY_LIMIT = STARTER_PLAN_MONTHLY_LIMIT

AI_GENERATION_MONTHLY_LIMIT = int(os.getenv("AI_GENERATION_MONTHLY_LIMIT", "50"))

FREE_UPLOAD_ROW_LIMIT = int(os.getenv("FREE_UPLOAD_ROW_LIMIT", "250"))
STARTER_UPLOAD_ROW_LIMIT = int(os.getenv("STARTER_UPLOAD_ROW_LIMIT", "2500"))
PRO_UPLOAD_ROW_LIMIT = int(os.getenv("PRO_UPLOAD_ROW_LIMIT", "10000"))
```

**Step 2:** Add two helper functions in `config.py` (after the constants) so plan→limit mapping lives in ONE place (used by the settings API + optionally the enforcement sites):
```python
def monthly_limit_for_plan(plan: str) -> int:
    return {
        "pro": PRO_PLAN_MONTHLY_LIMIT,
        "starter": STARTER_PLAN_MONTHLY_LIMIT,
    }.get(plan, FREE_PLAN_MONTHLY_LIMIT)


def upload_limit_for_plan(plan: str) -> int:
    return {
        "pro": PRO_UPLOAD_ROW_LIMIT,
        "starter": STARTER_UPLOAD_ROW_LIMIT,
    }.get(plan, FREE_UPLOAD_ROW_LIMIT)
```

**Step 2:** Verify enforcement sites read the constants (no hardcoded numbers). Grep:
```bash
cd D:/dev/git/outmass && grep -n "FREE_PLAN_MONTHLY_LIMIT\|STARTER_PLAN_MONTHLY_LIMIT\|PRO_PLAN_MONTHLY_LIMIT\|FREE_UPLOAD_ROW_LIMIT\|STARTER_UPLOAD_ROW_LIMIT\|PRO_UPLOAD_ROW_LIMIT" backend/routers/campaigns.py backend/workers/scheduled_worker.py backend/routers/billing.py
```
Read each match — confirm they use the constant, not a literal. If any site hardcodes 50/2000/100/5000, note it (shouldn't happen, but verify).

**Step 3:** Commit:
```bash
git add backend/config.py
git commit -m "feat(billing): raise free 50->250, starter 2000->2500, align upload limits"
```

### Task 1.2: Update / add backend tests for the new limits (TDD)

**Files:** Test — find existing tests that assert limits.

**Step 1:** Find tests hardcoding old limits:
```bash
cd D:/dev/git/outmass && grep -rn "\b50\b\|\b2000\b\|\b100\b\|\b5000\b\|limit_exceeded\|FREE_PLAN_MONTHLY" backend/tests/ | grep -iv "status_code\|http\|sleep\|timeout\|port\|width\|1000\b"
```
Look especially in `test_billing.py`, `test_campaigns_validation.py`, `test_contact_validation.py` (upload row limit), and any send-quota test.

**Step 2:** For each test asserting the OLD limit (e.g. "free user blocked at 50", "upload >100 rejected"), update the expected number to the new limit (250 / 2500 / 10000). If a test sends 100 contacts expecting rejection on free, it now must use >250 to trigger rejection. Read each carefully — adjust the test's input AND expected boundary.

**Step 3:** Add one explicit regression test (in the most relevant existing test file, e.g. `test_billing.py` or a new `test_plan_limits.py`) asserting the config values directly:
```python
def test_plan_limits_are_current():
    from config import (
        FREE_PLAN_MONTHLY_LIMIT, STARTER_PLAN_MONTHLY_LIMIT, PRO_PLAN_MONTHLY_LIMIT,
        FREE_UPLOAD_ROW_LIMIT, STARTER_UPLOAD_ROW_LIMIT, PRO_UPLOAD_ROW_LIMIT,
    )
    assert FREE_PLAN_MONTHLY_LIMIT == 250
    assert STARTER_PLAN_MONTHLY_LIMIT == 2500
    assert PRO_PLAN_MONTHLY_LIMIT == 10000
    assert FREE_UPLOAD_ROW_LIMIT == 250
    assert STARTER_UPLOAD_ROW_LIMIT == 2500
    assert PRO_UPLOAD_ROW_LIMIT == 10000
```
This is a guard so the numbers can't silently drift.

**Step 4:** Run full suite:
```bash
cd D:/dev/git/outmass && npm run test:unit
```
Expect all green (297 + your new test, minus none). Fix any test that still expects an old boundary.

**Step 5:** Commit:
```bash
git add backend/tests/
git commit -m "test(billing): update plan-limit assertions to new values + guard test"
```

---

## PHASE 1.5 — Expose limit via API (parametric)

### Task 1.5: Add monthly_limit + upload_limit to GET /settings

**Files:** Modify `backend/routers/settings.py` (the `get_settings` return, ~line 40-57); Test: `backend/tests/test_settings.py`

**Step 1 (TDD):** Add/extend a test asserting `GET /settings` returns `monthly_limit` matching the user's plan:
```python
def test_settings_returns_monthly_limit_for_plan(client, fake_db, auth_bypass):
    # auth_bypass user is free by default → 250
    resp = client.get("/settings", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["monthly_limit"] == 250
    assert body["upload_limit"] == 250
```
(If `auth_bypass` is a paid plan, adjust expected value. Check the fixture.)

**Step 2:** Run → FAIL (keys missing).

**Step 3:** Import the helpers and add the two fields to the `get_settings` return dict:
```python
from config import monthly_limit_for_plan, upload_limit_for_plan
...
    plan = user.get("plan", "free")
    return {
        ...
        "plan": plan,
        "emails_sent_this_month": user.get("emails_sent_this_month", 0),
        "monthly_limit": monthly_limit_for_plan(plan),
        "upload_limit": upload_limit_for_plan(plan),
        ...
    }
```

**Step 4:** Run → PASS. Full suite green.

**Step 5:** Commit:
```bash
git add backend/routers/settings.py backend/tests/test_settings.py
git commit -m "feat(settings): expose monthly_limit + upload_limit (plan-derived)"
```

---

## PHASE 2 — Frontend Display (read limit from backend)

### Task 2.1: sidebar.js reads monthly_limit from backend

**Files:** Modify `extension/sidebar.js` (lines ~641 and ~719)

**Step 1:** Both lines currently hardcode:
```js
var limit = plan === "pro" ? 10000 : plan === "starter" ? 2000 : 50;
```
Replace BOTH with: read the backend-provided value, fall back to the hardcoded ternary only if absent (offline/old backend):
```js
var limit = result.monthly_limit || (plan === "pro" ? 10000 : plan === "starter" ? 2500 : 250);
```
(At line ~719 the variable holding the response may be named differently — check; it's the object that already has `.plan`. Use that object's `.monthly_limit`.)

**Step 2:** Verify both sites:
```bash
cd D:/dev/git/outmass && grep -n "monthly_limit\|plan === \"pro\"" extension/sidebar.js
```
Both quota sites should now prefer `monthly_limit`. The fallback ternary updated to 2500/250 (so even offline it's not stale).

**Step 3:** `node --check extension/sidebar.js` → OK.

**Step 4:** Commit:
```bash
git add extension/sidebar.js
git commit -m "feat(ext): sidebar quota reads backend monthly_limit (parametric, fallback 250/2500)"
```

### Task 2.2: Check popup.js + any other frontend limit display

**Files:** Inspect `extension/popup.js`, `extension/popup.html`

**Step 1:** Grep for limit numbers in popup + any other extension JS:
```bash
cd D:/dev/git/outmass && grep -rn "\b50\b\|\b2000\b\|10000" extension/popup.js extension/popup.html extension/content_script.js
```
**Step 2:** If popup shows a numeric limit anywhere, update it to the new values. If it only shows the plan name (Free/Starter/Pro badge) with no number, no change needed — note that.

**Step 3:** Commit if changed:
```bash
git add extension/popup.js extension/popup.html
git commit -m "feat(ext): popup plan-limit display updated"
```
(Skip commit if nothing changed.)

---

## PHASE 3 — i18n Quota Messages

### Task 3.1: Update any quota message with a hardcoded number

**Files:** `extension/_locales/*/messages.json`

**Step 1:** Find quota-related i18n keys with numbers:
```bash
cd D:/dev/git/outmass && grep -n "50\|2000\|100" extension/_locales/en/messages.json | grep -i "limit\|quota\|email\|month\|upgrade\|plan"
```
Also check the backend `limit_exceeded` message in `campaigns.py` (~line 569 `"Aylik {limit} email limitine ulastiniz"` — that one interpolates `{limit}` dynamically, so it's fine; verify it uses the variable, not a literal).

**Step 2:** For any i18n message that hardcodes "50 emails/month" or "2000", update the number across all 10 locales (en, tr, de, fr, es, ru, ar, hi, zh_CN, ja). If quota messages use a `$1`/placeholder for the number (dynamic), no change needed — confirm.

**Step 3:** Validate all 10 locales parse:
```bash
cd D:/dev/git/outmass && node -e "['en','tr','de','fr','es','ru','ar','hi','zh_CN','ja'].forEach(l=>JSON.parse(require('fs').readFileSync('extension/_locales/'+l+'/messages.json','utf8'))); console.log('all OK')"
```

**Step 4:** Commit if changed:
```bash
git add extension/_locales
git commit -m "i18n: update quota messages to new limits"
```
(Skip if all quota messages are dynamic/placeholder-based.)

---

## PHASE 4 — Public Docs + Store Listing

### Task 4.1: Update pricing page

**Files:** `docs/pricing.html` (+ check `docs/index.html`, `docs/launch.html` for limit mentions)

**Step 1:** Grep for the old numbers:
```bash
cd D:/dev/git/outmass && grep -rn "50 email\|50 mail\|2,000\|2000\|10,000\|10000\|100 " docs/pricing.html docs/index.html docs/launch.html
```
**Step 2:** Update every customer-facing limit: free "50/month" → "250/month", starter "2,000" → "2,500", upload mentions if any. Keep wording/format consistent with the page.

**Step 3:** Commit:
```bash
git add docs/pricing.html docs/index.html docs/launch.html
git commit -m "docs(pricing): update free/starter limits (250/2500)"
```

### Task 4.2: Update store listing

**Files:** `docs/store-listing/listings.json`

**Step 1:** Grep:
```bash
cd D:/dev/git/outmass && grep -n "50\|2000\|2,000" docs/store-listing/listings.json
```
**Step 2:** If any feature bullet mentions the free limit ("50 free emails/month"), update to 250 across all locales present in the file. If the listing doesn't mention a number, no change.

**Step 3:** Commit if changed:
```bash
git add docs/store-listing/listings.json
git commit -m "docs(listings): update free limit mention to 250"
```

---

## PHASE 5 — Ship

### Task 5.1: Manifest bump + CHANGELOG

**Files:** `extension/manifest.json`, `extension/CHANGELOG.md`

**Step 1:** Bump `"version": "0.1.10"` → `"0.1.11"`. Verify JSON parses.

**Step 2:** CHANGELOG entry (user-friendly, frame as improvement):
```markdown
## v0.1.11 — 2026-06-01

- More generous free plan: 250 emails/month (was 50). Starter raised to 2,500/month. Upload limits raised to match. Enjoy!
```

**Step 3:** Commit:
```bash
git add extension/manifest.json extension/CHANGELOG.md
git commit -m "chore(ext): v0.1.11 manifest + changelog (free tier raise)"
```

### Task 5.2: Full verification + ship

**Step 1:** `cd D:/dev/git/outmass && npm run test:all 2>&1 | tail` (unit + E2E). If E2E quota screenshots shifted and the change is correct, regenerate baselines deliberately; otherwise investigate.
**Step 2:** `node --check extension/sidebar.js && node --check extension/popup.js && node --check extension/background.js`.
**Step 3:** Build ZIP:
```powershell
cd D:/dev/git/outmass/extension; Compress-Archive -Path * -DestinationPath ../outmass-v0.1.11.zip -Force; cd ..
```
**Step 4:** Report: SHAs, test counts, ZIP path, which files actually changed (popup/i18n/listing may have been no-ops). Backend config → deploys on push (limits live immediately). Docs → GitHub Pages. Extension → Web Store upload.

---

## Done

Free 250 / Starter 2.500, upload aligned, synced across backend + frontend + docs + listing. Limits live server-side on push; extension display + pricing page catch up. All UP, no breakage. Optional: mention the bigger free plan in the Abdul outreach.
