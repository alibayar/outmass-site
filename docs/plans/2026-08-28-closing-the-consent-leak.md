# Closing the consent leak (#48 / #24)

**Decision:** Ali, 2026-08-28 — "kesinlikle kapatmaya çalışalım."

**Status:** plan written, NOT implemented. §4 needs approval before any code.

---

## 1. The size of the thing

People, not attempts. An anonymous id is threaded to its account through
`$identify`'s `$anon_distinct_id`, which is the only link between the two
halves of one person's timeline.

| | 30 days | 60 days |
|---|---|---|
| People who started a sign-in | 39 | 73 |
| Reached an account | 22 | 44 |
| **Never did** | **17** | **29** |
| Lost | **44%** | 40% |

Four in ten never get in. In the last thirty days we gained 22 accounts and
lost 17 people at one screen.

At our observed 10% free-to-paid rate those 29 would have been ~3 paying
customers — on a base of 6. The people who bail probably convert worse than
the ones who push through, so treat 10% as a ceiling; even half of it is one
or two customers we do not have.

Every directory listing and blog post this month feeds the top of this funnel.
They all walk into the same door.

## 2. The only real lever, and why it is not simply "flip the flag"

`FIRST_SIGNIN_INCLUDE_MAIL_READ=false` makes the first consent screen ask for
Mail.Send + User.Read + offline_access instead of adding Mail.Read, which
Microsoft renders as **"Read your mail"** — the most alarming line we show
someone who has not sent a single email yet.

Everything that was supposed to block it is already built and verified today:
migration 024 applied (ledger, 2026-08-28), `/settings` returns the field, the
sidebar polls it and raises a one-click re-consent banner
(`extension/sidebar.js:156`, `:199`), and `reply_detector` degrades to a skip.
The docstring claiming otherwise was twenty days stale and is now fixed.

**But the flag is global, and that is the real blocker.** In
`routers/auth.py`:

```python
wants_mail_read = FIRST_SIGNIN_INCLUDE_MAIL_READ or include_mail_read
scope = MS_GRAPH_SCOPES if wants_mail_read else MS_GRAPH_FIRST_SIGNIN_SCOPES
```

`/auth/login` has no identity — nobody is authenticated yet — so it cannot
tell a first sign-in from a returning user re-authenticating. Flip the flag
and **every** re-auth gets the narrow ask: the reconnect banner, an expired
token, the eight dead Microsoft connections we are already carrying. The
callback then records `has_mail_read_scope = False` for someone who had it,
their refresh narrows to match (`models/ms_token.py:343`), and reply detection
stops.

That is recoverable and visible — on 0.2.0+. **Yesterday's version spread: 16
of 54 reporting installs are on 0.2.x, 38 are on 0.1.x.** Seventy percent of
the installed base cannot see the banner that would tell them.

So flipping today trades a leak we can measure for a silent downgrade we
cannot, in the population least able to notice.

## 3. A second finding: the primer may be part of the leak

`popupConsentExplainer`, shown before we send anyone to Microsoft:

> "Microsoft will ask permission for OutMass to send emails **and detect
> replies** from your own Outlook account."

Two problems. It becomes false the moment the flag flips — the screen will not
mention replies. And today, unflipped, it **pre-announces the alarming
permission**: we warn people about "reading your mail" before they have even
seen the screen. Nobody has ever tested whether that primer helps or hurts.

## 4. What to build — needs approval

All three ship in **0.2.3**, before the flag is touched.

**(a) Protect the returning user.** The extension knows whether it already has
a stored account; the server cannot. So on re-authentication — the reconnect
banner, an expired session, any flow where `chrome.storage` already holds a
user — the extension calls `/auth/login?include_mail_read=true`. First sign-in
sends nothing and gets the narrow ask. No server change; the parameter already
exists and is already honoured.

Residual risk, stated plainly: a 0.1.x client never sends the parameter, so a
pre-0.2.0 user who reconnects after the flip is still narrowed silently. That
population is the eight dead connections plus whoever expires next, and it
shrinks every week as 0.2.x spreads. Ali's dead-8 reconnect emails — drafted
and waiting — should go out BEFORE the flip, which turns most of that
population into 0.2.x users on their way back in.

**(b) Fix the primer, and shorten it.** Drop "and detect replies" — it will be
untrue, and it advertises the permission we are removing. Proposed:

> "Microsoft will ask permission for OutMass to send emails from your own
> Outlook account. Your campaigns are stored securely so scheduling and
> follow-ups can run."

Fourteen locale files; the suite enforces parity.

**(c) Gate the onboarding modal on being signed in.** A brand-new install's
first view is a full-screen tutorial about CSV upload, over the sign-in
banner (`showOnboardingIfFirstRun`, `sidebar.js:4390`, called at `:4447`).
Fire it after first login instead. This is upstream of `signin_clicked`, so
it can never be credited against the 40% — it is a separate small wrong.

## 5. Then flip, and what we will actually learn

Order: 0.2.3 published on both stores → dead-8 emails out → set
`FIRST_SIGNIN_INCLUDE_MAIL_READ=false` on the Railway **web** service.

**Measurable:** the whole-leak rate. 44% over thirty days, n=39. If it falls
to roughly 25% we would see it inside two months — the numbers are small but
the effect would not be.

**Not measurable, and nobody should pretend otherwise:** whether the
improvement came from removing Mail.Read specifically. Microsoft never tells
us which scope someone declined, and the explicit-decline bucket is four
events in eighteen days — halving *that* would take on the order of two
hundred days per arm.

So the case for this is mechanism, not a forecast: we stop asking to read
someone's inbox before they have sent anything. If the rate also improves, we
will know the leak got smaller without being able to prove why.

**Rollback:** one variable, no deploy. Existing narrow-consent users keep
working — their refresh reads `has_mail_read_scope` per user, so flipping back
does not disturb them.

## 6. What this plan deliberately does not do

From the four-lens review, verified and set aside: no `prompt=consent` (adds
friction to the 65% who already succeed), no `login_hint`/`domain_hint`
(both need an identity a first-time install does not have), no admin-consent
flow (zero AADSTS90094 in sixty days, and our callback requires a `code` that
Microsoft's admin-consent redirect does not send), no Publisher Attestation
(does not touch the consent screen), and no heuristic splitting the seven
unexplained `access_denied` events — seven points is guessing in a
classifier's clothes, and `/auth/callback` is an unauthenticated GET a scanner
can forge.
