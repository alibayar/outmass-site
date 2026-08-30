# Railway environment — the one place

Internal. Lives in `docs/plans/` because that is the only directory
`docs/_config.yml` keeps out of the public Jekyll site, and this file names
every setting the infrastructure has. A test enforces both halves of that
(`backend/tests/test_env_registry.py`).

**Source of truth is `backend/utils/env_registry.py`, not this file.** The
tables below are generated from it, and a test fails if they disagree or if
`config.py` grows a setting neither knows about.

---

## Why this exists

Railway gives each service its own Variables panel. We run three off one image
— **web**, **worker**, **beat** (see `backend/Procfile`) — so every setting
exists in triplicate and is copied by hand. That has cost us three times:

- **2026-07** — the Telegram credentials were on web and not on the worker, so
  the daily report simply never arrived. Nothing errored. It was just absent.
- **2026-08-10** — the worker was still carrying TEST Stripe keys beside the
  production database. `backend/utils/config_guard.py` exists because of this.
- **2026-08-08** — `BACKEND_URL` could not be confirmed on any service, and it
  is what stamps tracking pixels and unsubscribe links into outgoing mail. A
  wrong value there is invisible to us and broken for every recipient.

All three were silence. None of them would have produced a support ticket.

---

## What to do (Ali, Railway dashboard)

Railway supports **project-level Shared Variables**: define once, reference
from every service. That collapses three copies into one.

1. Railway → the OutMass project → **Settings → Shared Variables**.
2. Add every variable from the two tables below, at project level, with its
   production value.
3. In **each** of the three services → Variables → replace the local copy with
   a reference: `${{shared.NAME}}`.
4. Redeploy all three.
5. Confirm from the logs, not from the dashboard: each service now logs its
   own startup checks, and an ENV GAP alert names anything still missing.

**Do not share** the values Railway injects itself — PORT is per-service and
assigned at boot, and the RAILWAY_-prefixed variables are set by the platform.
Sharing those would override what the platform provides.

There is nothing in the list below that legitimately differs between services.
If a value ever needs to differ, it is a new setting, not a divergent copy.

---

## What now watches this

Both entry points run the startup checks — `backend/main.py` **and**
`backend/workers/celery_app.py`. Until 2026-08-13 only the web service did,
which meant the guard written after a *worker* misconfiguration was not
running on the worker. Each service now reports what it alone is missing:

- `config.py` raises on `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` and
  `JWT_SECRET` — a service without those does not boot, so nobody has to
  remember them.
- `check_stripe_mode` catches a test Stripe key against the production
  database, and the reverse.
- `check_plan_price_ids` catches a missing price id, which empties the plan
  catalogue and silently reverts the panel to its old single Upgrade button.
- `check_env` names anything else in the first table that this service needs
  and does not have.

Every one of those reports to the log and to Telegram, and none of them can
refuse to boot: a billing misconfiguration must not be able to take down
sign-in and sending.

---

### Silent when missing — these are the ones that have cost us

| Variable | Services | Silent | What stops working |
|---|---|---|---|
| `STRIPE_SECRET_KEY` | web | **yes** | checkout, the portal and every webhook stop working; the panel keeps its Upgrade button and nobody can pay |
| `STRIPE_WEBHOOK_SECRET` | web | **yes** | every Stripe webhook is rejected — a customer pays and never gets their plan |
| `STRIPE_STARTER_PRICE_ID` (or `STRIPE_STANDARD_PRICE_ID`) | web | **yes** | the plan catalogue comes back empty and the panel silently falls back to its old single hardcoded-Starter button |
| `STRIPE_PRO_PRICE_ID` | web | **yes** | same as the Starter price id — the catalogue is all-or-nothing |
| `AZURE_CLIENT_SECRET` | web, worker | **yes** | web: the OAuth token exchange fails and nobody can sign in. worker: every token refresh returns invalid_client, which ms_token treats as a reauth reason — so every active user is flagged requires_reauth AND emailed a 'reconnect your account' notice that is not true, while scheduled sends, follow-ups and reply detection all stop |
| `REDIS_TLS_VERIFY` | web, worker, beat | no | defaults to false, keeping the certificate check off; set true to verify the broker (2026-08-27) |
| `REDIS_URL` | worker, beat | **yes** | the worker talks to a localhost broker that is not there — no scheduled send, no follow-up, no auto-resume, and no error anywhere |
| `BACKEND_URL` | web, worker, beat | **yes** | tracking pixels, click links, unsubscribe links and Stripe redirect URLs are stamped into outgoing mail pointing at localhost |
| `MAILERSEND_API_KEY` | web, worker | **yes** | every transactional email is skipped — welcome, reconnect, quota-cap, plan-drop, the 30-day nudge and feedback forwarding |
| `TELEGRAM_BOT_TOKEN` | web, worker, beat | **yes** | every operator alert is dropped, including the ones that report a misconfiguration — this is how the daily report went missing |
| `TELEGRAM_CHAT_ID` | web, worker, beat | **yes** | as above |
| `POSTHOG_API_KEY` | web, worker | **yes** | server-side funnel events stop; the funnel looks smaller than it is and nothing says so |
| `ANTHROPIC_API_KEY` | web | **yes** | the AI writer fails for Pro users |
| `POSTHOG_PERSONAL_API_KEY` | worker | **yes** | the daily report cannot read funnel numbers |
| `REPORT_OWNER_EMAILS` | worker | **yes** | the daily report is generated and sent to nobody |

### Loud, or with a default that is genuinely right

| Variable | Services | Silent | If unset |
|---|---|---|---|
| `SUPABASE_URL` | web, worker, beat | no | config.py raises — the service will not start |
| `SUPABASE_SERVICE_ROLE_KEY` (or `SUPABASE_KEY`) | web, worker, beat | no | config.py raises unless the legacy key is set instead |
| `JWT_SECRET` | web, worker, beat | no | config.py raises — the service will not start |
| `STRIPE_PORTAL_CONFIG_ID` | web | no | Stripe's default portal configuration is used |
| `STRIPE_TEAM_PRICE_ID` | web | no | the unsold Team tier is unbuyable, which it already is |
| `AZURE_CLIENT_ID` | web, worker | no | falls back to the live app registration id; the worker needs it for token refresh (see `AZURE_CLIENT_SECRET`) |
| `AZURE_REDIRECT_URI` | web | no | derived from the backend URL |
| `AZURE_EXTENSION_ID` | web | no | falls back to the store extension id |
| `ALLOWED_EXTENSION_IDS` | web | no | falls back to the store extension id |
| `CORS_ORIGINS` | web | no | falls back to the store extension plus localhost |
| `POSTHOG_HOST` | web, worker | no | defaults to the EU ingest host |
| `POSTHOG_API_HOST` | worker | no | defaults to the EU query host |
| `POSTHOG_PROJECT_ID` | worker | no | defaults to the live project |
| `REPORT_HEALTH_URL` | worker | no | the report skips its health probe |
| `REPORT_TRIGGER_KEY` | web | no | the manual report trigger endpoint stays closed |
| `MAILERSEND_FROM_EMAIL` | web, worker | no | defaults to support@getoutmass.com |
| `MAILERSEND_FROM_NAME` | web, worker | no | defaults to the support sender name |
| `MAILERSEND_TO_EMAIL` | web | no | feedback forwarding defaults to support@getoutmass.com |
| `FIRST_SIGNIN_INCLUDE_MAIL_READ` | web, worker | no | defaults to true. Safe to flip since the version gate (0.2.3+): older clients keep the wide ask whatever it says, so the flip no longer waits on store publication |
| `FREE_PLAN_MONTHLY_LIMIT` | web, worker | no | defaults to 250 |
| `STARTER_PLAN_MONTHLY_LIMIT` | web, worker | no | defaults to 2500 |
| `PRO_PLAN_MONTHLY_LIMIT` | web, worker | no | defaults to 10000 |
| `FREE_UPLOAD_ROW_LIMIT` | web | no | defaults to 250; in force for clients older than 0.2.3, and while UPLOAD_LIMIT_FOLLOWS_QUOTA is off |
| `STARTER_UPLOAD_ROW_LIMIT` | web | no | defaults to 2500; in force for clients older than 0.2.3, and while UPLOAD_LIMIT_FOLLOWS_QUOTA is off |
| `PRO_UPLOAD_ROW_LIMIT` | web | no | defaults to 10000; in force for clients older than 0.2.3, and while UPLOAD_LIMIT_FOLLOWS_QUOTA is off |
| `UPLOAD_LIMIT_FOLLOWS_QUOTA` | web | no | defaults to false, and no longer needs flipping: the client's version decides (0.2.3+ gets the single ceiling). True is a one-directional override that lifts it for older clients too |
| `CSV_UPLOAD_ROW_LIMIT` | web | no | defaults to 10000; the single ceiling used once the flag is on |
| `AI_GENERATION_MONTHLY_LIMIT` | web | no | defaults to 50 |
| `PLAN_DROP_NOTICE_DAYS` | web | no | defaults to 14 |
| `AUTH_RESUME_MAX_AGE_DAYS` | web, worker | no | defaults to 7 |
| `AUTO_RESUME_DORMANT_DAYS` | worker | no | defaults to 30; owner must have been seen this recently for auto-resume to continue |
| `AUTO_RESUME_BACKOFF_HOURS` | worker | no | defaults to 6; minimum gap between attempts on the same partial campaign |
| `RAILWAY_GIT_COMMIT_SHA` | web | no | injected by Railway itself, not set by hand; absent means the health endpoint answers 'unknown', which is honest rather than misleading |
| `INACTIVITY_NUDGE_ENABLED` | worker | no | defaults to false, so the nudge emails do not go out until it is set |
| `INACTIVITY_NUDGE_DAYS` | worker | no | defaults to 30 |

The plan and upload limits are the numbers CLAUDE.md points at: `config.py` is
their single source, and nothing else in the codebase may write them down.

### Read by config.py, consumed by nothing

Listed so nobody copies them into a third service believing they matter. Kept
rather than deleted — two of them configure inactivity tiers that are designed
but not built.

| Variable | Status |
|---|---|
| `FRONTEND_URL` | nothing reads it |
| `INACTIVITY_PAUSE_DAYS` | the 60-day pause tier is not implemented |
| `INACTIVITY_CANCEL_DAYS` | the 90-day cancel tier is not implemented |
| `INACTIVITY_AUTOCANCEL_ENABLED` | the switch for those two tiers; nothing reads the value yet |

---

## Adding a setting later

Add it to `backend/utils/env_registry.py` in the same commit that adds the
`os.getenv` call — the test suite will not let you do otherwise — saying which
services need it and, in plain words, what stops working when it is absent.
Then regenerate the table here. The value goes in Shared Variables, once.
