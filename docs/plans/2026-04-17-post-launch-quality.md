# Post-Launch Quality Pass — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Harden OutMass with the CSV/content/campaign-name validations and UX polish listed in HANDOFF.md sections A–D (critical + important + future), so the product feels safe and professional on day 1.

**Architecture:** Server-authoritative validation (FastAPI routers/models) with early client-side mirror for UX. Reuse the existing FakeSupabase unit-test pattern for backend changes and test-after for pure UI polish. i18n keys mirror the existing `messages.json` convention, added to all 10 locales.

**Tech Stack:** FastAPI + Pydantic, Supabase Python client, vanilla JS (MV3), pytest + Playwright, Chrome i18n API.

**Order (per HANDOFF suggestion):** C → A → B → D. Each section ends with unit tests green and a single semantic commit.

**Testing philosophy:**
- **TDD** for backend validators (`contact.py`, `campaigns.py` endpoints, merge-tag helpers).
- **Test-after** for UI polish (preview modal, onboarding, archive tab).
- Unit suite lives at `backend/tests/`, runs in ~3 s with mock DB (`conftest.py`).
- E2E locked by visual regression — avoid CSS churn; prefer additive DOM changes.

**i18n rule:** Every user-facing string goes through `t("key")`. Add the key to `extension/_locales/en/messages.json` FIRST, then propagate to the other 9 locales in a single commit (tr, de, fr, es, ru, ar, hi, zh_CN, ja).

---

## PHASE 0 — Baseline

### Task 0.1: Confirm test suite green before changes

**Step 1:** Run full unit suite
```bash
cd D:/dev/git/outmass && npm run test:unit
```
Expected: `70 passed`

**Step 2:** Sanity-check Playwright doesn't crash (optional, slow)
```bash
npm run test:e2e -- --reporter=list
```
Expected: 48 passed. If any fail on baseline, record the failure and fix before proceeding.

**Step 3:** Note current commit for rollback reference
```bash
git log --oneline -1
```

---

## PHASE 1 — SECTION C: Email Content Controls

The rationale for doing C first: merge-tag validation catches the #1 user failure mode (broken placeholders landing in recipient inboxes), and Test Send is the most-requested feature.

### Task C.1: Backend — merge-tag validator (KNOWN + UNKNOWN + MALFORMED)

**Files:**
- Create: `backend/utils/merge_tags.py`
- Test: `backend/tests/test_merge_tags.py`

**Step 1: Write failing tests** (`backend/tests/test_merge_tags.py`)

```python
"""Tests for merge-tag validation helpers."""
import pytest
from utils.merge_tags import (
    find_malformed_tags,
    find_unknown_tags,
    STANDARD_TAGS,
)


def test_find_malformed_tags_detects_missing_close_brace():
    # Missing closing brace — dangerous, will land in inbox
    result = find_malformed_tags("Hello {{firstName}")
    assert result == ["{{firstName"]


def test_find_malformed_tags_detects_missing_open_brace():
    result = find_malformed_tags("Hello firstName}}")
    assert result == ["firstName}}"]


def test_find_malformed_tags_single_brace_ignored():
    # A lone { or } without a partner is not a "malformed tag" — just text
    assert find_malformed_tags("Price: $5 { off }") == []


def test_find_malformed_tags_empty_tag():
    # {{}} is malformed
    assert find_malformed_tags("Hello {{}}") == ["{{}}"]


def test_find_malformed_tags_clean_template():
    assert find_malformed_tags("Hi {{firstName}}, welcome.") == []


def test_find_unknown_tags_flags_missing_context_key():
    ctx_keys = {"firstName", "email"}
    result = find_unknown_tags("Hi {{firstName}} at {{unknownField}}", ctx_keys)
    assert result == ["unknownField"]


def test_find_unknown_tags_standard_tags_always_ok():
    # senderName etc. are always resolvable from user profile
    result = find_unknown_tags("From {{senderName}}", set())
    assert result == []


def test_find_unknown_tags_multiple_unknowns_deduplicated():
    result = find_unknown_tags("{{foo}} {{bar}} {{foo}}", set())
    assert sorted(result) == ["bar", "foo"]


def test_find_unknown_tags_handles_empty_template():
    assert find_unknown_tags("", {"firstName"}) == []


def test_standard_tags_includes_all_documented():
    for key in ("firstName", "lastName", "email", "company", "position",
                "senderName", "senderPosition", "senderCompany", "senderPhone"):
        assert key in STANDARD_TAGS
```

**Step 2:** Run tests to confirm they fail
```bash
npm run test:unit -- tests/test_merge_tags.py -v
```
Expected: `ModuleNotFoundError: utils.merge_tags`

**Step 3: Create the module** (`backend/utils/__init__.py` empty file + `backend/utils/merge_tags.py`)

```python
"""Merge-tag validators used by campaign create/send paths."""
import re

# Template tags resolvable from user profile (always available)
SENDER_TAGS = frozenset({
    "senderName", "senderPosition", "senderCompany", "senderPhone",
})

# Tags resolvable from a standard contact row
CONTACT_TAGS = frozenset({
    "firstName", "lastName", "email", "company", "position",
})

STANDARD_TAGS = SENDER_TAGS | CONTACT_TAGS

_WELLFORMED = re.compile(r"\{\{(\w+)\}\}")
# Anything that looks like an attempted tag: {{... or ...}} with mismatched braces
# We locate "{{" followed by no "}}" before the next "{{" or end, OR
# a "}}" preceded by no matching "{{". Simple heuristic:
_MAYBE_TAG = re.compile(r"\{\{[^{}]*\}?|\{?[^{}]*\}\}")


def find_malformed_tags(template: str) -> list[str]:
    """Return substrings that look like broken merge tags.

    Examples of malformed input:
        "{{firstName"      -> missing close
        "firstName}}"      -> missing open
        "{{}}"             -> empty
    Well-formed `{{key}}` is ignored.
    """
    if not template:
        return []
    out = []
    # Strip well-formed tags first, then look for leftover brace pairs
    stripped = _WELLFORMED.sub("", template)
    for m in re.finditer(r"\{\{[^{}]*?(?=\{\{|$)|\{\{[^{}]*?\}?|[^{}]*?\}\}", stripped):
        frag = m.group(0).strip()
        if not frag:
            continue
        # A fragment must contain "{{" or "}}" to count as malformed tag
        if "{{" in frag or "}}" in frag:
            # Filter noise: require at least one brace pair partial
            if frag.count("{") != frag.count("}"):
                out.append(frag)
            elif frag == "{{}}":
                out.append(frag)
    # Dedupe preserving order
    seen = set()
    result = []
    for item in out:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def find_unknown_tags(template: str, contact_keys: set[str]) -> list[str]:
    """Return well-formed tag names that won't resolve against the given context.

    contact_keys: set of columns present in the uploaded CSV (e.g. {"firstName", "customField"}).
    Sender tags (senderName etc.) are always considered known.
    """
    if not template:
        return []
    found = _WELLFORMED.findall(template)
    allowed = STANDARD_TAGS | contact_keys
    unknowns = []
    seen = set()
    for tag in found:
        if tag not in allowed and tag not in seen:
            seen.add(tag)
            unknowns.append(tag)
    return unknowns
```

**Step 4:** Run tests to confirm pass
```bash
npm run test:unit -- tests/test_merge_tags.py -v
```
Expected: `10 passed`

**Step 5: Commit**
```bash
git add backend/utils/__init__.py backend/utils/merge_tags.py backend/tests/test_merge_tags.py
git commit -m "feat: add merge-tag validators (malformed + unknown detection)"
```

---

### Task C.2: Wire merge-tag validation into send path

**File:** `backend/routers/campaigns.py:229` (send_campaign endpoint)

**Step 1: Add test for malformed tag rejection** (`backend/tests/test_campaigns_validation.py` — new file)

```python
"""Validation tests for campaign create/send paths (subject/body/name/merge tags)."""
from unittest.mock import patch, MagicMock

from tests.conftest import FakeQueryBuilder, FAKE_USER
from main import app
from routers.auth import get_current_user


def test_send_rejects_malformed_merge_tag(client, fake_db, auth_bypass):
    """Sending a campaign with a broken {{tag} in body must return 400."""
    campaign = {
        "id": "c1", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "Hi {{firstName}", "body": "Body ok", "name": "Test",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 1,
    }
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    fake_db.set_table("contacts", FakeQueryBuilder(data=[
        {"id": "k1", "email": "a@b.com", "status": "pending", "unsubscribed": False,
         "first_name": "A", "last_name": "B", "company": "", "position": "",
         "custom_fields": {}}
    ]))
    fake_db.set_table("suppression_list", FakeQueryBuilder(data=[]))
    with patch("models.ms_token.get_fresh_access_token", return_value="fake-token"):
        resp = client.post("/campaigns/c1/send", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 400
    assert "malformed" in resp.json()["detail"].lower() or "merge" in resp.json()["detail"].lower()
```

**Step 2:** Run — expect fail (endpoint doesn't validate yet)
```bash
npm run test:unit -- tests/test_campaigns_validation.py::test_send_rejects_malformed_merge_tag -v
```

**Step 3: Modify `backend/routers/campaigns.py`**

At top of file, add import:
```python
from utils.merge_tags import find_malformed_tags, find_unknown_tags
```

Inside `send_campaign()` — right after the `if not pending` check around line 265, insert:

```python
    # ── Merge-tag validation (C-01/C-02) ──
    for field_name, content in (("subject", campaign["subject"]), ("body", campaign["body"])):
        malformed = find_malformed_tags(content)
        if malformed:
            raise HTTPException(
                status_code=400,
                detail=f"Malformed merge tag in {field_name}: {malformed[0]}",
            )
    # Collect contact keys actually present (firstName/lastName/... + custom)
    first = pending[0]
    contact_keys = set()
    for k, v in first.items():
        if v not in (None, ""):
            # Map DB snake_case back to camelCase merge-tag names
            key = {"first_name": "firstName", "last_name": "lastName"}.get(k, k)
            contact_keys.add(key)
    for k in (first.get("custom_fields") or {}).keys():
        contact_keys.add(k)
    unknown_subj = find_unknown_tags(campaign["subject"], contact_keys)
    unknown_body = find_unknown_tags(campaign["body"], contact_keys)
    unknowns = sorted(set(unknown_subj + unknown_body))
    if unknowns:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown merge tags (not in CSV): {', '.join(unknowns)}",
        )
```

**Step 4:** Run — expect pass
```bash
npm run test:unit -- tests/test_campaigns_validation.py -v
```

**Step 5: Add unknown-tag test** in same file:
```python
def test_send_rejects_unknown_merge_tag(client, fake_db, auth_bypass):
    campaign = {
        "id": "c2", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "Hi {{fname}}", "body": "Body ok", "name": "Test",
        "sent_count": 0, "open_count": 0, "click_count": 0, "total_contacts": 1,
    }
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    fake_db.set_table("contacts", FakeQueryBuilder(data=[
        {"id": "k1", "email": "a@b.com", "status": "pending", "unsubscribed": False,
         "first_name": "A", "last_name": "", "company": "", "position": "",
         "custom_fields": {}}
    ]))
    fake_db.set_table("suppression_list", FakeQueryBuilder(data=[]))
    with patch("models.ms_token.get_fresh_access_token", return_value="fake-token"):
        resp = client.post("/campaigns/c2/send", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 400
    assert "fname" in resp.json()["detail"]
```

**Step 6:** Run full merge-tag suite → expect pass. **Commit:**
```bash
git add backend/routers/campaigns.py backend/tests/test_campaigns_validation.py
git commit -m "feat: reject campaigns with malformed or unknown merge tags before send"
```

---

### Task C.3: Test Send endpoint — send preview to sender's own email

**Files:**
- Modify: `backend/routers/campaigns.py`
- Test: append to `backend/tests/test_campaigns_validation.py`

**Step 1: Write test first**

```python
def test_test_send_sends_to_sender_email(client, fake_db, auth_bypass):
    """POST /campaigns/{id}/test-send delivers one email to the authenticated user."""
    campaign = {
        "id": "c3", "user_id": FAKE_USER["id"], "status": "draft",
        "subject": "Hi {{firstName}}", "body": "Welcome {{firstName}}",
        "name": "Test", "sent_count": 0, "open_count": 0,
        "click_count": 0, "total_contacts": 0,
    }
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[campaign]))
    mock_send = MagicMock(return_value={"success": True})
    with patch("models.ms_token.get_fresh_access_token", return_value="fake-token"), \
         patch("routers.campaigns._send_single_email", new=mock_send):
        resp = client.post("/campaigns/c3/test-send",
                           headers={"Authorization": "Bearer t"},
                           json={"sample": {"firstName": "Alice"}})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
```

**Step 2:** Run — expect 404 or 405 (no endpoint yet)

**Step 3: Implement endpoint** in `campaigns.py` (after `send_campaign` around line 392):

```python
class TestSendRequest(BaseModel):
    sample: dict | None = None  # optional merge-tag values to use


@router.post("/{campaign_id}/test-send")
async def test_send(
    campaign_id: str,
    body: TestSendRequest,
    user: dict = Depends(get_current_user),
):
    """Send a single test email to the authenticated user's own address.

    Uses the sample dict (from first CSV row or user-supplied) as merge context.
    Does NOT count against monthly quota. Does NOT create tracking records.
    """
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    for field_name, content in (("subject", campaign["subject"]), ("body", campaign["body"])):
        malformed = find_malformed_tags(content)
        if malformed:
            raise HTTPException(
                status_code=400,
                detail=f"Malformed merge tag in {field_name}: {malformed[0]}",
            )

    from models.ms_token import get_fresh_access_token
    access_token = get_fresh_access_token(user["id"])
    if not access_token:
        raise HTTPException(status_code=401, detail="Token refresh failed")

    sample = body.sample or {}
    synthetic_contact = {
        "id": "test-" + campaign_id,
        "email": user["email"],
        "first_name": sample.get("firstName", "Test"),
        "last_name": sample.get("lastName", "User"),
        "company": sample.get("company", ""),
        "position": sample.get("position", ""),
        "custom_fields": {k: v for k, v in sample.items()
                          if k not in ("firstName", "lastName", "company", "position", "email")},
    }

    async with httpx.AsyncClient() as client:
        result = await _send_single_email(
            client=client,
            access_token=access_token,
            campaign=campaign,
            contact=synthetic_contact,
            track_opens=False,  # test send doesn't track
            track_clicks=False,
            unsubscribe_text=user.get("unsubscribe_text", "Abonelikten cik"),
            sender_info=user,
        )

    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "Test send failed"))

    return {"success": True, "sent_to": user["email"]}
```

**Step 4:** Run test — expect pass.

**Step 5: Commit**
```bash
git add backend/routers/campaigns.py backend/tests/test_campaigns_validation.py
git commit -m "feat: add /campaigns/{id}/test-send endpoint (preview to sender)"
```

---

### Task C.4: Frontend — Test Send button + modal

**Files:**
- Modify: `extension/sidebar.html` (add button next to Preview)
- Modify: `extension/sidebar.js` (wire button to background → backend)
- Modify: `extension/background.js` (add TEST_SEND message handler)
- Modify: `extension/_locales/en/messages.json` + 9 other locales (new keys)

**Step 1: Add i18n keys** to `extension/_locales/en/messages.json` (append before closing `}`):

```json
  "btnTestSend": { "message": "Test Send" },
  "testSendPrompt": { "message": "A test email will be sent to your own address. Continue?" },
  "testSendSuccess": { "message": "Test email sent to $EMAIL$. Check your inbox.", "placeholders": { "email": { "content": "$1" } } },
  "testSendFailed": { "message": "Test send failed: $ERROR$", "placeholders": { "error": { "content": "$1" } } },
  "testSendNeedsContent": { "message": "Enter subject and body first." }
```

**Step 2:** Translate to 9 other locales (tr/de/fr/es/ru/ar/hi/zh_CN/ja). For each file, add the 5 keys with translated `message`. Translations provided under Task C.4-i18n appendix below.

**Step 3: Add HTML button** in `extension/sidebar.html` — find the existing `<button id="btn-preview"` and duplicate it next to it:

```html
<button id="btn-test-send" class="btn-secondary" data-i18n-key="btnTestSend">Test Send</button>
```

**Step 4: Wire in sidebar.js** — after `btnPreview.addEventListener` (around line 247), add:

```javascript
var btnTestSend = document.getElementById("btn-test-send");
if (btnTestSend) {
  btnTestSend.addEventListener("click", function () {
    var subject = subjectInput.value.trim();
    var body = bodyInput.value.trim();
    if (!subject || !body) {
      alert(t("testSendNeedsContent"));
      return;
    }
    if (!confirm(t("testSendPrompt"))) return;
    btnTestSend.disabled = true;
    var originalText = btnTestSend.textContent;
    btnTestSend.textContent = "…";

    var sample = (csvData && csvData.rows && csvData.rows[0]) || {};
    // Create ephemeral campaign, test-send, cleanup
    chrome.runtime.sendMessage(
      { type: "CREATE_CAMPAIGN", payload: { name: "__test__", subject: subject, body: body } },
      function (createResp) {
        if (!createResp || createResp.error) {
          alert(t("testSendFailed", [createResp ? createResp.error : "create failed"]));
          btnTestSend.disabled = false;
          btnTestSend.textContent = originalText;
          return;
        }
        var cid = createResp.data ? createResp.data.campaign_id : createResp.campaign_id;
        chrome.runtime.sendMessage(
          { type: "TEST_SEND", campaignId: cid, payload: { sample: sample } },
          function (resp) {
            btnTestSend.disabled = false;
            btnTestSend.textContent = originalText;
            if (!resp || resp.error) {
              alert(t("testSendFailed", [resp ? resp.error : "send failed"]));
              return;
            }
            alert(t("testSendSuccess", [resp.data ? resp.data.sent_to : ""]));
          }
        );
      }
    );
  });
}
```

**Step 5: Add TEST_SEND handler in `extension/background.js`** — find the pattern like `SEND_CAMPAIGN` and mirror it:

```javascript
if (msg.type === "TEST_SEND") {
  apiCall("POST", "/campaigns/" + msg.campaignId + "/test-send", msg.payload)
    .then(function (data) { sendResponse({ data: data }); })
    .catch(function (err) { sendResponse({ error: err.message || String(err), status: err.status }); });
  return true; // async
}
```

**Step 6:** Load extension in Chrome, open Outlook Web, open sidebar, click Test Send — verify email arrives.

**Step 7: Commit**
```bash
git add extension/sidebar.html extension/sidebar.js extension/background.js extension/_locales/
git commit -m "feat: Test Send button — preview delivery to sender's own inbox"
```

---

### Task C.5: Subject length warning + ALL CAPS warning + spam word warning + link count

**File:** `extension/sidebar.js` (client-side soft warnings — not a hard block)

**Step 1: Add helper functions** in sidebar.js (near `mergePlaceholders`):

```javascript
var SPAM_WORDS = [
  "free!!!", "act now", "100% guaranteed", "click here", "buy now",
  "limited time", "urgent", "winner", "congratulations", "$$$", "cash bonus"
];

function getContentWarnings(subject, body) {
  var warnings = [];
  // Subject length
  if (subject.length > 78) warnings.push(t("warnSubjectLong"));
  // ALL CAPS check (more than 50% uppercase letters in subject)
  var letters = subject.replace(/[^A-Za-z]/g, "");
  if (letters.length >= 8) {
    var upper = subject.replace(/[^A-Z]/g, "").length;
    if (upper / letters.length > 0.5) warnings.push(t("warnAllCaps"));
  }
  // Spam words
  var combined = (subject + " " + body).toLowerCase();
  var hits = SPAM_WORDS.filter(function (w) { return combined.indexOf(w) >= 0; });
  if (hits.length > 0) {
    warnings.push(t("warnSpamWords", [hits.slice(0, 3).join(", ")]));
  }
  // Link count
  var linkCount = (body.match(/https?:\/\//gi) || []).length;
  if (linkCount >= 5) warnings.push(t("warnTooManyLinks", [String(linkCount)]));
  return warnings;
}
```

**Step 2: Add i18n keys** (en + 9 locales):
```json
  "warnSubjectLong": { "message": "Subject is over 78 chars — may be truncated on mobile." },
  "warnAllCaps": { "message": "Subject uses many capital letters — looks like spam." },
  "warnSpamWords": { "message": "Possible spam words detected: $LIST$", "placeholders": { "list": { "content": "$1" } } },
  "warnTooManyLinks": { "message": "$N$ links in body — may trigger spam filters.", "placeholders": { "n": { "content": "$1" } } },
  "warnContinueAnyway": { "message": "Continue sending anyway?" }
```

**Step 3: Show warnings before send** — in the existing btnSend click handler (around line 325-340, the part that calls `startSendFlow`), insert before the call:

```javascript
var warnings = getContentWarnings(subject, body);
if (warnings.length > 0) {
  var msg = warnings.join("\n• ");
  if (!confirm("• " + msg + "\n\n" + t("warnContinueAnyway"))) return;
}
```

**Step 4:** Manual test — enter `FREE!!! ACT NOW GUARANTEED` as subject, verify warning dialog appears.

**Step 5: Commit**
```bash
git add extension/sidebar.js extension/_locales/
git commit -m "feat: warn user about spam words, ALL CAPS, long subjects, link overload before send"
```

---

### Task C.6 (future): HTML validation & link shortener detection

Keep stub only: add a TODO comment pointing to this task in `sidebar.js`:
```javascript
// TODO: C-future — detect bit.ly/tinyurl shortened links (deliverability hit);
// HTML structure validation (unbalanced tags); image count > 5 warning.
```
**No code change, no commit** — tracked in HANDOFF.md checklist.

---

## PHASE 2 — SECTION A: CSV Controls

### Task A.1: Backend — case-insensitive email normalization + within-CSV dedup

**Files:**
- Modify: `backend/models/contact.py` (`bulk_insert`)
- Test: `backend/tests/test_contact_validation.py` (new)

**Step 1: Write failing tests**

```python
"""Contact bulk_insert validation tests."""
from unittest.mock import MagicMock, patch

from models import contact as contact_model
from tests.conftest import FakeQueryBuilder


def test_bulk_insert_deduplicates_within_csv(fake_db):
    """Same email appearing twice in one upload is only inserted once."""
    fake_db.set_table("contacts", FakeQueryBuilder(data=[]))
    rows = [
        {"email": "alice@example.com", "firstName": "Alice"},
        {"email": "alice@example.com", "firstName": "Alice2"},
        {"email": "bob@example.com", "firstName": "Bob"},
    ]
    # We don't assert the returned count (FakeSupabase echoes back what was inserted);
    # instead we inspect the payload passed to insert().
    inserted = []
    class Capture(FakeQueryBuilder):
        def insert(self, r):
            inserted.extend(r)
            return self
    fake_db.set_table("contacts", Capture())
    contact_model.bulk_insert("camp1", rows)
    emails = [r["email"] for r in inserted]
    assert emails.count("alice@example.com") == 1
    assert "bob@example.com" in emails


def test_bulk_insert_normalizes_email_case_insensitive(fake_db):
    inserted = []
    class Capture(FakeQueryBuilder):
        def insert(self, r):
            inserted.extend(r)
            return self
    fake_db.set_table("contacts", Capture())
    rows = [
        {"email": "Alice@Example.COM"},
        {"email": "alice@example.com"},  # dupe after normalize
    ]
    contact_model.bulk_insert("camp1", rows)
    assert len(inserted) == 1
    assert inserted[0]["email"] == "alice@example.com"


def test_bulk_insert_filters_suppressed_emails(fake_db):
    inserted = []
    class Capture(FakeQueryBuilder):
        def insert(self, r):
            inserted.extend(r)
            return self
    fake_db.set_table("contacts", Capture())
    rows = [
        {"email": "keep@example.com"},
        {"email": "blocked@example.com"},
    ]
    contact_model.bulk_insert("camp1", rows, suppressed={"blocked@example.com"})
    assert [r["email"] for r in inserted] == ["keep@example.com"]
```

**Step 2:** Run — expect failures.

**Step 3: Modify `backend/models/contact.py`:bulk_insert**:

```python
def bulk_insert(
    campaign_id: str,
    contacts: list[dict],
    suppressed: set[str] | None = None,
) -> dict:
    """Insert contacts for a campaign.

    - Normalizes email to lowercase.
    - Deduplicates by email within the given list (case-insensitive).
    - Skips invalid email format.
    - Skips entries present in the optional `suppressed` set.

    Returns a dict: {"inserted": int, "skipped_invalid": int,
                      "skipped_duplicate": int, "skipped_suppressed": int}.
    """
    suppressed = {s.lower() for s in (suppressed or set())}
    seen: set[str] = set()
    rows: list[dict] = []
    skipped_invalid = 0
    skipped_duplicate = 0
    skipped_suppressed = 0

    for c in contacts:
        raw = (c.get("email") or "").strip().lower()
        if not raw or not EMAIL_REGEX.match(raw):
            skipped_invalid += 1
            continue
        if raw in suppressed:
            skipped_suppressed += 1
            continue
        if raw in seen:
            skipped_duplicate += 1
            continue
        seen.add(raw)
        rows.append({
            "campaign_id": campaign_id,
            "email": raw,
            "first_name": c.get("firstName", c.get("first_name", "")),
            "last_name": c.get("lastName", c.get("last_name", "")),
            "company": c.get("company", ""),
            "position": c.get("position", ""),
            "custom_fields": {
                k: v for k, v in c.items()
                if k not in ("email", "firstName", "first_name", "lastName",
                             "last_name", "company", "position")
            },
            "status": "pending",
        })

    if not rows:
        return {
            "inserted": 0, "skipped_invalid": skipped_invalid,
            "skipped_duplicate": skipped_duplicate,
            "skipped_suppressed": skipped_suppressed,
        }

    result = get_db().table("contacts").insert(rows).execute()
    return {
        "inserted": len(result.data) if result.data else len(rows),
        "skipped_invalid": skipped_invalid,
        "skipped_duplicate": skipped_duplicate,
        "skipped_suppressed": skipped_suppressed,
    }
```

**Step 4:** Update callers. `bulk_insert` now returns a dict, not an int. Grep:
```bash
grep -rn "bulk_insert" D:/dev/git/outmass/backend/
```
Update `routers/campaigns.py:212` — replace `count = contact_model.bulk_insert(...)` with:
```python
result = contact_model.bulk_insert(campaign_id, contacts, suppressed=suppressed_emails_lower)
count = result["inserted"]
```
(We'll fetch `suppressed_emails_lower` in task A.3.)

**Step 5:** Run full unit suite — expect all pass. **Commit:**
```bash
git add backend/models/contact.py backend/tests/test_contact_validation.py
git commit -m "feat: dedupe + case-insensitive email normalization in bulk_insert"
```

---

### Task A.2: upload_contacts — mandatory email column, row/size limits, UTF-8 BOM, latin-1 rejection

**File:** `backend/routers/campaigns.py:187` (upload_contacts)

**Step 1: Write failing tests** (append to `test_contact_validation.py`):

```python
def test_upload_rejects_missing_email_column(client, fake_db, auth_bypass):
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[
        {"id": "c1", "user_id": "00000000-0000-0000-0000-000000000001",
         "subject": "s", "body": "b", "status": "draft"},
    ]))
    csv = "name,company\nAlice,Acme\n"
    resp = client.post("/campaigns/c1/contacts", json={"csv_string": csv})
    assert resp.status_code == 400
    assert "email" in resp.json()["detail"].lower()


def test_upload_rejects_too_many_rows(client, fake_db, auth_bypass):
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[
        {"id": "c1", "user_id": "00000000-0000-0000-0000-000000000001",
         "subject": "s", "body": "b", "status": "draft"},
    ]))
    # Exceed Free plan limit (100 rows for free)
    rows = ["email"] + [f"user{i}@example.com" for i in range(200)]
    csv = "email\n" + "\n".join(rows[1:]) + "\n"
    resp = client.post("/campaigns/c1/contacts", json={"csv_string": csv})
    assert resp.status_code == 413
    assert "limit" in resp.json()["detail"].lower() or "rows" in resp.json()["detail"].lower()
```

**Step 2:** Run — expect 200 (no validation yet), test fails.

**Step 3: Modify upload_contacts.** Add imports at top:

```python
from config import (
    ...,
    FREE_UPLOAD_ROW_LIMIT,
    STARTER_UPLOAD_ROW_LIMIT,
    PRO_UPLOAD_ROW_LIMIT,
    MAX_CSV_SIZE_BYTES,
)
```

Add to `backend/config.py`:
```python
# CSV upload limits (per upload, not cumulative)
FREE_UPLOAD_ROW_LIMIT = 100
STARTER_UPLOAD_ROW_LIMIT = 2_000
PRO_UPLOAD_ROW_LIMIT = 5_000
MAX_CSV_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
```

Replace upload_contacts body (keep decorator + signature):

```python
@router.post("/{campaign_id}/contacts")
async def upload_contacts(
    campaign_id: str,
    body: UploadContactsRequest,
    user: dict = Depends(get_current_user),
):
    campaign = campaign_model.get_campaign(campaign_id)
    if not campaign or campaign["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")

    plan = user.get("plan", "free")
    row_limit = {"pro": PRO_UPLOAD_ROW_LIMIT,
                 "starter": STARTER_UPLOAD_ROW_LIMIT}.get(plan, FREE_UPLOAD_ROW_LIMIT)

    contacts: list[dict] = []

    if body.csv_string:
        # Size check (UTF-8 byte length)
        if len(body.csv_string.encode("utf-8")) > MAX_CSV_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="CSV file exceeds 5 MB limit")
        # Strip UTF-8 BOM if present
        text = body.csv_string.lstrip("\ufeff")
        # Detect unusable encoding (Latin-1/cp1252 non-UTF8 chars) — if we see
        # replacement characters, the client already botched the decode.
        if "\ufffd" in text:
            raise HTTPException(
                status_code=400,
                detail="CSV encoding not recognized. Please save as UTF-8.",
            )
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or "email" not in [h.lower() for h in reader.fieldnames]:
            raise HTTPException(
                status_code=400,
                detail="Column 'email' is required in the CSV header",
            )
        # Normalize header case: ensure the dict key is lowercase "email"
        for row in reader:
            normalized = {}
            for k, v in row.items():
                if k and k.lower() == "email":
                    normalized["email"] = v
                else:
                    normalized[k] = v
            contacts.append(normalized)
    elif body.contacts:
        contacts = body.contacts
        # JSON path: require every row to have 'email'
        if contacts and not any("email" in c for c in contacts):
            raise HTTPException(status_code=400, detail="'email' field required")

    if not contacts:
        raise HTTPException(status_code=400, detail="No contacts provided")

    if len(contacts) > row_limit:
        raise HTTPException(
            status_code=413,
            detail=f"CSV has {len(contacts)} rows, plan limit is {row_limit}",
        )

    # Cross-check against suppression list
    from database import get_db
    suppressed_rows = (
        get_db().table("suppression_list")
        .select("email").eq("user_id", user["id"]).execute()
    )
    suppressed_set = {r["email"].lower() for r in (suppressed_rows.data or [])}

    result = contact_model.bulk_insert(campaign_id, contacts, suppressed=suppressed_set)

    total = contact_model.get_campaign_contacts_count(campaign_id)
    campaign_model.update_campaign(campaign_id, {"total_contacts": total})

    preview = []
    for c in contacts[:3]:
        merged_subject = _merge_template(campaign["subject"], c)
        preview.append({"email": c.get("email", ""), "subject": merged_subject})

    return {
        "count": result["inserted"],
        "skipped_invalid": result["skipped_invalid"],
        "skipped_duplicate": result["skipped_duplicate"],
        "skipped_suppressed": result["skipped_suppressed"],
        "preview": preview,
    }
```

**Step 4:** Run tests → expect pass.

**Step 5: Commit**
```bash
git add backend/config.py backend/routers/campaigns.py backend/tests/test_contact_validation.py
git commit -m "feat: CSV upload — mandatory email, row/size limits, BOM strip, suppression cross-check"
```

---

### Task A.3: Client-side mirror — pre-validate CSV before upload

**File:** `extension/sidebar.js` (`handleCSV` around line 159)

**Step 1: Modify handleCSV** to add size limit + header check:

```javascript
var CSV_MAX_BYTES = 5 * 1024 * 1024;
var CSV_MAX_ROWS_DISPLAY = 5000; // soft warning; backend enforces plan-based limit

function handleCSV(file) {
  if (file.size > CSV_MAX_BYTES) {
    alert(t("csvErrTooLarge"));
    return;
  }
  var reader = new FileReader();
  reader.onload = function (e) {
    var text = e.target.result;
    // Strip BOM
    if (text.charCodeAt(0) === 0xFEFF) text = text.slice(1);
    // Detect botched encoding (replacement chars)
    if (text.indexOf("\uFFFD") >= 0) {
      alert(t("csvErrEncoding"));
      return;
    }
    csvRawText = text;
    var lines = text.trim().split(/\r?\n/);
    var headers = parseCSVLine(lines[0]).map(function (h) { return h.trim(); });
    var lowerHeaders = headers.map(function (h) { return h.toLowerCase(); });
    if (lowerHeaders.indexOf("email") < 0) {
      alert(t("csvErrNoEmailColumn"));
      return;
    }
    var rows = [];
    var seen = {};
    var dupCount = 0;
    for (var i = 1; i < lines.length; i++) {
      if (!lines[i].trim()) continue;
      var values = parseCSVLine(lines[i]);
      var row = {};
      headers.forEach(function (h, idx) { row[h] = values[idx] !== undefined ? values[idx] : ""; });
      // Lowercase email + dedupe
      var em = (row.email || row.Email || "").trim().toLowerCase();
      if (!em) continue;
      row.email = em;
      if (seen[em]) { dupCount++; continue; }
      seen[em] = true;
      rows.push(row);
    }
    csvData = { headers: headers, rows: rows };
    csvDropzone.style.display = "none";
    csvInfo.style.display = "flex";
    csvFilename.textContent = file.name;
    var msg = rows.length + " " + t("csvCountSuffix");
    if (dupCount > 0) msg += " (" + dupCount + " " + t("csvDupRemoved") + ")";
    csvCount.textContent = msg;
    updateSendButton();
  };
  reader.readAsText(file, "UTF-8");
}
```

**Step 2: Add i18n keys** (en + 9 locales):
```json
  "csvErrTooLarge": { "message": "CSV file too large (max 5 MB)." },
  "csvErrEncoding": { "message": "CSV encoding not recognized. Save the file as UTF-8." },
  "csvErrNoEmailColumn": { "message": "CSV must have an 'email' column." },
  "csvDupRemoved": { "message": "duplicates removed" }
```

**Step 3:** Manual test in Chrome — upload CSV without email column, verify alert.

**Step 4: Commit**
```bash
git add extension/sidebar.js extension/_locales/
git commit -m "feat: client-side CSV pre-validation (email column, dedup, size, encoding)"
```

---

### Task A.4 (future): role-account + disposable domain detection

**File:** `backend/utils/email_classifier.py` (new)

**Step 1: Write stub with tests** but keep lists short:

```python
ROLE_PREFIXES = frozenset({
    "admin", "info", "noreply", "no-reply", "postmaster", "abuse",
    "support", "billing", "sales", "contact", "hello", "hr",
})

DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "tempmail.com", "10minutemail.com",
    "throwaway.email", "yopmail.com", "trashmail.com", "getnada.com",
    # ~30 entries — expand over time
})


def is_role_account(email: str) -> bool:
    local = email.split("@")[0].lower() if "@" in email else ""
    return local in ROLE_PREFIXES


def is_disposable(email: str) -> bool:
    if "@" not in email:
        return False
    domain = email.split("@", 1)[1].lower()
    return domain in DISPOSABLE_DOMAINS
```

Tests at `backend/tests/test_email_classifier.py`:
```python
from utils.email_classifier import is_role_account, is_disposable

def test_role_account(): assert is_role_account("Info@Acme.com")
def test_not_role(): assert not is_role_account("alice@acme.com")
def test_disposable(): assert is_disposable("x@mailinator.com")
def test_not_disposable(): assert not is_disposable("x@gmail.com")
```

**Step 2:** Integrate into `bulk_insert` — add `warn_role` / `warn_disposable` counters in the returned dict (don't skip; just count). Skip full UI wiring for now; report counts via upload response payload.

**Step 3: Commit**
```bash
git add backend/utils/email_classifier.py backend/tests/test_email_classifier.py
git commit -m "feat: detect role accounts + disposable domains (warn only, no skip)"
```

---

### Task A.5 (future): previous-campaign dedup (Pro only)

Add a TODO comment in `upload_contacts`:
```python
# TODO A.5: Pro plan — optionally dedup against contacts from previous campaigns
# within the same user. Requires a new query on contacts table and a
# user-setting toggle (default off).
```
**No code change, no commit.** Tracked in HANDOFF.md.

---

## PHASE 3 — SECTION B: Campaign Name

### Task B.1: Backend — reject whitespace-only name

**File:** `backend/routers/campaigns.py:70` (create_campaign)

**Step 1: Test** (append to `test_campaigns_validation.py`):
```python
def test_create_rejects_whitespace_only_name(client, fake_db, auth_bypass):
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[]))
    resp = client.post("/campaigns",
                       json={"name": "   ", "subject": "s", "body": "b"})
    assert resp.status_code == 400
```

**Step 2:** Run — expect pass creation (no trim validation yet), test fails.

**Step 3: Modify create_campaign** — before the scheduled_for check:
```python
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="Campaign name is required")
    body.name = body.name.strip()
```

**Step 4:** Run → pass. **Commit:**
```bash
git add backend/routers/campaigns.py backend/tests/test_campaigns_validation.py
git commit -m "fix: reject whitespace-only campaign names"
```

---

### Task B.2: Duplicate campaign name warning (client-side confirm)

**File:** `extension/sidebar.js` (`startSendFlow` around line 345)

**Step 1:** Add campaign-list fetch before create. Introduce cached list:

```javascript
var _cachedCampaignNames = null;

function fetchCampaignNames(cb) {
  chrome.runtime.sendMessage({ type: "LIST_CAMPAIGNS" }, function (resp) {
    if (resp && resp.data && Array.isArray(resp.data.campaigns)) {
      _cachedCampaignNames = resp.data.campaigns.map(function (c) { return (c.name || "").toLowerCase(); });
    } else {
      _cachedCampaignNames = [];
    }
    cb();
  });
}
```

In `startSendFlow`, wrap the existing logic:
```javascript
function startSendFlow(subject, body) {
  var nameInput = document.getElementById("campaign-name");
  var campaignName = nameInput && nameInput.value.trim();
  if (!campaignName) {
    // (existing fallback — subject + date)
    var d = new Date();
    var dateSuffix = d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    var subj = subject.substring(0, 50) || t("tabCampaign");
    campaignName = subj + " — " + dateSuffix;
  }
  fetchCampaignNames(function () {
    if (_cachedCampaignNames.indexOf(campaignName.toLowerCase()) >= 0) {
      if (!confirm(t("campaignNameDuplicate", [campaignName]))) return;
    }
    _startSendFlowInner(campaignName, subject, body);
  });
}

// (move the rest of the original startSendFlow body into _startSendFlowInner)
```

**Step 2: Add i18n key**:
```json
  "campaignNameDuplicate": { "message": "A campaign named \"$NAME$\" already exists. Continue?", "placeholders": { "name": { "content": "$1" } } }
```

**Step 3:** Manual test — create a campaign "Test", then try to create another with same name, verify confirm.

**Step 4: Commit**
```bash
git add extension/sidebar.js extension/_locales/
git commit -m "feat: warn on duplicate campaign name before create"
```

---

## PHASE 4 — SECTION D: UX Polish

### Task D.1: Email preview as HTML modal (not alert)

**Files:**
- Modify: `extension/sidebar.js` (btnPreview handler)
- Modify: `extension/styles/sidebar.css` (modal styles)

**Step 1:** Replace the existing `btnPreview.addEventListener` body:

```javascript
btnPreview.addEventListener("click", function () {
  if (!csvData || csvData.rows.length === 0) { alert(t("alertUploadCsvFirst")); return; }
  var subject = subjectInput.value;
  var body = bodyInput.value;
  var firstRow = csvData.rows[0];
  var previewSubject = mergePlaceholders(subject, firstRow);
  var previewBody = mergePlaceholders(body, firstRow);
  showPreviewModal(previewSubject, previewBody);
});

function showPreviewModal(subject, bodyHtml) {
  var existing = document.getElementById("preview-modal");
  if (existing) existing.remove();
  var wrap = document.createElement("div");
  wrap.id = "preview-modal";
  wrap.className = "om-modal-overlay";
  wrap.innerHTML =
    '<div class="om-modal">' +
      '<div class="om-modal-header">' +
        '<span>' + t("previewSubjectLabel") + '</span>' +
        '<button type="button" class="om-modal-close" aria-label="Close">×</button>' +
      '</div>' +
      '<div class="om-modal-subject"></div>' +
      '<iframe class="om-modal-iframe" sandbox=""></iframe>' +
    '</div>';
  document.body.appendChild(wrap);
  wrap.querySelector(".om-modal-subject").textContent = subject;
  var iframe = wrap.querySelector(".om-modal-iframe");
  iframe.srcdoc = '<!doctype html><meta charset="utf-8"><body style="font:14px system-ui;margin:16px;color:#323130">' + bodyHtml + '</body>';
  wrap.addEventListener("click", function (e) {
    if (e.target === wrap || e.target.classList.contains("om-modal-close")) wrap.remove();
  });
}
```

**Step 2: Add CSS** to `extension/styles/sidebar.css`:
```css
.om-modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.55);
  z-index: 10001; display: flex; align-items: center; justify-content: center; padding: 16px; }
.om-modal { background: #fff; border-radius: 10px; width: 100%; max-width: 520px;
  max-height: 85vh; display: flex; flex-direction: column; box-shadow: 0 12px 40px rgba(0,0,0,.25); }
.om-modal-header { display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; border-bottom: 1px solid #edebe9; font-weight: 600; }
.om-modal-close { background: none; border: none; font-size: 22px; cursor: pointer; color: #605e5c; }
.om-modal-subject { padding: 10px 16px; font-weight: 600; color: #323130; border-bottom: 1px solid #edebe9; }
.om-modal-iframe { flex: 1; border: none; min-height: 360px; background: #fafafa; }
```

**Step 3: Add i18n** (en + 9 locales):
```json
  "previewSubjectLabel": { "message": "Preview" }
```

**Step 4:** Manual test. Note: the iframe uses `sandbox=""` (fully isolated — no JS, no same-origin) to render HTML safely. Images served from the sender's domain will load normally.

**Step 5: Commit**
```bash
git add extension/sidebar.js extension/styles/sidebar.css extension/_locales/
git commit -m "feat: render email preview as HTML in modal iframe (not plain-text alert)"
```

---

### Task D.2: Campaign archive — DB flag + Reports tab "Active / Archived"

**Files:**
- Create: `backend/migrations/005_campaign_archived.sql`
- Modify: `backend/models/campaign.py` (add `archived` field support; list_campaigns filter)
- Modify: `backend/routers/campaigns.py` (add PATCH /campaigns/{id}/archive + query param filter)
- Modify: `extension/sidebar.js` (Reports tab — tab switch)
- Modify: `extension/sidebar.html` (sub-tabs inside Reports)

**Step 1: Migration**
```sql
-- 005_campaign_archived.sql
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS campaigns_user_archived_idx ON campaigns(user_id, archived);
```
Run on Supabase:
```bash
# user runs manually against Supabase SQL editor, or via supabase-cli
```

**Step 2: Test (backend)** — add to `test_campaigns_validation.py`:
```python
def test_archive_campaign_sets_flag(client, fake_db, auth_bypass):
    fake_db.set_table("campaigns", FakeQueryBuilder(data=[
        {"id": "c1", "user_id": FAKE_USER["id"], "archived": False,
         "name": "n", "subject": "s", "body": "b", "status": "sent"}
    ]))
    resp = client.post("/campaigns/c1/archive")
    assert resp.status_code == 200
    assert resp.json()["archived"] is True
```

**Step 3: Model change** — in `backend/models/campaign.py`, update `list_campaigns`:
```python
def list_campaigns(user_id: str, archived: bool = False) -> list[dict]:
    result = (get_db().table("campaigns")
        .select("*")
        .eq("user_id", user_id)
        .eq("archived", archived)
        .order("created_at", desc=True)
        .execute())
    return result.data or []


def set_archived(campaign_id: str, archived: bool):
    get_db().table("campaigns").update({"archived": archived}).eq("id", campaign_id).execute()
```

**Step 4: Endpoint** — in `routers/campaigns.py`:
```python
@router.get("")
async def list_campaigns(
    archived: bool = False,
    user: dict = Depends(get_current_user),
):
    campaigns = campaign_model.list_campaigns(user["id"], archived=archived)
    return {"campaigns": campaigns}


@router.post("/{campaign_id}/archive")
async def archive_campaign(campaign_id: str, user: dict = Depends(get_current_user)):
    c = campaign_model.get_campaign(campaign_id)
    if not c or c["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign_model.set_archived(campaign_id, True)
    return {"campaign_id": campaign_id, "archived": True}


@router.post("/{campaign_id}/unarchive")
async def unarchive_campaign(campaign_id: str, user: dict = Depends(get_current_user)):
    c = campaign_model.get_campaign(campaign_id)
    if not c or c["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign_model.set_archived(campaign_id, False)
    return {"campaign_id": campaign_id, "archived": False}
```

**Step 5: Frontend — Reports tab sub-tabs** in `sidebar.html` (inside the existing Reports tab content):
```html
<div class="reports-subtabs">
  <button class="sub-tab active" data-archived="false" data-i18n-key="reportsTabActive">Active</button>
  <button class="sub-tab" data-archived="true" data-i18n-key="reportsTabArchived">Archived</button>
</div>
```

In `sidebar.js`, update `loadReports` to accept `{ archived: bool }` and bind the subtab clicks. Add an archive action button next to each campaign row.

**Step 6: i18n keys** (en + 9 locales): `reportsTabActive`, `reportsTabArchived`, `btnArchive`, `btnUnarchive`, `archiveConfirm`.

**Step 7: Commit**
```bash
git add backend/migrations/005_campaign_archived.sql backend/models/campaign.py \
        backend/routers/campaigns.py backend/tests/test_campaigns_validation.py \
        extension/sidebar.html extension/sidebar.js extension/_locales/
git commit -m "feat: campaign archive (DB flag + Active/Archived tabs + archive/unarchive)"
```

---

### Task D.3: Onboarding wizard (3-step, first-run only)

**Files:** `extension/sidebar.html`, `extension/sidebar.js`, `extension/styles/sidebar.css`

**Step 1:** Add to sidebar.html (hidden by default):
```html
<div id="onboarding-overlay" class="om-modal-overlay" style="display:none">
  <div class="om-modal">
    <div class="om-modal-header">
      <span data-i18n-key="onbTitle">Welcome to OutMass</span>
      <button type="button" class="om-modal-close" id="onb-skip">×</button>
    </div>
    <div id="onb-step-body"></div>
    <div class="om-modal-footer">
      <button id="onb-prev" class="btn-secondary">Back</button>
      <span id="onb-progress">1 / 3</span>
      <button id="onb-next" class="btn-primary">Next</button>
    </div>
  </div>
</div>
```

**Step 2:** In sidebar.js, add:
```javascript
var ONB_STEPS = ["onbStep1", "onbStep2", "onbStep3"]; // i18n keys for each step body
var _onbStep = 0;

function showOnboardingIfFirstRun() {
  chrome.storage.local.get("onboardingDone", function (r) {
    if (r.onboardingDone) return;
    _onbStep = 0;
    renderOnbStep();
    document.getElementById("onboarding-overlay").style.display = "flex";
  });
}
function renderOnbStep() {
  var body = document.getElementById("onb-step-body");
  body.textContent = t(ONB_STEPS[_onbStep]);
  document.getElementById("onb-progress").textContent = (_onbStep + 1) + " / " + ONB_STEPS.length;
  document.getElementById("onb-prev").disabled = _onbStep === 0;
  document.getElementById("onb-next").textContent = _onbStep === ONB_STEPS.length - 1 ? t("onbFinish") : t("onbNext");
}
document.getElementById("onb-next").addEventListener("click", function () {
  if (_onbStep < ONB_STEPS.length - 1) { _onbStep++; renderOnbStep(); return; }
  chrome.storage.local.set({ onboardingDone: true });
  document.getElementById("onboarding-overlay").style.display = "none";
});
document.getElementById("onb-prev").addEventListener("click", function () {
  if (_onbStep > 0) { _onbStep--; renderOnbStep(); }
});
document.getElementById("onb-skip").addEventListener("click", function () {
  chrome.storage.local.set({ onboardingDone: true });
  document.getElementById("onboarding-overlay").style.display = "none";
});

// Call at end of main initialization
showOnboardingIfFirstRun();
```

**Step 3: i18n** (en + 9 locales):
```json
  "onbTitle": { "message": "Welcome to OutMass" },
  "onbStep1": { "message": "Step 1 — Upload a CSV of recipients. First column must be 'email'." },
  "onbStep2": { "message": "Step 2 — Write your subject and body. Use {{firstName}} to personalize." },
  "onbStep3": { "message": "Step 3 — Click Preview or Test Send to double-check, then Send." },
  "onbNext": { "message": "Next" },
  "onbFinish": { "message": "Finish" }
```

**Step 4: Commit**
```bash
git add extension/sidebar.html extension/sidebar.js extension/styles/sidebar.css extension/_locales/
git commit -m "feat: 3-step first-run onboarding wizard"
```

---

### Task D.4: Export campaign list as CSV

**File:** `extension/sidebar.js` (Reports tab), new endpoint in backend.

**Step 1:** Since we already have `/campaigns/{id}/export` (per-campaign contacts), add a new `/campaigns/export-list`:

```python
@router.get("/export-list")
async def export_campaign_list(user: dict = Depends(get_current_user)):
    """Export all of the user's campaigns + summary stats as CSV."""
    campaigns = campaign_model.list_campaigns(user["id"], archived=False) + \
                campaign_model.list_campaigns(user["id"], archived=True)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name", "status", "created_at", "sent_count",
                     "open_count", "click_count", "total_contacts", "archived"])
    for c in campaigns:
        writer.writerow([
            c.get("name", ""), c.get("status", ""), c.get("created_at", ""),
            c.get("sent_count", 0), c.get("open_count", 0), c.get("click_count", 0),
            c.get("total_contacts", 0), c.get("archived", False),
        ])
    output.seek(0)
    return {"csv_data": output.getvalue(), "filename": "outmass_campaigns.csv"}
```

**Step 2:** Frontend — add a "Export All" button in the Reports tab header:
```html
<button id="btn-export-list" class="btn-secondary" data-i18n-key="btnExportList">Export All</button>
```

**Step 3:** sidebar.js:
```javascript
var btnExportList = document.getElementById("btn-export-list");
if (btnExportList) {
  btnExportList.addEventListener("click", function () {
    chrome.runtime.sendMessage({ type: "EXPORT_CAMPAIGN_LIST" }, function (resp) {
      if (!resp || resp.error) { alert(resp ? resp.error : "export failed"); return; }
      var data = resp.data || resp;
      var blob = new Blob(["\uFEFF" + data.csv_data], { type: "text/csv;charset=utf-8" });
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a"); a.href = url; a.download = data.filename;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
    });
  });
}
```

**Step 4:** Add `EXPORT_CAMPAIGN_LIST` handler in background.js (mirror existing EXPORT_CAMPAIGN_CSV).

**Step 5: i18n** `btnExportList`.

**Step 6: Commit**
```bash
git add backend/routers/campaigns.py extension/sidebar.html extension/sidebar.js \
        extension/background.js extension/_locales/
git commit -m "feat: export all campaigns + stats as CSV"
```

---

## PHASE 5 — Final Verification

### Task F.1: Run full test suite
```bash
npm run test:unit   # expect 80+ passed (70 baseline + 10+ new)
npm run test:e2e    # expect 48 passed (no UI regression)
```

### Task F.2: Manual smoke test
1. Load unpacked extension.
2. Upload a CSV with duplicate emails → confirm dedup message.
3. Upload CSV missing `email` column → confirm error.
4. Write subject with `{{firstName}` → Test Send → confirm 400 error shown.
5. Click Preview → confirm modal renders HTML.
6. First-run: verify onboarding wizard shows.
7. Reports tab → click archive → verify campaign moves to Archived sub-tab.

### Task F.3: Update HANDOFF.md
Tick every box under `🟡 Launch Sonrası Yapılacaklar` that is now done.
Commit:
```bash
git commit -m "docs: HANDOFF — mark post-launch A/B/C/D items complete"
```

---

## APPENDIX: i18n Translations

For every new key in `en/messages.json`, add a translation to each of:
`tr`, `de`, `fr`, `es`, `ru`, `ar`, `hi`, `zh_CN`, `ja`.

Key list (all new keys this plan introduces):

```
btnTestSend, testSendPrompt, testSendSuccess, testSendFailed, testSendNeedsContent,
warnSubjectLong, warnAllCaps, warnSpamWords, warnTooManyLinks, warnContinueAnyway,
csvErrTooLarge, csvErrEncoding, csvErrNoEmailColumn, csvDupRemoved,
campaignNameDuplicate,
previewSubjectLabel,
reportsTabActive, reportsTabArchived, btnArchive, btnUnarchive, archiveConfirm,
onbTitle, onbStep1, onbStep2, onbStep3, onbNext, onbFinish,
btnExportList
```

Provide translations inline during the relevant task. Use existing strings in the same file as tone reference (TR is informal "Sen", DE is informal "Du", AR uses `؟` and `،` punctuation, RU uses "Вы").

---

## Execution Handoff

Plan saved to `docs/plans/2026-04-17-post-launch-quality.md`.

Given the size (~5 commits in Phase 1, ~5 commits in Phase 2, ~2 in Phase 3, ~4 in Phase 4), I'll execute linearly in this session — one task at a time, TDD for backend, test-after for UI, running `npm run test:unit` after each backend commit. i18n bulk-translation commit happens at the end of each phase.
