# OutMass — Quora content tracker

Living doc for the Quora drip (target: one new answer every ~2 days). Internal —
`docs/plans/` is excluded from the public Jekyll site.

**Playbook (keep doing):**
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

---

## 🗓️ Active 1/day sequence (2 value : 1 product — warms the account, avoids promo-flag)

Cadence decision (2026-06-26): 1 answer/day is fine **only** at a ~2:1 value-to-product
ratio on a new account. Pure-value answers (NO OutMass mention) in our niche build
topical authority so the product answers later land credibly and don't trip Quora's
promo filter.

- **Day 1 — WARM-UP (no product):** "Why do my bulk emails go to spam instead of the inbox?"
  https://www.quora.com/Why-do-my-bulk-emails-go-to-spam-instead-of-the-inbox
  Angle: prioritized deliverability fixes (SPF/DKIM/DMARC → list hygiene → sending
  pattern → content → engagement). Pure expertise, zero product.
- **Day 2 — WARM-UP (no product):** "What is the maximum limit of sending mails in a Day from Microsoft Outlook? Also how many maximum bcc…"
  https://www.quora.com/What-is-the-maximum-limit-of-sending-mails-in-a-Day-from-Microsoft-Outlook-Also-how-many-maximum-bcc-can-be-sent-in-a-mail
  Angle: exact limits (M365 10k/day, 500/msg, ~30/min; Outlook.com ~300/day, 100/msg).
  Factual authority; closes with "BCC is bad → individual sends" (sets up Day 3, no
  product named).
- **Day 3 — PRODUCT:** "How do I send a mass email without showing the other recipients in Outlook?"
  https://www.quora.com/How-do-I-send-a-mass-email-without-showing-the-other-recipients-in-Outlook
  Angle: BCC ok for ~20, bad beyond → individual personalized sends (mail merge) →
  OutMass does it in one click. (Moved up from the queue below.)

Full drafts for all three live in the chat thread dated 2026-06-26.

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
