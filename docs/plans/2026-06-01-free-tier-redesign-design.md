# Free Tier Redesign — Design

> **Date:** 2026-06-01
> **Status:** Approved (brainstorming)
> **Next:** writing-plans → implementation plan
> **Version:** v0.1.11 (extension quota display changes), backend config + docs

## Problem

OutMass's free tier is **50 emails/month** — far too narrow for activation:
- GMass (closest competitor) gives **50/day (~1.500/month)** on its free tier.
- Industry data: a *typical mail-merge campaign is 200-300 recipients*; an active cold-emailer sends *600-1.200/month*.
- Our first active user (Abdul) sent **49 emails in a single campaign** — exhausting nearly the entire monthly limit in one session. He hit the wall before he could form a habit.
- OutMass's send cost is **~zero** (mail goes through the user's own Microsoft Graph quota), so a narrow free tier is purely a conversion lever, not a cost constraint — and right now it's strangling activation when we have **0 paid users** and need usage/trust first.

## Decision

Raise the free tier and align upload limits, using a **data-backed, asymmetry-safe** approach.

**Asymmetry principle (the core rationale):** Raising a limit is always positive (users love it, PR-friendly); lowering one is always negative (churn, "they took it back"). So **start moderate, raise later from data** — never the reverse. We start at 250 (revenue-friendly, covers most typical campaigns) and can bump to 300+ later as a *positive* move if data shows activation suffers.

| Plan | Monthly | Upload rows | Price | Change |
|---|---|---|---|---|
| **Free** | 50 → **250** | 100 → **250** | $0 | 5× |
| **Starter** | 2.000 → **2.500** | 2.000 → **2.500** | $9 | +500 (positive) |
| **Pro** | 10.000 (same) | 5.000 → **10.000** | $19 | upload aligned |

### Rationale
- **Free 250** = covers most of a typical 200-300 mail-merge campaign → user can run ~1 full campaign, see value, form a habit (activation). 250 vs 300 is marginal for activation, but 250 keeps slightly more conversion pressure (revenue priority) and leaves headroom to raise later.
- **Upload = monthly limit** on every plan: a user can spend their whole monthly allowance in one campaign. The old free upload cap (100) split a typical campaign in two — itself an activation blocker.
- **Starter 2.000 → 2.500**: keeps a clean **10× ratio** vs free 250, and increases paid value (vs GMass $29.95, our $9/2.500 is more attractive). Positive for current/future paid users.
- **Conversion preserved**: active users send 600-1.200/month → free 250 won't suffice → natural upgrade to Starter. Free 250 vs Paid 2.500 = 10× → paid remains clearly worth it.

### Out of scope (YAGNI)
- Viral "Sent with OutMass" footer — rejected (unprofessional for B2B; ROI unprovable at current scale; revisit separately with tracking when 50+ active users).
- Daily-limit model (GMass style) — rejected (needs new reset mechanism; monthly is simpler + more flexible; would erode paid value if set near 1.500).
- New pricing tiers — 2 paid tiers are enough.

## User Impact (CLAUDE.md)

- **Pure positive**: every limit goes UP. Nobody loses anything.
  - Abdul (free, 49/50) → 49/250, instantly regains 201 sends.
  - Abid (starter promo) → 2.500 allowance.
- **Notification**: optional "good news" — since it's strictly beneficial, no mandatory banner. Could mention in release notes / a friendly note to active users (ties into Abdul outreach).
- **Reversible**: config-only change; technically reversible, but per the asymmetry principle we will NOT lower it.
- **Backward compat**: legacy clients unaffected (limits live server-side; old extensions just see a higher cap).

## Where the Limits Live (all must change together)

The numbers are duplicated across backend + frontend + docs. All must move in sync or the UI will lie:

1. **Backend** `backend/config.py`: `FREE_PLAN_MONTHLY_LIMIT`, `STARTER_PLAN_MONTHLY_LIMIT`, `FREE_UPLOAD_ROW_LIMIT`, `STARTER_UPLOAD_ROW_LIMIT`, `PRO_UPLOAD_ROW_LIMIT`. (`STANDARD_PLAN_MONTHLY_LIMIT` aliases Starter — auto-follows.)
2. **Backend** enforcement sites (`routers/campaigns.py` send-limit + upload-row checks) — these read the config constants, so they follow automatically; verify no hardcoded numbers.
3. **Frontend** `extension/sidebar.js`: HARDCODED quota numbers (~line 640-644, 718-719: `plan === "pro" ? 10000 : plan === "starter" ? 2000 : 50`). Must update to 250/2.500/10.000. **This is the easy-to-miss part** — if not updated, the sidebar shows the wrong limit.
4. **Frontend** `extension/popup.js`: any plan/limit display.
5. **Docs** `docs/pricing.html` (getoutmass.com): the public pricing page likely states "50 emails/month" etc.
6. **Store listing** `docs/store-listing/listings.json`: feature bullets may mention the free limit (10 locales).
7. **i18n** `extension/_locales/*`: any quota message with a hardcoded number.
8. **Monthly reset**: verify `emails_sent_this_month` actually resets monthly (find the reset logic); the limit raise assumes a working monthly reset.

## Testing

- Backend unit tests asserting the new limits in the send + upload gates (FakeSupabase pattern). Update any existing test that hardcodes 50/2.000/100.
- Frontend: manual — sidebar quota shows "X / 250" for free, correct for starter/pro.
- E2E visual regression: quota text changes may shift screenshots — re-run, update baselines only if the change is expected/correct.

## Rollout

- Backend config → Railway deploy (instant, server-authoritative).
- Extension → v0.1.11 (sidebar/popup quota display) → Web Store upload.
- Docs/pricing → GitHub Pages (instant).
- Order: backend + docs can ship first (limits take effect immediately, server-side); extension display catches up on next Web Store approval. Since it's all UP, no mid-flight breakage.
