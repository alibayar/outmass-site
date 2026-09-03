# OutMass — Backlog

Identified during the 2026-06-23/24 work but not yet done. Living doc — update
status as items land. (Internal: `docs/plans/` is excluded from the public Jekyll
site, so this never ships to getoutmass.com.)

**Status:** ⬜ todo · 🔧 in progress · ✅ done · ⏸️ deferred

> **Audited 2026-08-08.** Every open entry was re-checked against the code, and
> most of them had drifted: three were done and still marked open, two were
> partly done in ways that read as fully done, and one heading carried a second
> unrelated item that had been invisible for five weeks. One entry ("unit-tests
> green") had gone from true to false without anyone editing it, which is how a
> ten-day CI outage stayed hidden.
>
> Two habits that would have prevented most of it:
> - **A ✅ must not contain an open action.** If the remaining step is Ali's, it
>   is a separate ⬜, not a sentence at the end of a done entry.
> - **Pin claims to evidence, not to memory.** Counts (locale keys, listing
>   languages, send loops) age silently; every number here now carries the date
>   it was measured. Three of them were wrong by the time they were re-read.
>
> Current release state lives in the handoffs, not here — see
> `handoff-2026-08-08.md`. Entries pinned to a version number go stale within
> the week.

---

### Two infrastructure hygiene items, queued 2026-08-27

Both surfaced from the beat's own logs while verifying the variable cleanup.
Neither is urgent; both are the kind of thing that only ever gets found while
looking at something else.

**1. Redis certificate verification — answered 2026-08-27, awaiting one variable.**

`workers/celery_app.py:117-125` sets `ssl_cert_reqs=CERT_NONE` for any
`rediss://` broker, and both the beat and the worker log Celery's warning on
every boot: no validation of the broker's identity, vulnerable to a
man-in-the-middle. The justification in the comment is that Upstash uses a
certificate outside standard CA bundles, sourced to
`upstash.com/docs/redis/howto/celeryintegration` - **which now returns 404**.
So the reason is an unverified quote from a page that no longer exists.

The channel carries the task queue. Someone able to sit in the path could read
it and, having captured the broker password, enqueue tasks of their own. The
path is Railway to Upstash, so the practical likelihood is low - this is
hygiene, not an incident.

**Tested, and the comment was wrong.** Ali ran the handshake against the
production host with a default `ssl.create_default_context()`: **OK, TLSv1.3**.
Upstash's certificate verifies against the standard CA bundle, so the reason
for turning verification off no longer exists - if it ever did.

**Shipped as a switch, still off.** `REDIS_TLS_VERIFY` (default `false`) in
`workers/celery_app.py`. Off it produces byte-identical behaviour to before;
on it sets `CERT_REQUIRED` in both places that matter - the URL parameter
Celery's result backend demands, and the `broker_use_ssl` dict kombu hands to
redis-py. Both were checked to move together, since disagreeing would be worse
than either setting.

It defaults off rather than on because the failure mode is not a warning: a
broker we cannot connect to means no scheduled sends, no follow-ups, no
auto-resume, and nothing user-visible saying so. A laptop's CA bundle
verifying is not the container's CA bundle verifying.

**Ali's move, whenever convenient:** set `REDIS_TLS_VERIFY=true` on web, worker
and beat; watch one deploy connect (the beat log's `Sending due task` line
within five minutes is the proof); unset it if it does not. One variable, no
rollback deploy. The Celery man-in-the-middle warning disappears at the same
time, which is how you will know it took.

**2. Railway bakes secrets into the image as build args.**

Every build logs `SecretsUsedInArgOrEnv` for each service variable whose NAME
looks secret - on the 08-27 beat build: `JWT_SECRET`,
`SUPABASE_SERVICE_ROLE_KEY`, `TELEGRAM_BOT_TOKEN`, each twice (ARG line 11,
ENV line 12). Nixpacks declares service variables at build time, so they land
in the image's layer metadata rather than only in the running container.

Two things worth keeping about this:

- **The warning list is name-based, so it undercounts.** `REDIS_URL` carries
  the Upstash password and is never flagged, because "URL" is not a word the
  scanner looks for. Do not read the list as the inventory.
- **Deleting the eight unused variables shrank this by two real secrets.**
  `AZURE_CLIENT_SECRET` and `ANTHROPIC_API_KEY` match the same naming pattern
  and would have been baked into this image had they still been on the
  service. (Inferred from the pattern rather than observed - there is no
  before-build log to compare.) That is a second, unplanned reason the cleanup
  was worth doing.

The image sits in Railway's private registry, so exposure needs registry
access. The fix, if one exists, is on Railway's side: whether build-time
injection can be limited to the variables a build actually needs. Worth thirty
minutes of reading their docs before doing anything else.

**Also in that build log and NOT worth chasing:** `UndefinedVar: $NIXPACKS_PATH`
is nixpacks referencing its own variable a line before defining it. Cosmetic.

### AADSTS650051 is turning new users away at the front door

**Found 2026-08-27** with `backend/scripts/ask.py`, the first thing it was used
for. Both of that day's sign-ups hit it on their very first attempt:

| When (UTC) | Browser | Code | Our classification |
|---|---|---|---|
| 04:46:46 | Edge | AADSTS650051 / invalid_client | app_registration_rejected |
| 11:52:53 | Chrome | AADSTS650051 / invalid_client | app_registration_rejected |

Both failures are at `stage: authorize`, both carry `attributed_to: "app"`, and
the message our own code shows the user is **"This is our fault, not yours.
Please report it (AADSTS650051)"**.

**That attribution is wrong, and it is the finding.** Microsoft does not publish
650051, but their own Q&A threads describe it consistently: the consent action
fails because the service principal for the app already exists in the target
tenant while Entra has not finished provisioning it. A known transient that
clears on retry. Our data says the same thing — both users were in within eight
and thirty seconds of retrying, and a genuinely rejected registration fails
every time.

So we label Microsoft's provisioning race as our own registration being
refused, and then ask the user to report it. Nobody can act on that report,
and the one thing that does work — try again — is the thing the message does
not say.

Both users retried and got in within 8 and 30 seconds, which is the one
reassuring fact: a permanently broken registration would fail every time, so
this looks intermittent rather than dead. The same code appeared on 2026-08-10
and is the reason `_APP_LEVEL_ERRORS` exists in `routers/auth.py` at all.
Nothing else in the last fourteen days carries it.

**Why it matters more than the count suggests:** it fires on someone's first
ever interaction with the product, before they have any reason to persist. The
two who did retry were lucky or determined; there is no way to know how many
did not.

**Azure: probably nothing to fix.** A `stage: authorize` failure happens before
any secret is used — the client secret only enters at token exchange — so a
rotation or expiry cannot produce this, and an expiring secret would surface as
`stage: token_exchange`. Worth a five-minute sanity pass on the registration
(client id, redirect URI, supported account types, publisher verification, and
note the secret's expiry date for its own sake), but not a hunt.

**On 08-26 there was one real loss, not two.** Reading the properties rather
than the row count: 13:34 UTC was `consent_declined` after 34 seconds in the
window on Edge 0.2.2, with no `ms_auth_failed` from the backend — Microsoft
never redirected back, so the window was closed. That is the consent-page
abandonment we already know about. The 12:03 row looked like a second loss and
is not: `attempt_no 3`, extension 0.1.27, and `seconds: 1376725` — sixteen days
in the window. It is an old session finally reporting, not a visitor that day.

The lesson repeats: the count was two, the reading was one.

### 🟠 Store listing claims a privacy guarantee the code does not keep — GONE FROM EDGE 2026-09-03, STILL LIVE ON CHROME

**Edge verified 2026-09-03 09:15** on the public listing: the section is now
`🔒 SİZİN HESABINIZ, SİZİN GÖNDERİMİNİZ` and reads "Kampanyanız sunucularımızda
saklanır, çünkü zamanlanmış gönderim, takip e-postaları ve kampanya raporları
başka türlü çalışamaz." The reply-detection cadence and the 0.3.3 follow-up
line went live in the same publish.

**Chrome still serves the old text.** Ali pasted both stores the same night;
Edge published, Chrome's listing edit is queued behind its own review while the
0.3.3 package is already live. Two stores, one submission, different speeds —
worth knowing for every future claims fix: the package landing does not mean
the words did.

Closes when the Chrome listing serves the replacement. Check by fetching the
public page, not the dashboard.

**Text fixed 2026-09-01 (`3401ee8`) in all twelve locales. Never pasted into
either store.** Read off the live Chrome listing on 2026-09-03:

> 🔒 VERİLERİNİZ SİZDE KALIR
> OutMass gönderimleri sizin kendi Microsoft Graph API'nizden OAuth 2.0 ile
> yapar. **E-postalarınızın içeriği sunucularımızda tutulmaz.**

`create_campaign` writes `subject` and `body` to the `campaigns` table. The
sentence is still the opposite of what happens, still in twelve languages, and
still the strongest kind of claim to get wrong. `listings.json` and
`descriptions/*.txt` both carry the correct replacement and are in sync — the
only missing step is a human pasting them into Chrome Web Store and Edge
Partner Center.

> Marked ✅ on 2026-09-03 after I scanned `listings.json`, found no match, and
> reported it closed. Ali corrected me: *"dosyada güncel olabilir ama ben
> mağazada güncellemedim."* Reopened.
>
> **The repo is not the world.** A claims item is closed when the CLAIM is
> gone from where people read it, not when the file that generates it is
> fixed. For store copy the only proof is the live listing — fetch it. That
> was the second version of the same mistake in one night: first I trusted a
> backlog marker over the file, then I trusted the file over the store.

**Two more lines on the same paste** (all three ship together, one visit per
store per language):
- Reply detection: the store says `günlük Inbox taraması` / "daily Inbox
  scan"; it has run every six hours since `41e2e44` and the file already says
  `birkaç saatte bir`.
- Follow-ups: the store says the old `biri yanıt verdiği anda otomatik durur`.
  The file says `yanıt verenler atlanır`, and **0.3.3 went live on Chrome on
  2026-09-03**, so the audience wording needs the 0.3.3 rewrite before this
  paste — see the follow-up-claim item.

Full checklist, including everything else the Softonic submission turned up:
`2026-08-25-claims-and-listing-fixes.md`.

**Found 2026-08-25**, while preparing the Softonic description. Live on the
Chrome and Edge store listings in 12 languages, sourced from
`docs/store-listing/listings.json`:

> "We never store the content of your emails on our servers."

`create_campaign` inserts `subject` and `body` straight into the `campaigns`
table ([backend/models/campaign.py:57](../../backend/models/campaign.py)). It
has to: scheduled sending, follow-ups and campaign reports all read the stored
campaign later. The uploaded list lives in `contacts` for the same reason. So
the sentence is not a nuance we are shading - it is the opposite of what
happens, and it is the strongest kind of claim to get wrong.

What IS true, and what the blog post already says as of 08-24: sending goes
through the user's own Microsoft account over OAuth 2.0 and Graph, there is no
third-party sending server or shared IP pool, and reply detection stamps
`replied_at` without recording any reply content.

**Second, smaller claim in the same copy:** "follow-ups ... stop automatically
**as soon as** someone replies". Follow-ups dispatch hourly
([celery_app.py:129](../../backend/workers/celery_app.py)) while reply detection
runs once a day at 05:00 UTC, and the follow-up filter reads the `replied_at`
the detector stamps. A reply arriving at 06:00 is invisible until the next
morning, so a follow-up due in that window still goes out to someone who
already answered - which the worker's own docstring calls "the #1 thing users
expect follow-ups to never do".

**Actions:**
1. Softonic gets corrected copy today (`softonic-en.txt`) - do not propagate.
2. Fix `listings.json` at the source and regenerate all 12 descriptions, then
   update both store listings in the 0.2.3 pass. Until that lands, do not add
   translated listings anywhere: each new language is another copy of the
   false sentence.
3. Product decision for Ali (behaviour change, needs approval): close the
   reply window - either scan replies for the campaign immediately before
   dispatching its follow-ups, or move detection to hourly. If the window
   closes, the original sentence becomes true rather than needing softening.

Note the 30-day guarantee was checked at the same time and is consistent -
`refund.html` matches the store copy, exclusions and all. Not every flagged
claim turns out to be wrong.

## 🔴 P0 — blocks users / revenue now

### ✅ Publisher verification → Azure MPN ID — DONE (2026-06-24)

> **Resolved.** The app `3b6a9f9b` was already in the work tenant
> (`outmassappoutlook.onmicrosoft.com`) — no migration / no client-ID change.
> The earlier error was just the wrong signed-in account; redoing it as
> `partner@…onmicrosoft.com` (a CPP admin) got past `MPNAccountNotFoundOrNoAccess`.
> Then `metisbilisim.com` was added as a verified tenant custom domain (DNS TXT)
> to satisfy the publisher-domain match. **M365 work/school consent block lifted.
> Zero code/deploy change, zero service disruption.** _(original notes below.)_
The M365 work/school **consent block** is still live — an unverified multitenant
publisher means end users can't grant consent. Telemetry shows real, motivated
users lost to it (*"The user did not approve access"* — e.g. person `988a5fe3`,
US/Mac, 8 attempts over 4h). Partner Center legal verification is **Authorized**,
but the Azure "Add MPN ID to verify publisher" step failed with
**`MPNAccountNotFoundOrNoAccess`**.

To finish (Azure → App registrations → OutMass `3b6a9f9b-cbb6-4dcb-a3b6-d993de74a1b5`
→ Branding & properties):
1. Partner Center → Account settings → **Identifiers** → use the **`PartnerGlobal`**-type
   ID (NOT a Location/PLA ID). The number we tried (`7128581`) errored — confirm the real one.
2. Sign in to Azure with an account that's **Global / MPN / Accounts Admin** on the
   Partner Center (CPP) account, and confirm the app's tenant is in the CPP
   **associated tenants** list.
3. **Likely next hurdle — `PublisherDomainMismatch`:** the app's Publisher Domain is
   `getoutmass.com`, but the Partner Center vetting domain (primary contact
   `alibayar@metisbilisim.com`) is `metisbilisim.com`. Either add **`metisbilisim.com`**
   as a verified custom domain in the app's Entra tenant (DNS), or set the app's
   publisher domain to it.

*Needs Ali at the Azure / Partner Center portals (share screens).*

---

## 🟠 P1 — bit a paying customer / ship pending

### ✅ Cross-campaign dedup skips never-delivered recipients — DONE (2026-06-24)

> **Resolved.** `_fetch_previous_emails` now dedups `pending` only from campaigns
> still on track to deliver (scheduled/sending/ab_testing); `pending` from a
> failed/partial/cancelled campaign is no longer skipped, so a failed send can't
> lock a user out of re-mailing their own list. `sent` dedup unchanged. Added a
> regression test (`test_pro_user_dedup_keeps_pending_from_failed_campaign`).
`_fetch_previous_emails` (`backend/routers/campaigns.py` ~1204) returns **sent OR
pending** addresses; the upload dedup (~447) then skips them. Recipients left
`pending` by a FAILED/partial send (e.g. the 502 timeout) never received the email
but get skipped → the user is locked out of their own list. **Miriam hit exactly
this.** **Fix:** dedup should skip only actually-`sent` (delivered) contacts, not
`pending` from failed/partial campaigns. (Today's workaround: Settings → "Skip
Repeat Recipients" → off.)

### ✅ Upload extension v0.1.18 to Chrome — DONE (2026-06-25, LIVE)
`outmass-0.1.18.zip` built + verified and **live on the Chrome Web Store** —
confirmed by an organic new user (India, person `2348cf80`) already running
0.1.18 end-to-end. Bundles large-send warning + benign-noise client filter
(P2 #2) + feedback reassurance copy (P2 #3).

### ✅ Upload extension v0.1.18 to Edge — SUPERSEDED (closed 2026-08-08)
Overtaken by events long ago and left open by bookkeeping alone. Edge was
already on 0.1.20 by 2026-07-03 (`handoff-2026-07-03.md:26`), reached 0.1.25 in
July and published 0.1.26 on 07-29 (see the store-listing entry below). The
0.1.18 zip was never the thing to upload.

**Current store state** (self-reported in `handoff-2026-08-08.md:22`, NOT read
from the dashboards — only Ali can confirm those): Chrome 0.1.27 live, Edge
0.1.26 live with 0.1.27 in review, and `outmass-0.2.0.zip` built and verified
but not yet uploaded to either store. Track the live versions in the handoff,
not here — a backlog entry pinned to one version number goes stale the week
after it is written.

---

## 🟡 P2 — flagged bugs / cleanup

### ✅ Truncated unsubscribe IDs — DONE (2026-06-25)

> **Resolved.** `get_contact()` now validates the id is a UUID and returns
> `None` before the query, so the public tracking routes (`/t`, `/c`,
> `/unsubscribe`) fall into their existing "not found" path (clean 200)
> instead of crashing with 22P02 → 500. Test: `test_contact_uuid_guard.py`.
> _(Committed `93815ee`, not yet deployed — batched with the dedup fix.)_
PostHog `$exception` (backend): `/unsubscribe/NjhjYWRjMT…` — 10-char, non-UUID →
`invalid input syntax for type uuid`. Either the unsubscribe links are being
truncated, or email scanners hit partial URLs.

### ✅ Filter benign $exception noise — DONE (2026-06-25)

> **Resolved.** Two layers share one denylist (ResizeObserver loop,
> port-closed/bfcache, extension-context-invalidated): the backend
> `/api/error-report` returns `{"status":"filtered"}` without capturing
> (scrubs noise from already-shipped versions immediately), and
> `reportError()` in `background.js` short-circuits before the fetch.
> Tests in `test_posthog.py`. _(Committed `527941d`; backend deploys in
> the batch, client ships with 0.1.18.)_
363 `ResizeObserver loop completed…` events flooded error tracking
(`extension-client`).

### ✅ Feedback form confirmation — DONE (2026-06-25)

> **Resolved.** The success toast now promises a reply — "Thanks — we got
> your message and will reply to your email soon." across all 10 locales —
> instead of the passive "submitted!". Also fixed the feedback context
> reporting a hardcoded version `"0.1.0"` (now the real manifest version)
> so support tickets carry accurate build info. _(Committed `04e4a6b`;
> ships with 0.1.18.)_
The in-app feedback form gave no clear "we got it — we'll reply to your email"
confirmation, so users felt unheard (Miriam: *"I can't even email support"*, yet
her feedback did arrive).

---

## 🔵 P3 — ops / quality

### ✅ DMARC for getoutmass.com — DONE 2026-08-13

> **Resolved.** The record is live, aggregate reports arrive daily, and
> `scripts/dmarc_report.py` reads them without opening the XML; reports land
> in `dmarc/`. The heading here still said **CONFIRMED MISSING** the day after
> it was fixed — stale by exactly the amount that makes a backlog untrustworthy,
> corrected 2026-08-14.
>
> *(Original entry: `nslookup -type=TXT _dmarc.getoutmass.com 8.8.8.8` →
> NXDOMAIN on 2026-08-08. SPF was already correct
> (`v=spf1 include:_spf.mx.cloudflare.net include:_spf.mailersend.net ~all`), so
> the missing piece was one DNS TXT record. Without DMARC, receivers had no
> policy to apply to mail failing SPF/DKIM, and nothing told us when it
> happened. DKIM was verified in the same sitting.)*

### ⬜ Hélène's comped Pro ends 2026-10-01 — watch the 18 days before it

Her two campaigns (CBRE 66, Sustainability FM 42, both 5/day) finish around
**13 September**. The comp runs to **1 October**. That leaves eighteen days
where she holds Pro and has nothing running, and those days answer a question
we cannot answer by asking:

- **Starts a third campaign** → she is choosing to use Pro. Ask about paying
  for it as the comp nears its end; the answer means something.
- **Goes quiet** → the question changes to "what was missing from Pro?", and
  she is the only user who can answer it — she has run follow-ups, A/B and
  scheduling on a real list.

She is on Starter ($9) and has held comped Pro since 2026-08-30. Both earlier
grants were OUR-FAULT compensation and exempt from the gift test: the first
because the Starter gate blocked follow-ups and A/B, the second for the
scheduled-send formatting bug, promised by email as 1 October and verified in
the row on 2026-09-03.

A third grant was proposed on 2026-09-02 — three months, for the quality of
her feedback, which is real: she found the 100% open rate, and that one was
inflating every user's numbers. But it is DISCRETIONARY, so the test applies
([[gift_learning_or_crutch]]), and as stated it fails: she is already using
the product heavily, so the gift buys no new usage, and it is paired with no
question. What it would buy is three more months of not knowing whether our
best-informed user values Pro at $19.

**Do on 13 September:** thank her properly — she pushed on a number she did
not believe, and that stopped other people from running into the same thing.
Nobody has told her. Keep it separate from any grant.

Say it that way, not with a count. Ali, 2026-09-03: *"kaç kişiyi etkilediğini
falan karıştırmayalım."* A number opens two doors we do not want opened — it
tells her how few users we have, and it moves the subject from what she did to
how long we served everyone a wrong figure. "You stopped others hitting this"
gives her the credit without either.

If a gesture is wanted anyway, one month PAIRED WITH THE QUESTION passes the
test; three months unasked does not.

### ⬜ Composer: links and an image in the signature — PROMISED TO A CUSTOMER 2026-09-01

Hélène Carpentier asked both in the same message as her follow-up text:

> "Is there also a way to add links into the text? (that was not obvious how
> to do that) and add a logo in signature (as my signature below)."

The reply told her links were "on the list", which is why this entry exists:
a sentence in a support email is a commitment, and it was not written down
anywhere until Ali noticed the gap the same afternoon.

**Links.** Possible today only by typing HTML into the composer, which is not
an answer for someone writing an email. It also only became *safe* on
2026-09-01 (`7dea631`): before that, one `<a href>` in a body flipped
`looks_like_html` and the whole message went out as a single block, so the
feature she asked for would have handed her back the bug she reported that
morning. `render_body` now separates block markup from inline markup, and
`_wrap_links` already rewrites `href="..."` for click tracking, so the send
side is done. What is missing is the panel: no way to mark a word as a link
without knowing HTML.

Smallest honest version: a link button on the body field that wraps the
selection in `<a href="…">`. Not a rich-text editor. Half a day plus the
locale pass (2-3 keys × 14 files).

**Logo in the signature — scoped by Ali, 2026-09-01: a field for the URL, no
hosting.** Right call; hosting images is a different product.

It fits the sender profile that already exists — `sender_name`,
`sender_position`, `sender_company`, `sender_phone`, edited in Settings and
exposed as `{{senderName}}` and friends. Logo is a fifth field.

  1. `users.sender_logo_url`, nullable. One reversible migration.
  2. A Settings field beside the other four, plus its label and hint
     (2 keys × 14 locale files).
  3. `build_merge_context` supplies `senderLogo`. **It must expand to a
     complete `<img …>` tag, not to the bare URL** — a user who has to write
     `<img src="{{senderLogo}}">` themselves is back to needing HTML, which is
     the thing this entry exists to remove. Empty string when unset, so a
     template carrying the tag degrades to nothing rather than to a broken
     image.
  4. Validate on save: https only, and reject anything that is not a URL.
     The risk is small (their own address, in mail from their own mailbox)
     but `javascript:` and `data:` have no business in an `img src` we write.

**The one non-obvious part.** Since 2026-09-01 `render_body` picks a branch
from the TEMPLATE: plain text gets escaped, so an `<img>` arriving from a
merge value would be delivered as the literal characters `&lt;img …`. A
template whose only markup is `{{senderLogo}}` therefore looks plain and would
break exactly the feature being added.

Fix it where the decision is made, not with a special case at the merge site:
a template containing `{{senderLogo}}` counts as inline markup, because the
author placing that tag IS the author placing an image. `extension/sidebar.js`
carries the same three-branch logic and a test compares the two, so both sides
change together or the suite fails.

Half a day, plus the locale pass and Ali's onay for the migration.

Related, from the same message and NOT promised: **there is no way to edit a
campaign after it starts.** No PUT, no PATCH, no panel control — verified
2026-09-01. Stopping one is new in 0.3.2. Worth its own entry when someone
asks twice; recorded here so the third person's request is not the first time
we notice.

### ⬜ Branded support send-as (`support@getoutmass.com`)
Split out of the entry above on 2026-08-08 because the two are independent and
bundling them hid that one of them is a one-record DNS fix. Replies still come
from `outmassapp@outlook.com` (Outlook.com cannot send-as an external domain).
Note the repo uses MailerSend as an **HTTP API** sender, not SMTP
(`backend/utils/welcome_email.py`, `backend/workers/inactivity_nudge.py`,
`backend/models/ms_token.py`, `backend/routers/account.py`) — so this is a Gmail
"Send mail as" setup against MailerSend SMTP credentials, entirely outside the
codebase. Nothing to implement here; it is an account setting.

### ✅ Re-run the PostHog funnel (verify the fixes) — DONE 2026-08-07

> **Resolved.** Asked on 06-24 for "2-3 days later"; actually done 08-07, and it
> was worth the wait because by then there was enough volume to read. The full
> store→install→sign-in→send funnel is in `handoff-2026-08-07.md:24-54`:
> 430 impressions → 140 views (33%) → 48 installs (34%); post-install
> 63 → 30 opened the panel → 37 tried sign-in → 22 signed in → 16 uploaded →
> 9 sent (14%). Cohort split: of 54 who never opened the panel, **0 sent**;
> of 43 who did, 15 sent (35%).
>
> It answered both original questions with evidence, and both answers were
> different from the guess. *"Authorization page could not be loaded"* was NOT a
> Microsoft-side failure at all — it was our own error page returning HTTP 400,
> which Chromium reports as a page-load failure and the extension auto-retried,
> so a user who had just declined got a fresh consent screen 3 seconds later.
> Fixed and deployed 08-08 (`7233d35`). And *"did not approve"* turned out to be
> partly real: AADSTS65004 events are the first hard proof that users actively
> decline, rather than being blocked.
>
> Two lessons kept: reading the funnel found a bug that no test suite could have
> (the 400 was correct HTTP and wrong behaviour), and store conversion turned out
> to be the healthy part — see `funnel_truth_2026_08`. The lever is impressions
> volume and post-install activation, not the store listing.

**Not a standing cadence.** This was one ad-hoc read. If a weekly rhythm is
wanted, that is a separate commitment nobody has made yet.

### ✅ Debounce the sign-in button (prevent stacked OAuth popups) — DONE (2026-06-25)

> **Resolved (`02f9b62`, ships in 0.1.19).** `startMSLogin` now single-flights:
> while an OAuth flow is in progress, repeated Sign in / reconnect clicks join
> the same in-flight promise instead of launching another `launchWebAuthFlow`.
> Keyed by flow type (signin vs onedrive). `oauth_started` now fires once per
> real flow. Also disabled the sidebar "sending-as change" link mid-flow.
Telemetry from the first 0.1.18 organic user (2026-06-25, person `2348cf80`):
**10 `oauth_started` / 3 `oauth_completed` / 2 `oauth_failed`** in one ~12-min
session, six `oauth_started` within ~10s. The user rapidly re-clicked sign-in,
spawning multiple OAuth popups; the abandoned ones logged
`oauth_failed: "The user did not approve access."` (benign user-cancellation,
**not** the consent block — they completed and ran a successful test send).
**Fix:** disable / debounce the sign-in button while an OAuth flow is in
progress (`background.js` launch path + the sidebar/popup buttons) so a flow
can't be started twice. Also dampens false "did not approve" noise in the
oauth funnel. Low effort, UX-only.

### 🔧 Quota follow-ups (deferred from the 2026-07-03 billing-anchored quota review)
Adversarial review of the rolling-quota change surfaced these; all bounded /
rare, deliberately deferred. **Re-audited 2026-08-15 against the code, every
verdict cross-examined by two skeptics: 1 ✅, 2 ✅ with a narrower accepted
residual, 3 🔧 HALF-done (the skeptic pass caught a missing write path the
first read called done), 4 🔧 half-done.**
1. ✅ **Mid-campaign reset/increment race — DONE 2026-08-11** — send loops incremented the counter
   ONCE at the end of a paced (possibly hours-long) run; if the period boundary
   rolls over mid-flight, the whole campaign's count lands in the NEW period.
   Fix: increment in small batches (~25) inside the send loops. Bounded
   (≤1 campaign), self-corrects next period; pre-existed in calendar form.
   - **Done for ONE loop.** `840ee99` (2026-08-08) added
     `QUOTA_CHARGE_BATCH = 25` (`backend/config.py:264`) and batches inside
     `_run_campaign_send` (`backend/routers/campaigns.py:972-976`, with a
     tail-catch at 995 and handlers for cancellation and generic failure) —
     the **send-now** path only. That commit touched no worker file.
   - ✅ **The three worker loops followed on 2026-08-11** (`ffe9737`): mid-loop
     `QUOTA_CHARGE_BATCH` charging + a guarded remainder flush in the
     scheduled-campaign loop (`scheduled_worker.py:181`), the A/B winner pass
     (`:515`) and follow-ups (`followup_worker.py:109`).
     `test_quota_batching.py` pins the call SHAPE (25+25+10, never one 60)
     and bounds a mid-loop kill to one batch. This bullet claimed "still
     unbatched, all three" for four days after the fix landed — task #26 was
     the correct record and this file was the stale one.
   - **The entry said "5 send loops"; there are 4.** ✅ **Closed 2026-08-14 —
     the fifth was deleted.** `email_worker.send_email_task` had no caller and
     never touched `increment_sent_count`, but the 2026-08-13 send-path
     mapping sharpened what that meant: it POSTed to Graph, marked the contact
     sent and bumped the campaign counter, so it was the one path that could
     put a customer's email on the wire charging no quota and reporting
     nothing — and it stayed **registered** at `celery_app.py`, one
     `celery.send_task()` from a shell away from being live. "Dead code" was
     the wrong frame; dormant and armed was the right one. Ali's call: delete,
     rewrite later if ever needed. A test now asserts the set of files that
     POST to `/me/sendMail` is exactly the three that charge the quota, so a
     fourth cannot reappear quietly.
2. ✅ **cancel_at_period_end final-day refill — DONE 2026-08-14/15**
   (`79398b6` + `28a8c75`). Exactly the fix this line used to propose:
   migration 028 persists cancel_at_period_end from subscription.updated in
   both directions (`billing.py:886-906`) and holds the due-day rollover
   (`user.py:395-401`); a day later the paid_cycle_confirmed hold
   (`user.py:426-436`) covers the same case even if the flag were never set.
   Tests: `test_quota_anchor_and_cancellation.py`,
   `test_billing_cycle_reset.py:109` (the cancel hold wins even over a stray
   paid_cycle_confirmed=True). **Accepted residual, not cancellation-specific:**
   both holds are bounded to today==due, so a Stripe webhook lost past UTC
   midnight lets ONE stale-plan rollover through a day late — the tradeoff
   `user.py:390-394` documents on purpose. Revisit only if the green report's
   "backstop rolled it" flag fires two months running.
3. 🔧 **Month-end anchor drift — READ half shipped, WRITE half missing**
   (re-scoped 2026-08-15; the audit's first pass called this done and two
   skeptics refuted it). Migration 029 added `month_reset_anchor_day` and the
   period math reads it (`user.py:304-324`, `:438-444`) — but **nothing in
   application code ever writes the column**; the only writer is the
   migration's one-time backfill. So (a) every user created after the
   migration has NULL forever → falls back to the clamped day → the original
   29/30/31→28 decay reproduces for all new users; and (b) NEW and sharper:
   the checkout re-anchor (`billing.py:576-580`) sets month_reset_date=today
   without touching the anchor day, so a subscriber who pays on a different
   day than they signed up keeps the STALE signup anchor and the next quota
   "month" can be days long (signup day 5, pay Aug 31 → due Sep 5). Fix =
   write the anchor at user creation and at every month_reset_date re-anchor,
   plus a source-scan test that every writer of one writes the other
   (`test_send_telemetry.py` has the pattern). → task #57.
4. ✅ **create-checkout StripeError fallthrough — DONE 2026-08-15** (second
   half closed same day it was re-scoped). The 502 half had shipped earlier
   (`billing.py:236-255`). The identity half now exists as
   `_event_subscription_is_current`: subscription.deleted / subscription
   .updated / the renewal invoice only act when the event describes the
   subscription the account RUNS on; stored-NULL and no-id cases fail open
   to the old behaviour, a mismatch skips loudly (log + Telegram). Covers
   the orphan-cancel scenario AND the ordinary cancel-then-resubscribe flow,
   where the old subscription's period-end death used to downgrade the
   freshly re-paying customer. The invoice id is read in both the pre-basil
   and basil payload shapes. Tests:
   `test_webhook_subscription_identity.py`. The same review added three
   checkout hardenings: a >14-day-old session event is refused (dashboard
   "Resend" resurrection), an anomalous no-subscription session no longer
   NULLs a stored id, and the quota anchor now comes from the
   subscription's own `current_period_start`, not our webhook-processing
   clock. **Endpoint API version confirmed by Ali 2026-08-15:
   `2026-03-25.dahlia`** — post-basil, so the `parent.subscription_details`
   path is the one live payloads actually use; without the two-shape read
   the renewal guard would have shipped permanently inert. Every other
   field the webhooks read has months of production behaviour proving it
   arrives — `invoice.subscription` was the one field never read before,
   which is exactly why its absence would have been silent.

### ✅ Microsoft-consent funnel leak — ALL THREE SHIPPED, measure it now (2026-08-15)

> **Re-audited 2026-08-15. All three ideas are in the code; the 08-08 audit
> below is what was true a week ago and is kept because its warning still
> applies — adjacent work lands near this and it is easy to miscount.**
>
> - **Idea 1, pre-OAuth trust panel: SHIPPED in 0.2.1**, published to Chrome
>   on 08-15. `extension/sidebar.html:43` carries `popupConsentExplainer`,
>   which the 08-08 audit correctly reported as living only in popup.html.
> - **Idea 2, consent-decline follow-up: SHIPPED.** `i18n.js:197`
>   `msAuthMessage(mcode, fallback)` maps 14 classifications to sentences, and
>   it takes PRECEDENCE at all three places a user sees the failure —
>   `sidebar.js:186`, `sidebar.js:249`, `popup.js:258`. The static
>   `authErrorConsent` the audit flagged is now only the fallback for when the
>   backend sent no code. (Read one line further than the `consent_declined`
>   branch before concluding otherwise; that mistake was made twice.)
> - **Idea 3, per-step measurement: SHIPPED, cadence still unmade.** Nothing
>   reads the funnel on a schedule. `workers/green_report.py` is the obvious
>   home; Gate 2 in it still says "PostHog, by hand".
>
> **The baseline to beat, measured 2026-08-15** — `oauth_started` and
> `oauth_completed` are both client-side and lossy, so this counts
> `ms_auth_window_opened` against the SERVER-side `login`:
>
> | week | reached Microsoft | signed in | rate |
> |---|---|---|---|
> | 08-09 | 28 | 13 | 46% |
> | 08-02 | 17 | 7 | 41% |
>
> More than half of everyone who reaches Microsoft's screen never comes back.
>
> **And the shape of the loss, last 30 days by AADSTS:** user_declined_consent
> (65004) 8 people — the largest classified group by far; no_code_from_
> microsoft 3; account_from_other_tenant (50020) 1; unclassified 3.
>
> **AADSTS65001, the M365 admin-consent block this entry warned about, does
> not appear at all.** The loss is people choosing "no", not a tenant policy
> refusing them — which is the one kind a plain-language explanation before
> the screen can actually move. That is the bet 0.2.1 places.
>
> **Nothing left to build. Two things left to do:** put 0.2.1 on Edge (Edge
> received 0.2.0 on 08-15, and 0.2.0 does NOT contain the explainer), and
> re-measure the table above in a week.

> **Audited 2026-08-08 — one of the three ideas shipped. Read this before
> assuming the other two did, because adjacent work landed near both.**
>
> - **Idea 3, per-step funnel measurement: SHIPPED and used.** `abfae48`
>   (07-31) added `ms_auth_failed` with AADSTS classification;
>   `0f0636c` (08-03) added `ms_auth_window_opened` as the midpoint between
>   `oauth_started` (client) and completion. Real numbers came out of it on
>   08-07 (37 tried sign-in → 22 signed in). No weekly cadence exists though —
>   that was part of the idea and remains unmade.
> - **Idea 1, pre-OAuth trust panel: NOT shipped.** `popupConsentExplainer`
>   still lives only in `popup.html` and the locale files — grep finds it
>   nowhere in `sidebar.html`/`sidebar.js`. The panel, which is where users
>   actually are when they hit sign-in, still says nothing about what Microsoft
>   is about to ask for.
> - **Idea 2, consent-decline follow-up UX: NOT shipped — and this is the one
>   most likely to be miscounted as done.** The 08-08 auth work (error page
>   400→200, `_SETTLE_MESSAGES`, dwell 9s→5s) fixed the *repeat-prompt bug* and
>   improved the *server-side* settle text. But the client still collapses every
>   consent failure to one `consent_declined` code (`background.js:553-557`) and
>   renders one static alert (`authErrorConsent`) for all of them. Stopping a
>   loop is not the same as replacing a dead end with an explanation.
>
> So: 1 of 3. Do not close this entry.

~5 anonymous users lost AT the Microsoft consent screen in 10 days (AU 07-17,
BR 07-21, TR ×3 07-23, PH 07-25 — the PH one had a NEAR-PERFECT activation:
29-recipient CSV + 6 chip insertions in 5 minutes, then bailed at consent).
The 0.1.25 sign-in gate works — users now FIND and attempt OAuth (pre-gate
they never did) — the drop is now at Microsoft's permissions screen itself.
Ideas to explore: pre-OAuth trust panel (plain-language per-permission
explainer with the honest popupConsentExplainer framing + "we can never read
your inbox" + refund/privacy links), consent-decline follow-up UX (after
oauth_failed=declined, show "what Microsoft asked and why" instead of a dead
end), measure per-step funnel (oauth_started → completed rate) weekly.

### ✅ Scheduled-send early-close strand — FIXED 2026-07-29 (0.1.27 cut)
The twin of the router-path strand bug (c1705f2). `scheduled_worker` sliced the
list to the remaining quota (`pending[:remaining]`) but still closed the
campaign `"sent" if not errors` — so a scheduled campaign longer than the
remaining quota reported COMPLETE with contacts still 'pending', unreachable by
the Resume endpoint (409s on non-partial) and by the auto-resume beat (queries
`status='partial'`). Worse than the router case: the truncation is server-side,
so the user never even saw the quota alert. Now tracks `quota_capped` and lands
'partial'. Tests: `test_scheduled_quota_cap.py`.

### ✅ Auto-resume window vs rolling quota cycle — FIXED 2026-07-29 (0.1.27 cut)
`AUTO_RESUME_MAX_AGE_DAYS = 14` was compared against `created_at`, but the quota
period is a rolling month on the user's own `month_reset_date`, so the gap
between hitting the cap and the next reset is 0-31 days. Anyone who burned their
quota early in their cycle was ALREADY outside the 14-day window on reset day
and stayed outside it forever — while the in-app text promised an automatic
send. (Faisal's cap landed 5 days before his reset, which is why it worked.)
Now: query bound widened to 70 days, real rule is per-user
`_capped_in_last_quota_cycle()` = created within the current or previous cycle.
Tests: 4 new cases in `test_auto_resume.py`.
**Remaining limitation (accepted):** a campaign so large it needs 3+ cycles to
drain falls out after two. Reports still offers Resume. Proper fix needs a
`campaigns.updated_at`/last-activity column (migration) — revisit if a real
user hits it.

### ✅ Suppressed-skip contacts stay 'pending' forever — FIXED 2026-08-04
`contact_model.mark_suppressed()` records the skip in all three send loops
(router send-now, scheduled worker, A/B winner pass); `get_resumable_contacts`
already filters on `status IN (pending, deferred)` so they drop out with no
query change. 5 tests.

Two things the original diagnosis had wrong, worth keeping:
- **unsubscribed needed no fix.** `get_resumable_contacts` already carries
  `.eq("unsubscribed", False)`, so those were never the problem — only the
  suppression-list path was. Marking them too would touch rows for no gain.
- **"Decide Reports display semantics" was a non-issue.** The stats endpoint
  returns sent/opened/clicked/engaged/reply rates plus pending_followups; it
  never counts contact status. The only consumer is the resumable set, so
  nothing user-visible moved.

Scope note: suppressed addresses are filtered at UPLOAD time, so the rows
reaching these loops are only those added to the list AFTER the CSV went in
(including anyone who unsubscribed from an earlier campaign). Deliberately
NOT reversible — if the user later un-suppresses an address, the contact
stays skipped. Re-emailing someone who was on a do-not-email list should be
a deliberate act, not a side effect.

### ✅ Store-listing refresh — VERIFIED LIVE on the public listings (2026-08-15)

> Ali said the paste "should have happened"; instead of trusting memory or
> the dashboards, the PUBLIC store pages were scraped — they are what users
> actually see, which makes them the evidence rather than a proxy for it.
> **All 12 Chrome locales** (en, tr, de, fr, es, ru, ar, hi, zh-CN, zh-TW,
> ja, pt-BR) **and 2 sampled Edge locales** (tr, de) carry the new copy:
> 250/2,500 quotas, the 🚦 daily-limit and ♻️ auto-resume bullets, and no
> timezone claim anywhere. Chrome shows 0.2.1 live. Edge takes its listing
> as one submission, so two clean samples speak for the set.
>
> One false alarm during verification worth keeping: a grep for the OLD
> "50 emails/mo" marker matched — inside "2**50** emails/month". Read the
> context before believing a marker, even one you wrote yourself.
>
> The pt_PT question that used to live at the bottom of this entry moved to
> its own item below — a ✅ must not contain an open question.

> **Re-marked 2026-08-08.** This was ✅ while its last line said "Remaining: Ali
> pastes all 11 languages into BOTH dashboards" — so the repo-side prep was
> done and the only part users can actually see was not, tracked nowhere. A ✅
> with an open action inside it is how work disappears.
>
> **And the number moved: it is 12 now, not 11.** `listings.json` currently
> holds en, tr, de, fr, es, ru, ar, hi, zh_CN, **zh_TW**, ja, pt_BR — zh_TW was
> added the day after this entry was written, when Traditional Chinese became a
> real translation. `docs/store-listing/README.md` still says 11 and still
> describes pt_BR as "listing-only until the pt locales ship in 0.1.27"; 0.1.27
> shipped on 08-05.
>
> *(the pt_PT question moved to its own ⬜ item below on 2026-08-15)*

Trigger fired: Edge published 0.1.26 on 07-29. All 9 points applied to
`docs/store-listing/listings.json` (10 languages edited + NEW pt_BR entry) via
a 15-agent translate+verify workflow; `check-limits.js` guards limits + banned
claims (timezone phrases, "Claude"). Outcomes vs the audit:
- Point 1-2 (250/2500): repo copy was already correct — the DASHBOARDS are
  staler than the repo; every language must be re-pasted, not just TR.
- Point 3 (language count): stays **10** — the 11th `_locales` folder is `zh`,
  a zh-TW/HK fallback with the same Simplified content, not a new language.
  Becomes 11 at 0.1.27 (Portuguese counted once). Policy note in README.
- Point 4 (timezone claim): removed in all languages; check-limits.js has
  per-language tripwire regexes so it can never return.
- Point 5: follow-ups marked (Pro) + "stops when someone replies" added.
- Point 6-7: 🚦 daily-limit and ♻️ auto-resume bullets added ×11.
- Point 8: AI quota 50/mo verified in config.py; "Claude-powered" genericized
  (model-name maintenance liability) — one-word revert if Ali disagrees.
- Point 9: 30-day guarantee kept.
- **BONUS fix found during the code claims-check: the old Pro pricing line
  claimed templates — templates are Starter+ in code (templates.py). Starter
  line now lists scheduled sending + templates + CSV export; Pro line lists
  AI + A/B + follow-ups. Plan labels added to feature bullets to match gates.**
- Verify pass caught an **ar bidi bug**: "(Starter+)" renders "(+Starter)" in
  RTL — replaced with "(Starter فأعلى)". (zh-lesson class of defect.)
Remaining: Ali pastes all 11 languages into BOTH dashboards (Edge listing edit
= new metadata-only submission; batch it, don't trickle).

Original audit (for history):
1. "Free — 50 emails/mo" → **250/mo** (ancient pre-launch number; underselling).
2. "Starter — 2,000/mo" → **2,500/mo** (underselling).
3. "10 interface languages" → 11 today, **13 once 0.1.27 ships** — sync the
   number with whatever is LIVE at edit time (claims discipline).
4. "send across timezones" → REMOVE — this exact claim was killed in the
   2026-07-15 site audit but survives in listing translations.
5. Follow-ups bullet: mark **Pro-only** (align with site decision b) and may
   now truthfully add "stops automatically when someone replies".
6. ADD: **Daily send limit** (live since 0.1.25 — the bellmed feature).
7. ADD (optional): quota-capped recipients auto-resume after reset (live
   2026-07-20).
8. Verify the AI-writer "(Pro, 50/mo)" quota against config before keeping the
   number; reconsider naming the model ("Claude destekli") in store copy.
9. "30-day money-back guarantee" ✓ verified real (refund.html + pricing FAQ) —
   keep.

### ⬜ pt_PT store-listing entry — decide, don't drift

Split from the store-listing entry above (a ✅ must not carry an open
question). The extension ships pt_PT but `listings.json` has no pt_PT
entry. Next time Ali is inside either dashboard: do the stores offer pt-PT
as a separate listing locale? If yes, decide add-or-skip deliberately; if
no, close this entry with that fact written down.

### ✅ 0.1.27 queue — CUT 2026-07-29, PUBLISHED on Chrome 2026-08-05
*(Heading corrected 08-08: it still said "awaiting Ali's upload" nine days after
the upload happened — the same ✅-with-an-open-action-inside pattern flagged at
the top of this file. Edge 0.1.27 was still in review at the time of writing.)*
Both queue items shipped, plus what the mandated adversarial review turned up.
**Shipped:** pt_BR + pt_PT locales (323 keys each, translated separately — not
one file copied; verified BR/PT vocabulary split) · reworded `alertQuotaCapped`
AND `resumeHint` ×13 · `aiLangPt` + AI-writer `pt` option + `pt_BR`/`pt_PT` in
Settings → Interface Language · backend `_LANG_NAMES["pt"]` · Portuguese
unsubscribe page · the two backend strand/window fixes above · new suites
`locale-variants` (script + regional purity) and `test_ai_language_contract`.
Package: `outmass-0.1.27.zip`, 29 entries, 13 locales, no leakage.

**Findings raised by the review that are NOT fixed (deliberate, documented):**
- **AI writer has one generic "pt" option** — a pt_PT user asking for a
  Portuguese draft may get Brazilian-leaning text. Accepted for now: Pro-only
  feature, output lands in the editor for review before sending, and both
  variants are mutually intelligible. Proper fix = send `pt_BR`/`pt_PT` from
  `getActiveLocale()` and add both to `_LANG_NAMES` (keep bare `pt` for
  already-shipped clients). Do it when a Portuguese Pro user actually appears.
- **AI-language preselect reads the browser language, never the Settings
  override** (`sidebar.js` ~1739 `chrome.i18n.getUILanguage()`): someone whose
  browser is English but who set the panel to Turkish gets English preselected.
  Pre-existing for all 13 languages, cosmetic (dropdown is one click). Fix =
  read `uiLanguage` from storage / expose the resolved locale, and normalise
  `pt_BR`/`zh_CN` → base code before the `supported` lookup.

**DEPLOY ORDER MATTERS:** backend first (`_LANG_NAMES` + unsubscribe strings +
the two worker fixes), extension after. New extension against an un-updated
backend = Portuguese requested, English email delivered, no error anywhere.

1. ✅ **Partial-send quota message text update ×13** — the in-app alert said
   "Resume sends them after an upgrade or your monthly reset"; since 2026-07-20
   the backend auto-resumes capped recipients (auto_resume_partial_campaigns
   beat + quota-cap email). Update wording to "they'll be sent automatically
   after your reset — or upgrade to send them now". Harmless meanwhile (user
   goes to click Resume, finds the campaign already completed).
2. ✅ **New locales: pt_BR + pt_PT (11 → 13 folders, 11 languages)** — approved by Ali 2026-07-21,
   data-driven: 2 observed pt-BR users in 90 days (the only uncovered locale in
   telemetry); pt_PT rides along nearly free. No generic "pt" code in Chrome —
   both folders required (pt-PT does NOT fall back to pt_BR). At cut: translate
   full messages.json ×2 in the correct variants, locale-consistency suite
   enforces parity automatically. Mind script/variant consistency (zh lesson,
   see memory release_adversarial_review). ALSO update item 1's new strings in
   13 files, not 11.
   - **Parallel, no release needed:** ✅ pt-BR store-listing translation is
     READY in listings.json (2026-07-29, verified pt-BR-not-pt-PT); Ali pastes
     it into Chrome/Edge dashboards with the listing refresh. Conscious call:
     it markets to users who get an English UI until 0.1.27 ships pt locales.
   - **NL: deliberately NOT added** — both observed NL users run en-US browser
     UIs (self-selected English; NL = top English-proficiency market). Policy
     stays demand-triggered: first real request/nl-locale telemetry → add same
     week.

### ✅ Traditional Chinese is now REAL — shipped in 0.1.27 (2026-07-30)
Ali's call after the count discussion: rather than keep explaining that `zh` was
a Simplified fallback, make Traditional genuine. `extension/_locales/zh_TW/`
(324 keys at the time) written from English in TAIWAN terminology — 軟體/檔案/
資訊/資料/範本/伺服器/設定/收件者/儲存/登入/排程/主旨/預設/行銷/支援/點選 —
deliberately NOT a character conversion of zh_CN (only 14/324 strings coincide,
all of them short labels that are identical in both scripts anyway).
*(Re-measured 2026-08-08: both files are now 340 keys with 15 coinciding —
later releases added strings. The claim holds; only the numbers aged.)*
Also: AI writer gained a Traditional option (and the Simplified one is now
labelled explicitly); `_LANG_NAMES["zh_TW"]`; recipient-facing unsubscribe page
in Traditional with `_detect_lang` preserving the region FOR CHINESE ONLY;
`zh` stays Simplified as the fallback for bare `zh`/zh-SG.
The `locale-variants` suite gained the sharper half of the check: correct
characters are the easy part (any converter does that), so it also greps for
**mainland vocabulary in Traditional dress** (軟件/信息/數據/模板/服務器/網絡/
設置/視頻/收件人/登錄/註銷/郵箱/回复/技術支持/應用程序…). Character lists were
vetted against the real file — 回/系/准/台/里/西 are standard Traditional and
were excluded after producing only false alarms.
NOTE: the pt/zh_TW work was done by hand — the subagent API returned 529 twice
with zero output, so the usual multi-lens review could not run on this half.
Verification was: 4 extension suites + a wide one-off character/vocabulary
audit + structural parity check against en.

### ✅ FALSE CLAIM on the live pricing page: "Traditional Chinese" — DONE 2026-08-05
**Closed the day Chrome published 0.1.27**, per claims-follow-product. Ali
approved; `docs/pricing.html` now says 13 in all four places and the
"joined at a user's request" anecdote is gone (it was never true).

Three counts turned out to be different, and the old copy claimed one number
for all three — each verified against the code, not assumed:
- **interface: 13** — options in `sidebar.html`'s language `<select>`, minus Auto
- **AI Writer: 12** — options built in `sidebar.js` (`aiLang*`)
- **unsubscribe pages: 12** — keys in `_UNSUB_STRINGS`, `backend/routers/tracking.py`

Both 12s differ from 13 for the same reason (Portuguese is offered once, not
twice), so the FAQ explains it in one clause instead of three numbers.

Found while doing it: **`docs/store-listing/edge-description-en.txt`** had sat
unvalidated since June and still advertised "10 UI languages", "across time
zones" AND "Claude-powered" — every claim the 07-15 audit removed elsewhere —
in the one directory whose purpose is paste sources. Deleted (superseded by
`descriptions/en.txt`); `check-limits.js` now fails on ANY loose `.txt` there.
`docs/launch/producthunt.md` carried the same three plus "Free forever at
50/month" (real free tier is **250**) and "Starter 2k" (real: **2,500**) —
all corrected.

Original plan (for history):
**Update 2026-07-30: the claim is about to become TRUE** — 0.1.27 ships a real
Traditional translation. So the page no longer needs the claim removed, only
corrected: the count and the list. Honest post-publish wording: **13 interface
languages** (see `docs/store-listing/README.md` for why 13 and not 11/14), list
"…Simplified Chinese, Traditional Chinese, Japanese, and Portuguese (Brazil &
Portugal)", drop the "joined at a user's request" anecdote (it was never true
of the old `zh` fallback), and fix line 129's AI-writer count to match.
Still needs Ali's OK (live pricing copy) and must wait for the store to show
0.1.27.

Original finding (for history):
`docs/pricing.html:230` tells visitors the UI supports **11 languages** and lists
"Simplified Chinese, **Traditional Chinese**", with a story attached: "Traditional
Chinese joined exactly that way, at a user's request." **It did not.** The `zh`
folder was created as a GENERIC Chinese fallback (`bf58ab7` — "generic zh locale
so all Chinese variants get Chinese, not English") and its content is
**321/323 keys byte-identical to `zh_CN`**, i.e. Simplified. A zh-TW/HK visitor
gets Simplified text, not Traditional. Same page also says "11 languages" at
line 77 while line 129 says the AI Writer has "10 languages" — internally
inconsistent too.
**Needs Ali's OK (live pricing copy).** Proposed wording once 0.1.27 is
published (claims-follow-product: only after the store shows it):
- honest count = **11 languages** (en, tr, de, fr, es, ru, ar, hi, zh-Hans, ja,
  pt) — Portuguese counted once, `zh` is a fallback not a language
- list: "…Simplified Chinese, Japanese, and Portuguese (Brazil & Portugal)"
- drop the Traditional-Chinese anecdote; if worth keeping, say the true thing:
  "browsers set to Traditional Chinese get the Simplified translation rather
  than English"
- line 129 AI-writer count → 11
- also `docs/store-listing/descriptions/*.txt` + `edge-description-en.txt` still
  say "10 UI languages" (they feed the same dashboards as listings.json).

### ✅ Claims-audit leftovers (from the 2026-07-15 site audit) — ALL THREE DONE

> **Closed 2026-08-08 after verifying each sub-item against the code.** The
> header had been left ⬜ while every item under it shipped — a section marker
> that outlived its contents.

0. ✅ **OneDrive picker consent-loop guard** — deployed, not just "in master".
   `_oneDriveAuthAttempted` one-shot guard (`sidebar.js:3465,3573-3578,3736`),
   `onedrive_auth_stuck` telemetry, `oneDriveAuthStuck` present in all 14 locale
   files. Backend half is live too: `_persist_ms_tokens` keeps the access token
   when Microsoft omits a refresh token (`auth.py:363-433`) and the license-403
   marker maps to `no_onedrive` (`onedrive.py:65`, 5 tests). Shipped in
   `060a6d0`, deployed per `handoff-2026-07-26.md:9-13` — with field proof in
   the same handoff (a user self-recovered and used OneDrive cleanly).
1. ✅ **popupConsentExplainer softened (2026-07-18, in master for 0.1.26)** —
   honest framing in all 11 locales: never reads your other emails; campaigns
   stored securely to power scheduling and follow-ups.
2. ✅ **Reply cancels pending follow-ups (2026-07-18, backend — DEPLOYED)** —
   `_get_filtered_contacts` applies `.is_("replied_at", "null")` before the
   per-condition filters (`followup_worker.py:124-148`), so replied contacts
   drop out for every condition, not just the not-opened one; three tests in
   `test_followup_reply_cancel.py`. Shipped in `4460729`, deployed per
   `handoff-2026-07-26.md`. **The follow-on action is done too:** the claim is
   back on the site — `docs/pricing.html:126` "stops automatically when someone
   replies", added in `bd606fd` only after it went live.

   *(A dangling sentence fragment from an earlier draft of this item lived here
   until 2026-08-08 and was deleted; it described the pre-fix state.)*

### ✅ Move the API to api.getoutmass.com — DONE 2026-08-12 (closed with #27)

> **Resolved.** The one remaining item — Railway's `BACKEND_URL` still pointing
> at the railway host — was confirmed changed on 2026-08-12. Every part of this
> entry has shipped; it stayed marked 🔧 for two more days, which is the same
> staleness the DMARC entry above had. The audit below is kept because it
> records how the halves came to ship six weeks apart.

### 🔧 Original entry (audited 2026-08-08)

> **Step 1 and the extension half of step 2 both shipped on 2026-07-14**
> (`eb5e81b`, folded into 0.1.25), and the entry was simply never updated:
> `extension/config.js:13-14` makes `api.getoutmass.com` the primary base with
> the railway host as fallback, and `manifest.json:15-16` carries both. Probed
> live 08-08: both return `{"status":"ok"}` — api.getoutmass.com through
> Cloudflare, the fallback through Railway direct.
>
> **What is NOT confirmed: the backend's own `BACKEND_URL` env var on Railway.**
> It is not in the repo, and no public probe distinguishes it — `AZURE_REDIRECT_URI`
> can be set independently (so the OAuth redirect proves nothing), CORS allow-lists
> several origins explicitly (so origin reflection proves nothing), and the
> unsubscribe page uses a relative form action. This variable stamps **tracking
> pixels, click-tracking links, unsubscribe links and Stripe redirect URLs** into
> outgoing mail — i.e. it carries the entire reason this item exists, since a
> recipient behind the GFW or a corporate filter is exactly who gets a broken
> tracking pixel and a dead unsubscribe link. If it still reads
> `outmass-production.up.railway.app`, the user-facing half of this fix has not
> landed at all.
>
> **Ali: Railway → web service → Variables → `BACKEND_URL`.** Or open any recent
> sent email and look at where the unsubscribe link points.

Original entry (for history):
The 2026-07-14 zh-CN churn exposed a structural reach problem: our API lives on
`outmass-production.up.railway.app`, and shared-platform domains like
railway.app are blocked wholesale by some corporate filters and national
firewalls (GFW) — users on those networks can NEVER sign in, and we only see
it as silence. 0.1.24 makes the failure honest (connectivity banner); this fix
removes the failure class. Steps:
1. **Ali:** Railway → web service → Settings → Networking → Custom Domain →
   `api.getoutmass.com` (Railway shows a CNAME target) → add that CNAME at the
   DNS provider → wait for the auto-provisioned cert → verify
   `https://api.getoutmass.com/` returns `{"status":"ok"}`.
2. **Code (next meaty extension release, to amortize the host-permission
   re-approval prompt):** extension `OUTMASS_BACKEND_URL` + manifest
   `host_permissions` → api.getoutmass.com (optionally keep the railway URL as
   a runtime fallback for resilience); backend `BACKEND_URL` env → new domain
   (Stripe redirect URLs + future tracking/unsubscribe links; old railway
   links keep working as long as both domains stay attached).
Bonus: branded tracking/unsub links also help deliverability.

### ✅ Fix the e2e CI suite — DONE 2026-08-04 (`25389b7`)

> **Resolved** with option (a), exactly as proposed: `e2e/chrome-stub.ts`
> supplies a `window.chrome` stub (runtime, storage, i18n, identity, alarms)
> installed via `page.addInitScript` in the `beforeEach` of both
> `extension.spec.ts` and `i18n-visual.spec.ts`. Verified three ways: 51/51 pass
> locally, the `e2e-tests` job has been green on every CI run since, and the
> red→green boundary lines up with that commit (run 30852879659 red at the
> parent, 30937885670 green at the first push after).

### ✅ Backend unit tests were dark in CI for 10 days — FOUND AND FIXED 2026-08-08

> Found while auditing the entry above, which opens with the words "unit-tests
> green". That was true when it was written and false by the time anyone read
> it again — the entry described a red CI and named the wrong job.
>
> `backend/tests/test_ai_language_contract.py` (added `bb2ea71`, 2026-07-29)
> built an assertion message as
> `f"{src.count('t(\"aiLang')} aiLang labels"`. A backslash inside an f-string
> **expression** is legal from Python 3.12 (PEP 701) and a `SyntaxError` before
> it. Local dev runs 3.14 and never blinked; CI pins **3.11**
> (`.github/workflows/ci.yml:30`), where pytest raised at COLLECTION time:
>
> ```
> collected 555 items / 1 error
> E   SyntaxError: f-string expression part cannot include a backslash
> !!!! Interrupted: 1 error during collection !!!!
> ```
>
> So **zero** backend tests ran in CI from 07-29 to 08-08 — including through
> the 0.1.27, 0.1.28 and 0.2.0 cuts. Nothing shipped broken (the suites were run
> locally every time, where they pass), but the CI safety net was not there.
>
> Fixed by hoisting the count into a local. Two things worth keeping:
> - **A syntax error in one test file silently disables every other one.** Not
>   "that file fails" — collection aborts and the whole job dies.
> - **A local/CI interpreter gap makes a whole class of error invisible.** A
>   sweep of all 106 backend files found no other instance. `ast.parse(...,
>   feature_version=(3,11))` does NOT detect this — it accepts the known-bad
>   snippet on 3.14, so any checker built on it must self-test first or it will
>   report a clean sweep it cannot actually see. A token-stream scan does work.
>
> Now that the job runs again, CI itself is the guard for the next one.

### ⬜ Separate the polluting game events from PostHog project 152466
Split back out on 2026-08-08 into the heading it originally had — it was
swallowed into the e2e-CI entry by `8d38b1a` and spent five weeks as an
orphaned paragraph under an unrelated title, which is a good way for an item to
never be done. PostHog project 152466 receives a game's events
(`match_started`, `lobby_viewed`); the org still has exactly one project, so no
separation has happened. Mitigating: the pollution was a single burst on
2026-06-19 (15 events in about an hour) and has not recurred in the seven weeks
since, so this is low priority — but the shared key is still in place, so it
can recur without warning.

**2026-08-15 — measured, not assumed:** `match_started` / `lobby_viewed` no
longer appear in the PostHog project's event schema at all; zero recurrence
since the single 2026-06-19 burst. The shared key remains the only residue,
so the item stays open at the lowest priority in this file.

Original entry (for history):
GitHub Actions CI: unit-tests green, **e2e-tests failing ~24/48 on every push
for a month** (Ali only noticed via the 07-03 email). Last green run =
06-03 21:35; first red = 06-03 21:49 → commit `76b6317` ("refresh announcements
on account switch"). Mechanism: `e2e/extension.spec.ts` loads `sidebar.html`
via **file:// with NO chrome stub** (`chrome` is undefined); 76b6317 added an
init-time `if (chrome.storage && chrome.storage.onChanged)` block — that guard
survives a chrome WITHOUT storage but **throws ReferenceError when `chrome`
itself is undefined**, killing the IIFE before the tab/JS handlers bind →
every interaction test fails (static CSS-visibility tests still pass).
**Fix options:** (a) cleanest — add a minimal `window.chrome` stub via
`page.addInitScript` in the spec's beforeEach (test-only, no production risk,
lets all 48 exercise real logic); (b) also audit init-path `chrome.*` refs
added since June (quota loadQuota etc.) if any still throw. Verify locally
with `npx playwright test` before pushing. Not urgent (product unaffected —
unit tests + manual verification carried the last month) but a red CI on every
push trains us to ignore CI, which is dangerous.

---

## 🧭 Exit-readiness — TRIGGER: $2k MRR + 3 consecutive months of growth (Ali, 2026-08-04)

Not a goal, an option to keep alive. Decision from the 2026-08-04 discussion:
exits in this market price on **MRR and its trend, never on user count** (free
users are a cost, not an asset). Realistic ladder: ~100 paying (~$1-1.5k MRR)
→ ~$35-60k marketplace sale (Acquire.com/Flippa) and TinySeed application
territory; ~1000 paying (~$10-15k MRR) → $350-600k+ at 2.5-4x ARR. Strategic
buyers (GMass, Mailmeteor, cold-outreach suites missing an Outlook leg) pay
for the Graph sending infra + store history + SEO assets, not the P&L. VC
path: not applicable (feature-market, capped TAM) — don't spend time on it.
Biggest multiple discount we cannot fix: platform risk (Chrome/Edge stores +
Graph API dependency).

**Standing rules until the trigger (all cheap, mostly already true):**
- Books stay clean: Stripe is the ledger; assets (domain, Azure app, store
  accounts, PostHog) stay owned by Metis Ltd and transferable.
- Keep the diligence trail buyers pay a premium for: tests, runbooks,
  handoffs, telemetry, `emails_sent_total` lifetime metrics.
- Store ratings/reviews are an ACQUISITION asset too (featuring playbook).
- **Never sign exclusivity** in partnerships (HeyReach-class outreach) — it
  handcuffs a sale.

**At the trigger:** revisit deliberately — Acquire.com listing and a TinySeed
application are each ~two weeks of prep from our books. Until then the best
exit strategy is growing MRR.

---

## ⏸️ Deferred (deliberately)

- **Send pacing Phase 2/3:** account-type awareness (personal ~300/day vs business
  ~10k/day) + auto-spread a very large list over several days (GMass-style "N/day").
  Phase 1 (30/min pacing + warning) already protects business accounts; Phase 2
  matters most for personal accounts.
  - **#63 — promoted out of deferral (approved 2026-08-18): one-click
    "spread this campaign over N days".** Headline of 0.2.3; trigger = Edge
    publishes 0.2.2 (don't reset their review queue). Bundle with #59 and
    #56 — one locale pass ×14 files, one review, one zip. Scope: UI control
    computing the existing daily cap + worker honoring a per-campaign day
    budget; NOT rotation, NOT warmup (that boundary stays). The data
    (90d): median send is 4 recipients, but 5 users fired 17 sends of
    300+ (max 1,876 in one sitting) and nobody heeds the large-send
    warning — the feature protects our heaviest users from themselves,
    earns the GMass "N/day" parity claim, and surfaces Starter's value at
    the exact moment someone uploads a big list. Design note + Ali onay
    before build (user-affecting).
    - **0.2.3 release ritual addition — store-listing review pass (both
      stores, all 13 languages), caught 2026-08-18:** (1) the live
      listing claims "our servers never store email content" — false as
      written: scheduled sends and follow-ups keep subject+body server-side
      and campaigns persist for reports; soften to "sent from your own
      Microsoft account; we never read your inbox; campaign content is
      stored only to run scheduled sends and reports." (2) "30-day
      money-back guarantee, no questions asked" appears in the listing —
      either mirror it on the pricing page and EN listing (a promise in one
      language is still a promise) or remove it; Ali decides. (3) zh (and
      possibly other) listings have no screenshots/promo tiles — add the EN
      set now, retake with zh UI later. Also fold in #63's new copy and any
      claim the release makes true.
  - Market datapoint #2 (2026-08-18): Mary Bass (Business Solutions Weekly,
    #31 prospect) chose QuickMail ($49/mo, 5k emails) over us for 6k contacts
    at a-few-per-day over weeks — "better able to handle that volume." The
    honest read: that job needs inbox rotation + warmup, not just auto-spread;
    entering it is a category change, not a feature. (Datapoint #1 was Alan /
    per-recipient attachments → SecureMailMerge, 2026-07-06.)
- **Edge 0.2.2 LIVE 2026-08-20** (uploaded 08-15 → exactly the 5 days Ali
  predicted; verified on the public listing: "Version 0.2.2 · 13
  languages"). Unblocks: the site email-language claim (both stores now
  carry it — needs Ali's wording onay), 0.2.3 planning (#63 headline +
  #59 + #56 + store-listing review pass), and starts #24's adoption
  clock — revisit the Mail.Read first-signin flag around 08-27 once the
  version spread drains toward 0.2.x.
- **Review asks (#61) — trigger refined 2026-08-20:** "prospect converts"
  alone is NOT the moment. mercedes converted AND sent their first campaign
  the same week, but the first-campaign session was effortful (encoding
  prompt, two CSV rejections, near midnight) — asking then would survey a
  tired user, and we cannot even attribute the session to a person
  (marketing@ ≠ necessarily Kevin). The ask fires on FELT value: a second
  smooth campaign, good open/reply numbers on the first, or a thanked
  support exchange — and it goes org-level through the relationship holder,
  who routes it ("whoever drives the campaigns"). Never right after a
  bumpy session, never "I saw you struggle" (telemetry-surveillance vibes),
  never incentivized. Ali's instinct caught this; write it down so the
  letter of a trigger never overrides its spirit again.
- **Marketing:** Quora drip answers (drafts ready). Directory submissions went
  out 2026-08-16; follow-through (#60) now has measured dates, not guesses:
  - **SaaSHub:** listing live + ownership VERIFIED same day — but "verified"
    and "approved" are two separate flags. The public page still says
    "Pending approval..." and carries `noindex`; site search, the
    *-alternatives lists and compare pages all wait on the second flag.
    ✅ APPROVED 2026-08-19 — the free queue took 3 days (their own UI
    threatened "up to 32"; the $75 Priority+ declined on 08-17 stayed in
    the pocket). Verified from outside: "Pending approval" gone from the
    public page, site search returns OutMass. Remaining: the
    *-alternatives cross-lists (gmass/mailmeteor/yamm) don't surface us
    yet — they rank by votes; check weekly, don't force.
  - **alternativeto.net:** ✅ APPROVED 2026-08-17 after Ali paid the $5
    priority review (worked as advertised: same-day-to-24h). Listing live
    with screenshots, UK origin, Chrome+Edge platforms. GMass and
    Mailmeteor alternative-pairings already linked from the original
    submission (they rode along with the paid review). YAMM pairing
    suggested 08-17 → sits in the separate suggestion-moderation queue
    ("can take a while", no paid fast-track, nothing is lost). Remaining:
    Ali ♥s the live GMass/Mailmeteor pairings (each at 0 likes; one like
    lifts them above the zero-like rows). Re-scrape gmass/mailmeteor/yamm pages in a few days to confirm
    cross-listing renders (note: their alternatives lists lazy-load —
    a markdown scrape can miss entries that ARE there; 08-17 false alarm).
  - Search engines: getoutmass.com is #1 for "outmass" on Google and Bing;
    the directory pages are noindex-while-pending, so `site:` checks before
    ~08-24 measure nothing.
  - **SourceForge (India + global):** submitted 2026-08-24 via
    sourceforge.net/software/vendors/new — a listing REQUEST form (their
    team reviews, "we'll be in touch"). Target shelf: their Mail Merge
    category, which already runs indexed "Best Mail Merge Software in
    India" pages. Two form quirks worth remembering: Product Description
    rejects anything that looks like a URL (domain names included, so
    outlook.office.com had to go) and caps at 1000 chars; Platforms
    Supported means INSTALLED apps, so SaaS/Web alone is the honest
    answer for an extension. Next step if approved: create a free
    SourceForge account with support@ to manage the page. Paid marketing
    packages declined as everywhere else.
  - **SourceForge: APPROVED 2026-08-25.** Page live at
    `sourceforge.net/software/product/OutMass/`, created by SourceForge from
    our 08-24 request; Logan Abbott emailed asking us to claim it. Verified
    independently (not via the email link): our submitted description is
    published verbatim, categories Bulk Email + Mail Merge, company shown as
    Metis Information Technologies Ltd / United Kingdom / Founded 2026,
    website link to getoutmass.com, Platforms "Cloud", Training
    "Documentation", Support "Online". Cross-listed under Alternatives:
    ActiveCampaign, BrandMail, GBlast, MailMerge365, EmailOctopus, **GMass**,
    lemlist - the GMass and MailMerge365 adjacency is the whole point of this
    listing.
    - **Ali's move (not mine - account creation):** go to sourceforge.net
      directly, sign up with **support@getoutmass.com** (shared box; the page
      will attract vendor-package sales mail), then "Claim this page" on the
      product page. Decline the paid marketing packages as everywhere else.
    - **Claim APPROVED 2026-08-27** ("OutMass Page Claim Approved"). The mail
      landed in support@'s JUNK folder, as the first SourceForge mail did -
      check there before concluding nothing arrived.
      - **It is three pages, not one.** The approval says OutMass also has a
        page on **Slashdot** and **Top Business Software**. Verified:
        `slashdot.org/software/p/OutMass/` exists and carries a PARAPHRASE of
        our description - "automated follow-ups are sent, and these cease as
        soon as a reply is received". So the overstatement travelled, in
        someone else's words. After editing the SourceForge page, check
        whether the edit propagates or whether each surface needs its own.
        (The privacy sentence is absent from all of them: our 08-24 submission
        never carried that paragraph. It lives only in listings.json.)
      - **Free, worth taking:** they offer buyer-intent notifications by email
        at no cost - which companies viewed the listing. It is the lead-in to
        their paid tier, but the free half is a real signal.
      - **A trade, not a gift:** placing a SourceForge badge on getoutmass.com
        makes our page "automatically rank higher in our category". Real lever
        on a site with 20M monthly visitors, paid for with a third-party badge
        and an outbound link on our own page. Ali's call, not obvious either
        way.
      - **Declined as everywhere:** the marketing packages, and the claim that
        upgrading makes ChatGPT and Gemini more likely to mention us. That is
        an upsell wearing the GEO research's clothes.
    - **Claim submitted 2026-08-25**, "Claim Received - being evaluated".
      Account: username `outmass`, support@getoutmass.com, country Turkey
      (personal/phone country; the listing's own country must stay United
      Kingdom - verify after approval). Claim form: Founder, company number
      17114932 given in Comments, paid-advertising toggle set to No,
      LinkedIn left blank rather than invented. Company Size answered with
      the smallest true option; the TrustRadius lesson is that inflating it
      buys a listing we would then have to defend.
      The paid pitch arrived on the confirmation page itself - "marketing
      packages... hundreds of software buyers per month" plus buyer-intent
      data. Declined by default; the free listing is the whole plan.
      Note the consent that came bundled with Submit: "I agree to receive
      communications from SourceForge.net" is not separable from the terms
      checkbox, so sales mail to support@ is expected, not a leak.
    - **Two edits once access lands:**
      1. The description says "Automated follow-ups re-contact non-openers and
         stop the moment someone replies." The mechanism is a daily reply
         check (`reply_detector`, beat `crontab(hour=5)`), which the previous
         sentence already discloses. Same overstatement corrected on the blog
         on 08-24 - change to "stop once a reply is detected". `not_opened`
         itself is accurate: `followup_worker` excludes repliers regardless of
         condition.
      2. "Videos and Screen Captures" is an empty section. The 5 screenshots
         recompressed for SoftwareSuggest fit here; the YouTube gap video
         (channel plan item 4) fills the video slot on this page too, making
         it the fourth surface that video would serve (Edge, G2, site,
         SourceForge).
    - Reviews sit at 0.0/5, "hasn't been reviewed yet". Another destination for
      the #61 trigger when a user's value is *felt* - never solicited, never
      incentivised.
  - **SoftwareSuggest language count is stale:** submitted 08-19 as "11
    languages"; the product ships 13 (14 locale files - `zh` and `zh_CN` are the
    same language). Understated rather than oversold, so not urgent; fix on the
    next portal visit. `CLAUDE.md` carried the same stale 11 and was corrected
    2026-08-25.
  - **SoftwareSuggest (India):** ✅ LIVE 2026-08-20 at
    softwaresuggest.com/outmass — approved in under 24h (they said up to
    3 business days). Verified from the public page: our short/long
    descriptions, three plans and FAQs published verbatim, no mutations.
    Original submission notes (2026-08-19): Free tier; vendor profile HQ set
    to United Kingdom (signup widget locks HQ to phone country — the
    portal's Company Profile does not). Full listing: 12 features, 11
    languages, 3 plans, 5 screenshots (compressed under their 150 KB cap),
    6 FAQs (no URLs allowed in answers), original-content descriptions
    (they run plagiarism checks — G2/site copy was rewritten). Expect the
    sales call pitching paid packages: decline, free listing is the plan.
    Competitors linked: GMass, Mailmeteor, QuickMail (YAMM and
    SecureMailMerge are not in their catalog).
  - **TrustRadius:** closed to us — vendor access requires a LinkedIn
    company page with 10+ employees (verified on the form 2026-08-19).
  - **Softonic (revised understanding 2026-08-25):** there is NO auto-listed
    OutMass page to claim - the 08-17 note that said otherwise was never
    verified. Panel search, web search and a direct URL guess all come up
    empty, and softonic.com serves a CAPTCHA to any external check. The org
    claim (approved 08-19) and an app claim are separate things; "claim"
    kept answering "You already have a claimed organization" because the org
    was all we ever had. So this is a NEW listing, not a correction of an
    existing one - a surface we now own and maintain.
    - Platform **Web apps** (no binary upload - the shelf we wanted),
      Category **Productivity** (the default "Browsers" would have listed us
      as a browser).
    - Icon: needed 512x512, largest we had was 200. `docs/ss/logo-512.png`,
      redrawn from the generator's own numbers rather than upscaled.
    - Screenshots: Softonic demands >=1920x1080, our captures are 1280x800.
      `docs/store-listing/frame-screenshots.py` places each capture at native
      resolution on a 1920x1080 canvas with a soft shadow - nothing is
      resampled, so no blurred UI text. Output in `docs/ss/softonic/`.
    - Description: `docs/store-listing/softonic-en.txt`, NOT the generated
      `descriptions/en.txt`. See the claims item below.
    - Their "Create with assistant" AI description generator is declined by
      default: it would write claims nobody audited.
  - **Softonic:** ✅ claim APPROVED same day (2026-08-19, Certificate of
    Incorporation did the job). Remaining 5-minute move: in the Publishing
    Center, replace their auto-generated OutMass copy with the audited
    G2 short+long text and check the screenshots. Bonus unlocked: reply
    access to user reviews + visits/downloads metrics.
    - **APP SUBMISSION REJECTED 2026-08-31 — the door is closed, do not
      retry.** Submitting OutMass 0.2.2 as an app came back REJECTED with a
      category rule, not a quality note: *"Chrome Extensions are not currently
      allowed on the Softonic website... we only accept standalone web
      applications at this time."* So there is no corrected version to
      resubmit — nothing about our package changes the answer. The mail
      invites a "corrected version"; that invitation is boilerplate and does
      not apply. Their note says they review content policies regularly, so
      the only thing that reopens this is a policy change on their side, or
      OutMass gaining a standalone web app. **Re-check only if one of those
      two happens.** The claimed COMPANY page from 08-19 is unaffected and
      still ours — the 5-minute copy fix above is still worth doing.
  - **GetApp + Software Advice: submitted 2026-08-21, "Under review, 1-2
    business days"** (→ expect ~08-24/25). Full channel profiles done the
    same evening: default+category descriptions, screenshots with
    captions, pricing details (no "downgrade anytime" claim — the panel
    only offers upgrades), pricing URL. Listing score 72%→88%→~98%;
    only remaining recommendation is product video (+2%), which waits
    for the video afternoon. Reviews stay deliberately at 0 (#61).
  - **G2 Digital Markets → Capterra: ✅ LIVE 2026-08-21** at
    capterra.com/p/10057851/OutMass (3 business days; the NZ locale page
    exists too and Google has indexed both). Verified from the public
    page: audited description verbatim, our screenshots with our
    captions, plans correct. Next 5-minute move: in the
    app.g2digitalmarkets.com panel, publish the same listing to GetApp
    and Software Advice (free, unlocks post-approval). The G2.com
    product page attaches via the my.G2 vendor account when their sync
    lands. Original submission notes:
  - **G2 Digital Markets:** submitted 2026-08-17 via
    app.g2digitalmarkets.com (account: support@getoutmass.com, company
    Metis Information Technologies Ltd, UK). Their own confirmation screen
    says review within 1-2 business days → publishes on Capterra; add
    GetApp + Software Advice from the panel after approval. Every section
    was audited against the live product; the AI draft's two real errors
    were caught before submit (calendar-month quota reset claim — ours is
    anchor-day; English-only language list — we ship 12+). Still to do:
    the separate G2.com profile via sell.g2.com/create-a-profile.

---

## ✅ Done in this stretch (for context)
Telemetry EU fix · Railway healthcheck (zero-downtime deploys) · sign-in auto-retry
· M365 FAQ + Fix A error message · Stripe verified end-to-end · 13 user-loss leak
fixes (`docs/plans/2026-06-24-user-loss-leak-fixes.md`) · async immediate send (no
more 502) · rate-limit pacing (30/min) + large-send warning.

**Deployed 2026-06-25** (`449be63`, verified live on prod): cross-campaign dedup
fix · P2 #1 non-UUID tracking ids → clean 200 (no 500) · P2 #2 benign-noise filter
(server `{"status":"filtered"}` + client) · P2 #3 feedback reassurance · FAQ
reframed (M365 work/school now supported by default after publisher verification).
