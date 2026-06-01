# Free Tier Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Raise limits — Free 50→250, Starter 2.000→2.500 monthly; upload rows aligned to monthly (Free 250, Starter 2.500, Pro 10.000) — across backend config, frontend display, docs, and store listing, all in sync.

**Architecture:** Backend limits are config-driven (`backend/config.py` constants, read by the send/upload gates) — change the constants, enforcement follows. Frontend has DUPLICATED hardcoded numbers (sidebar.js) that must be updated by hand or the UI lies. Docs/pricing + store listing also state the numbers. Monthly reset already works (`auth.py:_check_monthly_reset` via `month_reset_date`).

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

### Task 1.1: Update config constants

**Files:** Modify `backend/config.py` (lines ~154-167)

**Step 1:** Change the six constants to the new values:
```python
FREE_PLAN_MONTHLY_LIMIT = 250
STARTER_PLAN_MONTHLY_LIMIT = 2500
PRO_PLAN_MONTHLY_LIMIT = 10000
# STANDARD_PLAN_MONTHLY_LIMIT = STARTER_PLAN_MONTHLY_LIMIT  (alias — auto-follows)
...
FREE_UPLOAD_ROW_LIMIT = 250
STARTER_UPLOAD_ROW_LIMIT = 2_500
PRO_UPLOAD_ROW_LIMIT = 10_000
```
Leave `STANDARD_PLAN_MONTHLY_LIMIT = STARTER_PLAN_MONTHLY_LIMIT` as-is (it aliases, so it follows automatically).

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

## PHASE 2 — Frontend Display

### Task 2.1: Update hardcoded limits in sidebar.js

**Files:** Modify `extension/sidebar.js` (lines ~641 and ~719)

**Step 1:** Both lines read:
```js
var limit = plan === "pro" ? 10000 : plan === "starter" ? 2000 : 50;
```
Change BOTH to:
```js
var limit = plan === "pro" ? 10000 : plan === "starter" ? 2500 : 250;
```
(Search the whole file for any other `2000`/`\b50\b` used as a plan limit — there were exactly 2 quota sites at 641/719, but confirm with grep.)

**Step 2:** Verify:
```bash
cd D:/dev/git/outmass && grep -n "plan === \"pro\"" extension/sidebar.js
```
Both should now show `2500 : 250`.

**Step 3:** `node --check extension/sidebar.js` → OK.

**Step 4:** Commit:
```bash
git add extension/sidebar.js
git commit -m "feat(ext): sidebar quota display uses new plan limits (250/2500/10000)"
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
