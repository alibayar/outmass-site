# Store Featuring & Badges Playbook

Verified 2026-07-19 against official docs. Internal — `docs/plans/` is
excluded from the public site. Decision (Ali, 2026-07-19): **parked for
now** — revisit per the triggers below, not a calendar date.

## Chrome Web Store

### Featured badge (self-nomination EXISTS)
- **Where:** [One Stop Support](https://support.google.com/chrome_webstore/contact/one_stop_support)
  → "My item" → "I want to nominate my extension for a Featured badge and
  be eligible for merchandising" (merchandising = collections/homepage).
- **Evaluated on** (manual review by Chrome team — NOT user counts):
  1. Technical best practices (MV3 ✓, minimal permissions ✓, user privacy ✓).
  2. Store listing quality: images/screenshots + detailed description.
- **Nomination prerequisites:** published & public ✓ · English ✓ · no
  policy violations ✓ · you own it ✓ · **core features accessible without
  additional credentials or payments** ⚠️ — OutMass needs a Microsoft
  sign-in. Defensible (any free MS account works, no payment), but this is
  the likeliest rejection reason. If nominated, the form text should
  preempt it: reviewer can use any personal outlook.com account, free tier.
- **No penalty for rejection**; can improve and be re-evaluated.
- Docs: https://developer.chrome.com/docs/webstore/discovery

### Established Publisher badge (automatic, no application)
- Conditions: publisher identity verified + a few months of clean policy
  track record. **Action now: confirm publisher verification is complete
  in the CWS dashboard** — the clock runs from there.

### What "fast support" converts to on CWS
- No responsiveness badge exists. The store-visible levers:
  - **Developer replies to reviews are public** — answer every review
    fast, solution-first.
  - **Ratings** drive ranking and the Featured case. Fast support's store
    currency = the 5-star review it earns.

## Edge Add-ons

- **Featured badge:** automatic selection based on alignment with
  [best practices](https://learn.microsoft.com/en-us/microsoft-edge/extensions/developer-guide/best-practices)
  (security, privacy, performance, UX). No application form — the lever is
  staying aligned (we are: MV3, minimal hosts, filled privacy fields).
  Docs: https://learn.microsoft.com/en-us/microsoft-edge/extensions/
- **Homepage collections:** Edge team accepts featuring requests via
  Partner Center support ticket / their developer community channels.
  Far less crowded store → much more attainable than CWS featuring.

## Triggers to revisit (not dates)

1. **Listing polish first** (prerequisite for any nomination): refresh
   screenshots to show current UI (merge-tag chips, daily cap, welcome
   page), tighten description. Small task, do anytime.
2. **CWS Featured nomination** when: listing refreshed AND ~10+ reviews
   with ≥4.5 avg. Note the badge is a growth INPUT (discovery
   accelerator), not a reward for scale — evaluated on quality, not user
   count. Waiting for "100s of users" inverts its purpose; the review
   count matters only to strengthen the impression, not as a formal bar.
3. **Review asks** are decoupled from user count entirely — they run on
   happy moments, not scale. Standing candidates: users we personally
   rescued/helped (Mary, bellmed, hrcargo, Lucia as of 07-19). One-line
   personal async email at their next happy moment. Gift-test discipline
   applies (see memory: gift_learning_or_crutch).
4. **Edge collection ticket** when Edge 0.1.26 is approved and stable.

## Form-ready snippets (draft when triggered)

- CWS nomination pitch: Outlook-native mail merge (GMass-for-Outlook gap),
  MV3, minimal permissions, 11 locales, sends via user's own Graph
  account (nothing proxied), free tier fully functional with any
  Microsoft account (no payment/extra credentials beyond the user's own
  mailbox — inherent to the product category).
