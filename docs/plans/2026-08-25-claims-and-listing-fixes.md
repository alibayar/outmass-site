# Claims and listing fixes — found 2026-08-25

Everything the Softonic submission turned up, in one place. Most of it came
from a single habit: before pasting our own published copy onto a new surface,
read it line by line against the code. Two sentences did not survive that.

Companion entries live in `backlog.md` (Softonic / SourceForge sections);
this file is the checklist.

---

## A. Claims that are wrong and currently live

### A1. "We never store the content of your emails on our servers" — false

**Where:** `docs/store-listing/listings.json` → generated into all 12
`descriptions/*.txt` → published on the **Chrome and Edge store listings**.

**Why it is false:** `create_campaign` writes `subject` and `body` into the
`campaigns` table (`backend/models/campaign.py:57`). It must: scheduled
sending, follow-ups and campaign reports all read that row afterwards. The
uploaded list lives in `contacts` for the same reason.

**Replacement** (already used on Softonic, and consistent with the 08-24 blog
post which says the same thing):

> 🔒 YOUR ACCOUNT, YOUR SENDING
>
> OutMass sends through your own Microsoft account using OAuth 2.0 and the
> official Graph API — no third-party sending servers and no shared IP pools,
> so recipients see a normal email from you. Your campaign is stored on our
> servers, because scheduled sending, follow-ups and campaign reports cannot
> work otherwise. Reply detection records only that a reply arrived, never its
> contents.

**Status:** fixed on Softonic (`docs/store-listing/softonic-en.txt`). NOT yet
fixed at source. **Needs Ali's decision — see E1.**

### A2. "stop automatically as soon as someone replies" — overstated

**Where:** same source, same 12 languages, same two store listings.

**Why:** follow-ups dispatch **hourly** (`celery_app.py:129`); reply detection
runs **once a day at 05:00 UTC**; the follow-up filter reads the `replied_at`
the detector stamps (`followup_worker.py:178`). A reply arriving at 06:00 is
invisible until the next morning, so a follow-up falling due inside that window
still goes to someone who already answered — which the worker's own docstring
calls "the #1 thing users expect follow-ups to never do".

**Replacement:** "stop automatically once a reply is detected". The feature
list already carries a separate "daily Inbox scan" line, so the mechanism is
disclosed either way.

**Status:** fixed on Softonic. Source fix pending with A1.

### A3. SourceForge carries the sharper version of A2

Their published description says "stop **the moment** someone replies". Edit it
when the page claim is approved. The same page also needs its empty "Videos and
Screen Captures" section filled — see `backlog.md`.

---

## B. Copy that is stale or aimed at the wrong reader

### B1. "BUILT FOR: Founders and SDRs running outbound"

Not false, but not who actually uses OutMass. Measured 2026-08-24 by recipients
over 120 days: an education organisation (5,599), a medical-supply distributor
(2,816), personal Outlook accounts (607 across 36 sends), a PR agency (519), a
staffing firm (375). The dominant job is **an organisation emailing its own
list**. Reordered version, in use on Softonic:

> • Organisations emailing their own list — schools to parents, suppliers to
>   customers, associations to members
> • PR and agency teams reaching journalists or clients from their existing mailbox
> • Founders and SDRs running outbound from Outlook
> • Anyone who has tried to mail-merge in Outlook and given up

Belongs to the 0.2.3 store-listing pass either way.

### B2. SoftwareSuggest says 11 languages; the product ships 13

Submitted 08-19 as 11 (14 locale files, of which `zh` and `zh_CN` are the same
language). Understated rather than oversold, so not urgent — fix on the next
portal visit.

### B3. `CLAUDE.md` said a new locale key goes into 11 files

There are 14. Fixed 2026-08-25 (`4c67f2e`). The test auto-discovers the
directory, so nothing was ever broken — but a stale number in the instruction
file is exactly what mis-stated the free quota in July.

---

## C. Softonic taxonomy, recorded so nobody rediscovers it

| Field | Value | Why |
|---|---|---|
| Platform | **Web apps** | The only shelf that does not want a binary. No .crx or .zip is ever uploaded. |
| Category | **Productivity** | The field defaults to "Browsers", which would list us as a browser. |
| Subcategory | **E-mail Clients** | Closest shelf; Office Suites and Document Management lose the reader. |
| License | **Subscription-based** | No "Freemium" option exists. Between understating and overstating we understate: "Free" would walk users into a paywall they were not warned about, while the description says "Free — 250 emails/month, forever" two lines down. |
| Compatible with | **Chrome only** | The list offers Internet Explorer but not Edge. Ticking IE would be a false claim (MV3 does not run there); Edge simply cannot be declared. |
| Supported languages | **11 selected** | Their taxonomy has no zh_TW and no pt_BR. Not a contradiction with "13 UI languages" in the description: the field states what Softonic can express, the text states what the product has. |
| Publication | Automatic | Publishes as soon as the review approves. |
| Description | Ours, pasted | Their "Create with assistant" AI generator is declined by default: it writes claims nobody audited. |
| Translations | Skipped for now | Every added language is another copy of A1 until the source is fixed. |

**Assets the form demanded, and what was done:**

- Icon ≥512×512 — we had 200. `docs/ss/logo-512.png`, redrawn from the
  generator's own numbers (`docs/store-listing/make-logo-512.py`), not upscaled.
- Screenshots ≥1920×1080 — our captures are 1280×800.
  `docs/store-listing/frame-screenshots.py` places each capture at **native
  resolution** on a larger canvas with a soft shadow, so no UI text is
  resampled. Two sets exist: `-1920.jpg` and `-2048.jpg`, the second for
  validators that read "at least 1920x1080" as strictly greater.

---

## D. Checked and found FINE — do not re-open

- **30-day money-back guarantee.** `refund.html` matches the store copy
  including both exclusions (more than 30 days, ToS termination). Flagged on
  08-18, verified 08-25, no action.
- **"13 languages" on the pricing page.** Internally consistent: 13 UI
  languages listed by name, AI writer in 12, unsubscribe pages in 12, and 14
  locale files because `zh` duplicates `zh_CN`.

---

## E. Decisions that are Ali's

1. **Fix `listings.json` now, or wait for 0.2.3?** A1 is a privacy claim that
   is the opposite of what the code does, live in 12 languages on two stores.
   Correcting store listing text needs no version bump and no new package — it
   is a listing edit plus whatever review each store runs. Recommendation: ship
   it as its own change rather than riding along with 0.2.3, and hold every
   translated directory listing until it lands.
2. **Close the reply window?** Either scan a campaign's replies immediately
   before dispatching its follow-ups, or move detection to hourly. If the
   window closes, A2's original sentence becomes true instead of needing
   softening. Behaviour change → needs approval.
3. **Free-tier 250-row upload ceiling** (carried from 08-24): the club and
   school lists our newest blog post is written for cannot be trialled.
