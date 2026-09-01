# Post-Microsoft Strategy Review — 2026-08-31

Internal. `docs/plans/` is excluded from the public Jekyll site.

Written the morning after the 0.3.0 store cut, to answer: *what changes when
Microsoft ships native Mail Merge (Advanced)?*

**Revision 5.** Each round is marked in place — **[R2]** … **[R5]** —
so what each draft got wrong stays visible rather than being tidied away. That
matters here more than usual, because the thing every draft was most confident
about is the thing the next one overturned:

| | claimed | overturned by |
|---|---|---|
| R1 | the differentiator is **unwanted** | a four-lens adversarial review |
| R2 | it was **never delivered** | the retention query |
| R3 | **nobody comes back**, and the paid half was never sold | Ali, 2026-09-01 |
| R4 | it was sold **twice**, and lost both times to defects | the incident of 2026-09-01 |
| R5 | that failure mode is **recoverable**, and today it was recovered | — |

R2's own summary line — "the central thesis held" — did not survive R3, and
R3's did not survive R4. Read §8 and §9 if you only read two sections.

---

## TL;DR

1. Microsoft's roadmap item **423047** (GA September 2026) covers **per-recipient
   field personalisation only**. It commoditises the **free half** of OutMass and
   does not touch the paid half.
2. The paid half has **real demand**: up to 8 of our senders configured a follow-up
   and sent; ≤9 tried A/B; 6 pressed AI Generate.
3. **Not one of them ever got the feature.** All three sit behind a Pro tier
   nobody is on today — though **[R4]** two people did buy it and leave; see
   item 9.
4. **[R2] But "nobody was told" is only true of follow-ups.** The A/B and AI walls
   have shown a visible alert since **2026-04-16**, with Pro purchasable since
   04-17. Four and a half months of visible wall and live checkout — and
   **[R4]** two sales in that window, both since gone.
5. So the thing that is falsified is not "users don't want it" — it is
   **"a bare alert converts."** All three walls state a rule and offer no price, no
   button, no path. Fixing that is item 1 below.
6. **[R2] The first draft's plan — measure one cycle, decide at month end — does
   not survive.** September's realistic wall-hit pool is **2–5 people**. At that n,
   observing zero upgrades is the likeliest outcome whether the true rate is 5% or
   25%. The plan would fire its "demote to Starter" rule by noise, one month late,
   after Microsoft's GA.
7. **[R3] And then the retention query landed, and it outranks all of the above.**
   Only **two accounts ever** have sent campaigns in more than one calendar month.
   July → August retention is **1 of 13 (8%)**. The longest relationship any real
   user has had with OutMass is **25 days**. The only follow-up ever created was on
   the founder's own test account — **no real user has ever received one.**
8. So the September priority is not the paywall. **It is asking the ~20 dormant
   users why they left** — one afternoon, no code, and the only instrument that
   returns a reason instead of another ratio.
9. **[R4] And the claim all three drafts rested on is false.** "Zero real Pro
   subscribers" was wrong: **two people bought Pro.** One asked for a **refund**
   after a bounce storm and got it; the other was lost to defects in an early
   version. So the paid half was never unsold — it was **sold twice and held
   neither time**, and both times the reason was the product failing, not the
   price, the packaging, or the differentiator. See §2 and §8.
10. **[R5] And on 2026-09-01, for the first time, two customers went to the
   brink over a defect and both stayed** — not for a feature, but because
   we answered within minutes, admitted the fault, and refunded on request
   without conditions. The first evidence in this file that the failure
   mode is recoverable. See §9, including why it should not become the
   headline.

---

## 1. What Microsoft actually ships

Roadmap **423047**, "Mail Merge (Advanced)" — preview Aug 2026, **GA September
2026**. Verified unchanged since 29 May (log in
`2026-08-24-microsoft-qa-answers.md`).

Its description covers one thing: letting the basic mail merge in new Outlook pull
**per-recipient fields**. Nothing in the entry mentions open or click tracking,
reply detection, follow-up sequences, scheduling, pacing, or reporting.

Also unchanged: **Exchange Online's limits** — 10,000 recipients/24h, 1,000 per
message, 30 messages/minute. Microsoft's own guidance still points bulk senders at
third parties. Advanced Mail Merge raises none of them.

**Read:** Microsoft is about to give away the part we give away, and is not
building the part we charge for.

---

## 2. What we measured

### Who we have (Supabase, 2026-08-31)

| plan | comp_plan | count |
|---|---|---|
| free | — | 54 |
| starter | **pro** | 4 |
| starter | — | 4 |
| pro | — | **2 — the founder's own test accounts** |

**[R4] "Real Pro subscribers: zero, in the five months since the gate was
written" — this is wrong, and it was the load-bearing claim of both earlier
drafts.**

Two people have paid for Pro:

- **miriam@osbornecapitalpartners.com**, 24 June. `oauth_completed` carries
  `plan: pro` at 13:06:13Z, twelve minutes after five upgrade clicks. She sent,
  240-odd of her messages bounced, she wrote to us three times that afternoon,
  and **she asked for a refund. We gave it.**
- One more, in the early versions, lost to defects.

The table above is still accurate about *today*: the two `plan='pro'` rows are
the founder's test accounts. What was wrong was reading "nobody is on Pro now"
as "nobody has ever bought it".

Also [R4]: `faisal@samaed.com`'s Starter is a **grant**, made after he hit
defects — he was among the first payers, but that row is not revenue. The
paying count is one lower than the plan column suggests.

### The funnel (PostHog, all time)

| step | people |
|---|---|
| `onboarding_completed` | 55 |
| `sidebar_opened` | 53 |
| `recipients_uploaded` | 37 |
| `test_send_completed` | 21 |
| `send_completed` | **26** |

**[R2] The 26 is contaminated.** It includes `bayar_ali@hotmail.com` and three
`freya_jowin*` accounts created hours apart on 2026-08-30 with `_th` and `_vn`
suffixes — almost certainly region tests. If so the real denominator is **22**, and
every ratio below gets *stronger*. **Open question for Ali.**

### Demand, and what happened to it

| feature | gate | tried | got it | was the refusal visible? |
|---|---|---|---|---|
| Follow-ups (toggled, then sent) | Pro | **≤8** | **0** | **No — silent until 2026-08-28** |
| A/B test | Pro | **≤9** | **0** | **[R2] Yes, since 2026-04-16** |
| AI writer (pressed Generate) | Pro | **6** | **0** | **[R2] Yes, since 2026-04-16** |

**[R2] Corrections to the first draft:**

- **"12 tried A/B" is at most 9.** Three of the twelve have zero `oauth_completed`
  and zero `send_completed` ever. `/campaigns/{id}/ab-test` sits behind
  `Depends(get_current_user)` (`campaigns.py:1470`), so an unauthenticated session
  cannot reach the 402. The first draft applied this exclusion to the follow-up
  column and then not to the one beside it.
- **Refusals observed vs inferred.** `feature_locked_followup` has **zero events,
  all time** — its tracker was only written on 08-28. The A/B branch has no
  `track()` at all (`sidebar.js:2316`). Only the AI writer has *observed* refusals:
  6, every one `error_code=feature_locked`, not a single technical failure.
  The honest ledger is **6 observed, ≤17 inferred.** Do not say "26 refusals".

### How many people actually hit the follow-up 402

| measure | figure |
|---|---|
| `followup_enabled` events | 20 events / 14 people |
| toggled **then sent within the hour** | **8 people** |
| distinct attempt *episodes* | 11 |
| **402s actually observed** | **0** |

`followup_enabled` fires on a checkbox `change` (`sidebar.js:2988`), so it counts
exploring. Only "toggled then sent" can reach `maybeCreateFollowup()`. Of the other
six: five never sent at all; bellmed's toggle was 3 days from their next send, far
outside the window.

**Still an upper bound**, and permanently so: `maybeCreateFollowup()` also returns
early and silently when the follow-up subject or body is empty (`sidebar.js:3009`),
with nothing tracking it. See §6, hardening.

### Who they are

| user | campaigns | follow-up attempts | client today |
|---|---|---|---|
| marketing@hrds.com | 18 | 1 | **0.2.0** (08-28) |
| faisal@samaed.com | 14 | 2 | **0.3.0** (today) |
| partnerships@lebedevaeducation.com | 8 | 2 | 0.1.22 (gone since 07-03) |
| tony@skylineprp.com | 6 | 1 | **0.2.0** (08-10) |
| premierconsortium@outlook.com | 3 | **3** | 0.2.2 (08-19) |
| lucia@skylineprp.com | 1 | 1 | **0.3.0** (today) |
| Helene@circularworkplaces.com | 1 | 1 | 0.2.2 (08-28) |
| collabs@identitycollectives.com | 1 | 1 | 0.2.2 (08-17) |

**[R2] Three corrections here.** Our most frequent sender is **not** hrds —
`hrcargosolutionexpress@outlook.com` has 31 sends and never touched follow-ups.
Only **premierconsortium** genuinely retried across sessions; lebedeva's three
toggles were two episodes on one day (two of them 4.4 seconds apart). And the
first draft called bellmed's exclusion "toggled after their last send" — bellmed
sent again on 07-17 and 07-27; the exclusion stands on the 60-minute window, not
on that reason.

---

## 2.5 Retention — **[R3] the thing neither draft measured**

Both earlier drafts argued about *monetisation*. Ali's retention query, run
2026-08-31, says we have been arguing about the wrong layer.

**Only two accounts in the product's entire history have sent campaigns in more
than one calendar month** — `faisal@samaed.com` (Jun + Jul) and
`tony@skylineprp.com` (Jul + Aug). Both have since stopped: faisal's last campaign
is **20 July**, tony's **6 August**.

| | |
|---|---|
| Real accounts that ever created a campaign | **24** |
| Active in ≥2 calendar months | **2** |
| July → August retention | **1 of 13 — 8%** |
| Longest relationship, any real user | **25 days** (faisal, 25 Jun – 20 Jul) |
| Monthly active senders | Jun 3 → Jul 13 → **Aug 7** |
| First campaign in May or June, still sending after 20 July | **0 of 6** |

Every user is the same shape: a burst of 1–34 campaigns over 0–25 days, then
silence. hrcargo sent **34 campaigns in 14 days** and vanished. hrds sent **20 in
12 days** and has not been back since 28 August. These are not tyre-kickers
sampling the product — they are people doing sustained real work, who then leave.

**The honest counter-reading**, which deserves stating: mail merge may be
*inherently* bursty. A recruiter runs a hiring campaign, then has nothing to send
for two months. That is the job's rhythm, not churn, and GMass and Mailmeteor live
with it too.

The evidence against that reading: our May and June cohort has had **two to four
months** to come back on a long cycle, and **not one has**. With n=24 on a
five-month-old product this is a strong indication rather than a proof, but it is
the way the evidence points.

**What this does to the comp experiment.** Three of the four accounts granted Pro
yesterday were already dormant when we granted it — tony (last campaign 6 Aug),
bellmed (27 Jul), lucia (16 Jul). Only Helene is recent (28 Aug), and her one
campaign sent zero. The four emails now in flight are therefore **reactivation**
emails, not a feature experiment. That is still worth doing — arguably more so —
but it is not the retention read the first draft claimed it was.

---

## 3. Why nothing was delivered

`POST /campaigns/{id}/followups` (`routers/campaigns.py:1412`):

```python
if user_model.effective_plan(user) not in ("pro",):
    raise HTTPException(status_code=402, ...)
```

That gate has existed since **2026-03-29** (`8e483bc`). We have never had a Pro
subscriber, so every attempt hit it.

For **follow-ups only**, the extension swallowed that 402 into a `log()` line —
off unless debug is enabled — until **2026-08-28**. The user ticked the box, wrote
a follow-up, pressed Send, watched the campaign go out, and got **no indication**
that the follow-up did not exist.

**[R2] For A/B and the AI writer this was never true.** Both 402 branches have
called `alert()` since **2026-04-16** (`fcf69a8`), and Pro has been purchasable
from the popup since 04-17.

**This is the most consequential correction in the document.** A visible wall ran
for four and a half months, in front of ≤9 A/B users and 6 AI users, with a working
checkout beside it, and sold **nothing**.

**[R2] Also anachronistic:** the first draft argued the AI button should carry a
`PRO` tag "like A/B and follow-up do". Both those tags were added **2026-08-30**
(`2dfae55`) — *after every toggle event in the dataset*. During the entire
measurement window **all three features looked free.** The AI tag is still worth
adding; the contrast used to justify it was not real.

---

## 4. What the walls actually say

> "Automatic follow-ups are only available on the Pro plan. Your campaign will
> still be sent — the follow-up was not scheduled."
> "A/B testing is only available on the Pro plan."
> "AI email writer is only available on the Pro plan."

Each states a rule. **None offers a price, a link, or a button.** The user learns
they cannot have the thing and is handed no way to get it. This breaks the
project's own rule for user-visible messages (`CLAUDE.md`): *"kullanıcı bunu
okuyunca ne YAPACAĞINI biliyor mu?"*

**[R2] Where the upgrade clicks actually come from** — the first draft guessed
"the quota banner or the pricing link". Measured:

| context | clicks | people |
|---|---|---|
| `account_tab` | 19 | 12 |
| `popup` | 10 | 8 |
| `modal` | 1 | 1 |
| `quota_modal` | 1 | 1 |
| `plan_picker` | 1 | 1 |

The load-bearing half holds — **not one upgrade click in the product's history came
from a feature wall.** The descriptive half was wrong: they come from the account
tab and the popup, and exactly one ever came from the quota modal.

**[R2] And the upgrade surface sells the wrong thing.** `upgradeModalFeatures`
reads *"Detailed reports + priority support"*, and `buildPlanRows` renders only
name, price and quota (`sidebar.js:3678-3720`). **No upgrade surface in the product
mentions follow-ups, A/B or the AI writer.** Only the website has ever said Pro
includes them. So even a correctly wired wall would route a follow-up-hungry
75-recipient sender to a page selling 10,000 emails they do not need.

---

## 5. The competitor comparison — **[R2] substantially rewritten**

The first draft concluded "our tier shape matches the market, so the shape is not
the defect", using GMass and Mailmeteor. Both legs were weak.

**GMass is Gmail-only.** Our own repo says so
(`docs/blog/gmass-for-outlook.html`: it "does not support Outlook, Microsoft 365,
or Exchange Online accounts"). Its $29.95 → $39.95 ladder reflects Gmail economics
and validates nothing about Outlook buyers.

**Mailmeteor is not an analogy — it is a rival selling exactly what we cannot.**
`mailmeteor.com/products/microsoft-outlook`, read 2026-08-31, sells Outlook mail
merge with *"Track real-time open, clicks and replies"* and *"Send auto-follow-ups
based on recipient activity (e.g., if no reply in 3 days)"*, at **$17.99 Premium**.

So the corrected picture:

| | platform | follow-ups from |
|---|---|---|
| GMass | Gmail only | $39.95 — not comparable |
| Mailmeteor | **Outlook too** | **$17.99 — and they actually deliver it** |
| OutMass | Outlook Web | **$19 — never once delivered** |

The first draft also said our Pro was "cheaper than both". **False:** $19 > $17.99.

**[R2] Stale public claim.** `docs/blog/mailmeteor-alternative-for-outlook.html`
still asserts Mailmeteor "is not an Outlook-native mail-merge tool". Their own
product page contradicts that today. Under the claims-follow-product rule this
needs correcting — the rule applies to claims about competitors as much as about
ourselves.

---

## 6. Recommendation — **[R2] changed**

### Do not change pricing in September — but on one leg, not three

The surviving reason is sufficient: **we have never observed a paywall that offers
a path.** Changing the mechanism and the price in the same month learns nothing
from either.

The other two reasons are gone or weakened. "The shape matches the market" now
rests on one comparable, and that comparable is a competitor who *delivers* the
feature. And the comp cohort is thinner than claimed: comping Helene, tony, lucia
and bellmed removes **four of our eight proven demanders** from the very pool the
experiment needs.

### "Measure one cycle, decide at month end" does not survive

Wall-hitter run rate, ever: **June 2, July 3, August 3.** September then loses
Helene, tony, lucia and bellmed to the comp, lebedeva to churn, and possibly hrds
to a stale 0.2.0 client. Realistic exposure: **2–5 people.**

At n=3, zero upgrades is the modal outcome whether the true rate is 5% or 25%.
The pre-registered rule *"if almost none convert → move follow-ups to Starter"*
would therefore fire on noise, with high probability, **one month later and after
Microsoft's GA**. That is the worst available outcome: pay the delay, still guess.

### **[R3] But the paywall is not the September priority**

§2.5 changes the ordering. Monthly retention is **8%**. A follow-up feature is
worth nothing to someone who runs one campaign and never returns, and a 14-day
trial is worth nothing to someone who does not come back within 14 days.

Fixing the paywall is still right — it is cheap, and item 1 closes a trap that
would *bill* people for a plan that does not unlock what they clicked. But it
optimises the conversion of a cohort that leaves either way. **The September
question is not "will the paywall convert." It is "why does nobody come back."**

The one action that answers it costs a day and no code: **ask them.** We have
roughly twenty dormant accounts with working email addresses, and a working
practice for exactly this — the five apology emails set the precedent. One short
"what stopped you?" email, async, no calls, is the only instrument that returns
a *reason* rather than another ratio.

### Instead: make the wall a trial, not a bounce

The machinery exists and we already run it by hand. `comp_plan` /
`comp_plan_until` (migration 032, applied and verified) merged by
`effective_plan()`, expiring by arithmetic with no beat task and nothing to undo.
Yesterday's four grants *are* manual one-month Pro trials.

Automate it at the wall: the upgrade modal offers **"Try Pro free for 14 days"**;
one endpoint sets `comp_plan='pro'`, `comp_plan_until = now + 14d`; one trial per
account, guarded by `comp_plan_until` being null. **No price change, no Stripe
change, no migration, fully reversible.**

That turns each September wall-hit from one bit (bounced / paid) into several: do
they *use* follow-ups when they can, do their campaigns improve, do they pay at
expiry. Same tiny n, far more information — and it is the only version of September
that satisfies §7's own imperative for a single non-comped user.

Then **defer the demote-to-Starter decision until a real n exists.** Treat
September as qualitative. Do not pre-register a threshold that noise will trip.

### This week

**[R3] Re-ordered after the retention finding.**

**[R4] Item 1 no longer survives as a gate.** Dormant accounts emit no events —
that is what dormant means — so "observe them instead" cannot answer why they
left, and Ali has said he would rather observe. Fine: the email is then optional
rather than blocking. What replaces it as the September priority is §8's truth
layer, which is owed on its own evidence and needs nobody's reply to justify.

| # | change | user-visible? |
|---|---|---|
| **1** | **"What stopped you?" email to the ~20 dormant accounts.** The only instrument that returns a reason. One day, no code. | **yes — needs approval; BCC outmassapp@** |
| 2 | Route the three 402 branches through `showUpgradeModal()`; suppress the quota sentence; **filter the catalogue to plans that unlock the feature** | **yes — needs approval** |
| 3 | Make the upgrade surfaces name what Pro contains (follow-ups, A/B, AI) | **yes — needs approval; 14 locale files** |
| 4 | `track("feature_locked_ab")` on the A/B 402 branch | no — ship now |
| 5 | Trial-at-wall — **demoted**: a 14-day trial cannot help a cohort with 8% monthly retention | **yes — needs approval** |
| 6 | Correct the Mailmeteor blog claim | **yes — public content** |

**Item 1's catalogue filter is not optional.** `buildPlanRows` shows every plan
above the user's own, so a Free user hitting the *follow-up* wall would be offered
**Starter** — they could pay $9 and still not get follow-ups. Shipping items 1–2
without the filter replaces a silent failure with a **billed** one, strictly worse
than today.

### Cheap hardening

- **`track("followup_abandoned_empty")`** at `sidebar.js:3009`. This one line is
  the only reason "8" must keep being called an upper bound, and it distinguishes
  *giving up while composing* from *hitting the paywall* — different problems,
  different fixes. The A/B path has the same silent guard (`:2303`).
- **Do NOT add a `feature_locked_ai` event.** `ai_email_generate_failed` already
  fires with `error_code` *before* the 402 branch (`sidebar.js:2677`); a second
  event would double-count the only refusal signal we have. (The R1 appendix asked
  for one — this corrects it.)
- **Guard the empty plan catalogue.** `buildPlanRows` `return`s inside its
  `forEach` when `Intl` throws on a currency. If every row fails, the modal renders
  with no plans and no way forward — in a dialog about to become our primary
  conversion surface, in fourteen locales.
- **Add an internal-account exclusion list to `scripts/ask.py`** —
  `bayar_ali@hotmail.com`, the three `freya_jowin*`, `outmassapp@outlook.com`,
  `mstest404@outlook.com`, `outmass.review`. There is none today, which is why the
  denominator question in §2 is open at all.

---

## 7. On Microsoft, finally

Microsoft is about to commoditise mail merge — the half we already give away. Our
answer has always been "we own everything after Send." That answer is still correct
on the merits: Microsoft is not building it, SecureMailMerge refuses to by design.

But **we have never sold it to anyone**, and — the correction that matters — for
two of the three features that was not because nobody was told. They were told,
plainly, for four and a half months, next to a working checkout, and nobody bought.

**[R3] And the retention data says even that is the second question.** Microsoft's
GA is a threat to a product that keeps its users. At **8% monthly retention** and a
longest-ever relationship of **25 days**, we lose people faster than Microsoft could
take them. Advanced Mail Merge shipping in September changes very little about a
funnel that empties itself every four weeks.

So the honest statement is not the one either earlier draft reached:

> **We do not yet have a retention problem caused by a missing differentiator. We
> have a retention problem, full stop — and we have never asked anyone why.**

Microsoft's September is a deadline for the *install* reason, and worth the two
days in §6 items 2–4. But the thing that decides whether OutMass exists in six
months is item 1, and it costs an afternoon.

---

## 8. [R4] We sold the paid half. Twice. And held neither.

Written 2026-09-01, after Ali corrected the fact all three earlier drafts were
built on.

Two people paid for Pro. Neither is on it now, and neither left for a reason
this document had considered:

**miriam@osbornecapitalpartners.com, 24 June.** Uploaded 417 recipients at
12:27. Clicked upgrade five times between 13:01 and 13:05. Bought Pro at
13:06:13. Sent at 13:08. By 13:52 she was writing to us:

> "All of the emails I programmed to send came back as delivery failed, saying
> the email is not valid. The email is valid because I can send it singularly
> just fine. 244 emails+ came back this way. I paid for Pro, please help me."

She wrote three times that afternoon. **She asked for a refund and we gave it.**
Forty-six minutes from paying to writing the first complaint.

**One more, in the early versions**, lost to defects.

### What that does to the argument

Every earlier draft asked a version of "why has nobody bought the paid half?"
That question was malformed. People bought it. It did not survive contact with
the product.

- R1 said the differentiator was **unwanted**. Wrong.
- R2 said it was **never delivered**. True of follow-ups, and still true — no
  real user has ever received one — but it is not why either Pro customer left.
- R3 said **nobody comes back**. True, and this explains part of why: at least
  two of the people who did not come back had already paid and been failed.
- R4: the failures were **defects**. A bounce storm the product neither
  explained nor helped with; and, in the earlier case, bugs.

So the September question is not pricing, packaging, or positioning. It is
whether the product works for someone who paid.

### What that means for the next three days

It vindicates the last two days rather than redirecting them. The row-cap
close-out (`01e18bb`), the reply-detector scoping (`c6a0b3b`), the paywall
that now offers a path, the follow-up that is no longer discarded — all of
that is "make the product work", which is now the demonstrated failure mode
rather than a guess.

It also settles the Delivery Report question this file did not know it was
about to be asked. miriam's 244 bounces are the loudest complaint in the
product's history, they cost the only Pro sale we can document, and the panel
proposed for them addresses exactly that. Split it:

- **The truth layer** — per-campaign delivered / failed / never-attempted from
  columns the database already has. One day, no Mail.Read, no privacy change.
  Owed regardless: the product currently misreports delivery in **both**
  directions. It told faisal "sent" while 110 recipients were never attempted,
  and told miriam "failed" while her mail was going out.
- **The bounce layer** — counts, invalid-address extraction, suppression.
  Needs Mail.Read, NDR parsing, a consent rewrite, and a corpus of real bounced
  mail across Exchange, consumer Outlook.com and a non-English mailbox. Five to
  eight days, not three.

Truth layer first. Bounce layer behind a half-day Graph spike on whether the
failed address can be read without opening a message body.

### One correction this section does not make

It does not rehabilitate the follow-up feature. Fourteen people switched it on,
at most eight reached the refusal, and **no real user has ever received one**.
That is still true and still unaddressed by anything above. What changed is
that it is no longer the best explanation for why paying customers left — it
was never tested on them, because they were gone first.

---

## 9. [R5] The first recovery in the file

Written 2026-09-01, the afternoon of the incident described in
`2026-09-01-helene-stop-and-formatting.md` and `2026-09-01-tim-layout.md`.

Everything above this section measures loss. Two Pro sales refunded or churned,
eight months of scheduled campaigns arriving as one block, 110 recipients never
sent to, 8% monthly retention. Today added the first thing in the other
direction.

One defect — the workers never converting plain text to HTML — reached two
paying customers within four hours of each other. Both went to the edge:

- **Helene**, five recipients into a 66-person send, wrote *"I will have to
  close the account to stop it"*, then asked us to delete her account, stop the
  campaign, and refund her. We did all three without asking her to justify any
  of them. Two hours later: *"Thank you for all the explanations and quick
  support. Really impressed with that!"* — and she asked to resume the campaign
  and for a month to test the follow-ups.
- **Tim**, fifteen recipients into a 108-person send, one day after paying,
  having already been refused a follow-up he had configured. He asked how to
  stop a campaign. He stayed.

Neither was retained by a feature. Both were retained by the same three things:
answering within minutes, admitting the fault without anatomy or excuse, and
refunding on request with no conditions attached.

### What this does and does not license

It licenses one strategic sentence: **the recoverable failure mode is defects,
and we can recover it.** §8 established that both Pro customers were lost to
defects rather than to price or packaging. Today is the first evidence that the
same class of failure does not have to end the same way.

It does not license making support the headline. Three reasons, and Ali raised
the idea himself so they are worth writing down rather than arguing:

1. **It was needed because we broke it.** Two customers required heroic support
   because every scheduled campaign had been wrong for months. Marketing the
   recovery celebrates the wrong half.
2. **It does not scale.** Twenty-minute responses are possible at sixty users.
   A promise made now becomes a promise broken at six hundred.
3. **"Great support" is the most claimed and least believed line in software.**
   Asserting it costs nothing and is therefore worth nothing.

### What is worth doing, because it is falsifiable

- **Measure first response time.** We have no such data: support arrives at
  support@ and through the in-app form, and neither is timed. A published
  median, computed and updated automatically, is a claim a queue-based
  competitor cannot match and cannot fake. Nothing can be said until it is
  measured.
- **Say the person who wrote the code answers.** True, checkable, and one
  sentence.
- **Make the changelog visible.** It already names bugs plainly — 0.3.2 says
  *"Large campaigns no longer stop short and report themselves finished"*.
  Publishing that costs something, which is exactly why it is credible.

The order matters: instrument, then claim. Reversing it is how the
claims-follow-product rule gets broken.

---

## Open questions for Ali

1. Are `bayar_ali@hotmail.com` and the three `freya_jowin*` accounts yours? If so
   the sender denominator is 22, not 26, and every ratio improves.
2. Who owns the 2026-04-21 follow-up — the only one ever created?
   ```sql
   SELECT f.id, f.created_at, f.status, u.email, u.plan
   FROM follow_ups f JOIN users u ON u.id = f.user_id;
   ```
3. Does anyone come back? Retention is the one thing this review never measured.
   ```sql
   SELECT u.email, u.plan, count(*) AS kampanya,
          min(c.created_at)::date AS ilk, max(c.created_at)::date AS son,
          sum(c.sent_count) AS toplam_gonderim
   FROM campaigns c JOIN users u ON u.id = c.user_id
   GROUP BY u.email, u.plan ORDER BY kampanya DESC;
   ```

---

## Sources

- Roadmap 423047 — verification log in `2026-08-24-microsoft-qa-answers.md`
- PostHog (EU project), queried 2026-08-31 via `backend/scripts/ask.py`
- `routers/campaigns.py:1412`, `:1470`; `routers/ai.py:75`; `sidebar.js:2316`,
  `:2677`, `:3009`, `:3398`, `:3678`; `sidebar.html:133`
- Commits `8e483bc` (gate, 03-29), `fcf69a8` (A/B + AI alerts, 04-16),
  `2dfae55` (PRO tags, 08-30)
- mailmeteor.com/products/microsoft-outlook, gmass.co/pricing — read 2026-08-31
- `2026-07-06-competitive-analysis-securemailmerge.md`
