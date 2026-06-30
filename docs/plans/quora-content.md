# OutMass — Quora content tracker

Living doc for the Quora drip (target: one new answer every ~2 days). Internal —
`docs/plans/` is excluded from the public Jekyll site.

**Playbook (keep doing):**
- **READ BEFORE YOU WRITE (hard rule).** Before answering a question, scrape and
  read EVERY currently-readable existing answer on it (`firecrawl scrape <url>
  --only-main-content --wait-for 3500`). Then ask: (1) Is there already a
  satisfying answer? (2) Can we be clearer / more thorough? (3) Can we add
  genuinely *different* information? If we can't beat it or add a distinct angle,
  **SKIP the question** and pick another. Never post a weaker rehash of an answer
  that already exists — it adds nothing and risks a collapse/down-rank.
- Lead with genuine value; teach something real before mentioning OutMass.
- One disclosure line: `(Disclosure: I work on OutMass.)`
- **No in-body link while the account is new** (Quora links are `nofollow` = no SEO,
  and promo links on low-authority accounts get collapsed). The link lives in the
  **profile bio + credential**. Revisit once the account has upvotes/authority.
- **Vary the angle every time** — never repeat the native Word steps that every
  other answer already covers. Find the gap the existing answers leave.
- Verify every product claim against code/pricing before posting (we did 2026-06-26).

**Verified claim bank (all true as of 2026-06-26):** Outlook *web* only · CSV merge
(first name/company/custom fields) · open+click tracking · reply detection (live
daily beat) · scheduled sends · follow-ups · sends via your own M365 acct through
Microsoft Graph · individual emails (no BCC) · unsubscribe links + suppression ·
pacing ~30/min (per-minute throttle; daily 10k auto-spread is NOT built — only a
large-send warning) · Free 250/mo, Starter $9/2,500, Pro $19/10,000.

---

## ✅ Posted

### 1. "What are the best alternatives to GMass?" — posted 2026-06-20
URL: https://www.quora.com/What-are-the-best-alternatives-to-GMass
Angle: *provider-dependent* — Gmail → Mailmeteor/YAMM/Saleshandy; but all are
Gmail-only, so on Outlook → OutMass. (Ali's posted wording opens "GMass is
genuinely good — but the catch most people hit is that it's Gmail-only…")
Stats: 6 views, 0 upvotes (as of 06-25).

### 2. "Can you perform a mail merge in Outlook 365?" — posted 2026-06-26
URL: https://www.quora.com/Can-you-perform-a-mail-merge-in-Outlook-365
Angle: *deliverability/spam-safety* — built to complement the one existing answer
(which warns about account suspension but doesn't say how to do it safely). The
"how not to get flagged" checklist (send individually, pace, unsubscribe, watch
replies/bounces) IS OutMass's design. Full text:

> Yes, and the others are right on both counts: the only built-in route is through **Word (desktop) → Mailings → Start Mail Merge**, and a careless mass-send is a fast way to get your Microsoft 365 account throttled or suspended. So the real question isn't *can* you — it's how to do it **without** torching your sender reputation.
>
> A few things that actually keep you out of the spam folder (and out of trouble with Microsoft):
> - **Send individually, from your own mailbox** — not one email with 500 people in BCC. Each recipient should get a real 1:1 message.
> - **Pace your sends.** Microsoft 365 throttles you at roughly **30 messages a minute** (and ~10,000 recipients/day); blasting past that looks like spam behavior and is exactly what gets accounts flagged. Drip them out.
> - **Always include a working unsubscribe** and honor it — that's what separates permission-based outreach from spam (and it's legally required in most places).
> - **Track replies and bounces** so you stop emailing dead or unhappy addresses.
>
> The native Word merge does the first one but none of the rest — no throttling, no unsubscribe, no reply handling. If you'd rather have those handled for you, **OutMass** is a Chrome/Edge extension that runs mail merge inside **Outlook on the web** and adds exactly this: it sends individually through your own Microsoft 365 account via Microsoft's official API, automatically paces sends (~30/min) to stay under Microsoft's throttle, warns you before very large lists, adds unsubscribe links, and detects replies — plus open/click tracking, scheduling and follow-ups. Free up to 250 emails/month.
>
> Bottom line: mail merge from Outlook is fine **if** it's permission-based and paced. Get consent, throttle your sends, include unsubscribe — whether you do that by hand through Word or let a tool like OutMass handle it.
>
> *(Disclosure: I work on OutMass.)*

### 3. WARM-UP (no product): "How do I send a personalized mass email with attachments in Outlook?" — posted 2026-06-26
URL: https://www.quora.com/How-do-I-send-a-personalized-mass-email-with-attachments-in-Outlook
Angle: *no real existing answer* — the other "answers" were off-topic (PHP / Jira
spam). The true pain — **Word mail merge CANNOT attach files** — was unanswered.
Pure value: send a OneDrive/SharePoint **link** (best for deliverability), or the
**Mail Merge Toolkit** add-in, or individual sends. First genuinely-helpful answer
on the question. Full text in chat thread 2026-06-26.

---

## 🗓️ Active 1/day sequence (2 value : 1 product — warms the account, avoids promo-flag)

Cadence (2026-06-26): 1/day is fine **only** at ~2:1 value-to-product on a new account
AND only after applying READ-BEFORE-YOU-WRITE. The first two warm-ups we planned
(bulk→spam, Outlook limits) turned out to be weaker rehashes of strong existing
answers, so we **skipped** them and hunted thin-competition questions instead.

- **❌ SKIPPED — bulk→spam:** existing top answer is more thorough than ours
  (SPF/DKIM/DMARC, Postmaster/SNDS, Feb-2024 Google rules). Can't beat → skip.
- **❌ SKIPPED — Outlook limits/BCC:** existing answer already gives 10k/500/100 and
  is *more* precise (throttle is "adaptive, not a fixed number"). → skip.
- **✅ POSTED 06-26 — Warm-up A:** personalized mass email **with attachments** (Posted #3 above).
- **⬜ NEXT — Warm-up B (no product):** "What is the best way to send an email to many people without using Mail Merge?"
  https://www.quora.com/What-is-the-best-way-to-send-an-email-to-many-people-at-once-without-using-Mail-Merge
  Angle: existing answer is one thin BCC anecdote — we give the full picture (BCC
  caveats + Contact Group/distribution list + when a real tool is worth it). Full
  text in chat 2026-06-26.
- **⬜ THEN — PRODUCT (Day 3):** "How do I send a mass email without showing the other recipients in Outlook?"
  https://www.quora.com/How-do-I-send-a-mass-email-without-showing-the-other-recipients-in-Outlook
  Angle: SHARPENED — acknowledge the existing answer covers BCC + Word merge + ESP,
  then add the missing gap: lightweight mail merge **inside Outlook on the web**,
  from your own mailbox (OutMass). Full text in chat 2026-06-26.

## 📥 2026-06-26 — inbound Quora requests/suggestions (read-before-write applied)

Ratio now **2 product : 2 warm-up** live (attachments + without-mail-merge). Scraped &
read existing answers on three inbound questions:

- **✅ POSTED 2026-06-27 (warm-up) — "tracking email conversations open but not urgent"** (DIRECT request, Faye)
  https://www.quora.com/What-is-the-best-system-for-tracking-email-conversations-that-are-open-but-not-urgent
  Existing answer MISREAD it (explained open-*tracking*/pixels, not open-*conversations*).
  We answered the REAL question — inbox triage for non-urgent pending threads (Flag+due,
  "Waiting" category, Search Folder, conversation view, snooze). Pure value.
- **✅ POSTED 2026-06-27 (value-lead) — "batch email when business depends on fast replies"**
  https://www.quora.com/How-can-I-batch-email-when-my-business-depends-on-fast-replies
  Re-checked at **8 answers** (was 1) — still all spam/boilerplate (Thallu.COM ×4,
  mass-Gmail-accounts, an off-topic insurance rant, one generic ESP-pitch); NONE address
  the actual "fast replies" tension. We're the only on-target answer: small paced waves +
  individual sends + reply-catching workflow.
- **✅ Product — "send mass email without showing recipients"** (re-checked; existing answer
  still strong) → sharpened Outlook-web-native draft. Full text chat 06-26.

Order (lean value): ~~tracking~~ ✅ → ~~batch~~ ✅ → **without-showing (product) ← NEXT**.
SKIPPED: "10,000 emails to one address" (spam/bombing — reputation risk) · "mail merge in
Gmail" (6 answers, off-target) · "organize Outlook add-ins" (not our product) · "ZeroBounce
alternative" (verification, not our product — optional pure-value warm-up later).

**2026-06-27 inbound:** ✅ QUEUED — "What is the best tool for sending multiple cold emails at once?"
(https://www.quora.com/What-is-the-best-tool-for-sending-multiple-cold-emails-at-once ; 2 answers —
strong product fit; read-before-write before drafting). SKIPPED: "tool that alerts a deadline hidden
in an email" (deadline detection, not our product) · "manage email without another dashboard" (broad
inbox-mgmt, weak fit — park). NOTE: posted 2 on 06-27 (Faye + batch) → hold further posts, resume 1/day.

**2026-06-29 inbound — ALL SKIPPED:** "Protect M365 from Kali365" + "access M365 from third-party
apps to reduce scam exposure (Kali365)" → **trust-trap**: pitching OUR third-party app on a
security/scam question reads as exploiting fear; off-target (we're not a security product), skip
firmly. "Do spam filters make personal block lists unnecessary?" → receiver/filtering side, off our
sender niche — skip. (Faye-tracking already answered.) Pipeline stays: without-showing (product, next)
→ cold-emails (product, RBW).

## ⬜ Queue (next targets — prioritized; pick the top unposted each cycle)

1. **"How do I send a mass email without showing the other recipients in Outlook?"**
   https://www.quora.com/How-do-I-send-a-mass-email-without-showing-the-other-recipients-in-Outlook
   Angle: the BCC trap — BCC looks lazy, breaks personalization, and trips spam
   filters. The right way is individual 1:1 sends. Native Outlook can't; OutMass
   sends each person their own email (their name, no one else's address visible).

2. **"What is an alternative free program to a Microsoft Word mail merge?"**
   https://www.quora.com/What-is-an-alternative-free-program-to-a-Microsoft-Word-mail-merge
   Angle: Word merge is desktop-only + no tracking. Free alternatives split by
   provider; for Outlook-on-the-web, OutMass (free 250/mo) adds tracking/follow-ups.

3. **"What's the best software for 'mail-merging'?"**
   https://www.quora.com/Whats-the-best-software-for-mail-merging
   Angle: "best" depends on where your mail lives — lead with the provider split,
   land the Outlook reader on OutMass.

4. **"Has anyone used GMass for email marketing?"**
   https://www.quora.com/Has-anyone-used-GMass-for-email-marketing
   Angle: honest GMass review (great for Gmail) → "if you're on Outlook it won't
   install at all; the Outlook equivalent is OutMass."

5. **"Are there any free software for mass e-mailing?"**
   https://www.quora.com/Are-there-any-free-software-for-mass-e-mailing
   Angle: free tier + send-from-your-own-mailbox (deliverability) vs bulk-relay
   tools; OutMass free 250/mo for Outlook users.

6. **(Microsoft Q&A, not Quora) "What mass email platform do you use? (like GMass but for Outlook)"**
   https://learn.microsoft.com/en-us/answers/questions/4732892/what-mass-email-platform-do-you-use
   Angle: highest intent of all — someone literally asking for "GMass but for
   Outlook." Different platform (MS Q&A) but worth an answer.

---

## 📊 Performance log (update on each `/Your content` check)

| # | Question | Posted | Views | Upvotes | Notes |
|---|---|---|---|---|---|
| 1 | best alternatives to GMass | 2026-06-20 | 6 | 0 | low engagement; broad Gmail-centric Q |
| 2 | mail merge in Outlook 365 | 2026-06-26 | — | — | fresh; high-intent Outlook Q |
| 3 | mass email **with attachments** (WARM-UP) | 2026-06-26 | — | — | thin/off-topic competition → we're the best answer |
| 4 | without mail merge (WARM-UP) | 2026-06-26 | — | — | improved a thin single-anecdote answer |
| 5 | tracking open-but-not-urgent (WARM-UP) | 2026-06-27 | — | — | direct request (Faye); existing answer misread the Q |
| 6 | batch + fast replies (value-lead) | 2026-06-27 | — | — | 8 answers but all spam/off-target; only on-target reply |
