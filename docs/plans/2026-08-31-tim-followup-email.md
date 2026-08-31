# Tim Haverkamp — the follow-up he paid for and did not get (2026-08-31)

Draft held for Ali's decision on the comp. Not sent.

## What happened, from telemetry and the DB

`TimHaverkamp@improve4all.nl` — signed up 2026-08-28, sent one campaign of 1.
Came back today on 0.3.0.

| Istanbul | event |
|---|---|
| 17:56 | opened the panel, hit the re-auth banner, signed in |
| 17:59 | switched scheduled sending on |
| 18:01 | uploaded 108 recipients |
| 18:02, 18:03 | two test sends, both succeeded |
| 18:07:16 | pressed Send |
| 18:07:27 | **refused** — `feature_locked_scheduled_sending` (Starter feature) |
| 18:07:32 | the wall offered Starter; he clicked it |
| **18:09:35** | **paid $9** — 2 min 3 s from wall to payment |
| 18:09:45 | switched follow-ups on |
| 18:12:27 | scheduled the campaign, 108 recipients |
| 18:12:33 | **refused** — `feature_locked_followup` (Pro feature) |
| 18:13:07 | clicked *manage subscription* |

Stripe: $9.00 USD succeeded, Visa ...3166, subscription creation, no refund.

Campaign `c813f366-d407-45c6-95cc-8a2a93016f16`, "Even een vraag over
{{name}} — 31 aug 2026": status `scheduled`, **2026-09-01 08:00 UTC (11:00
Istanbul)**, 108 contacts, `daily_send_cap` 15 → roughly 1–8 September.
Merge tags passed `_raise_if_bad_merge_tags`, so `{{name}}` matches a real
column. **Nothing is broken.** The only thing missing is the follow-up.

## Two firsts, both worth recording

1. **A feature wall converted, for the first time in the product's history.**
   `upgrade_button_clicked` carried `context=quota_modal`, `plan=starter`.
   The morning's strategy note said the paywall had never sold. It sells —
   when it offers the plan that unlocks what was clicked.
2. **`feature_locked_followup` fired for the first time.** The 2026-08-28
   fix — which replaced a silent 402 with a visible alert — found its first
   real customer today. He was told. He just was not told what to do next,
   which is what the unshipped 2026-08-31 fix adds.

## The catch that decides the options

**A follow-up can only be attached at the moment Send is pressed.**
`maybeCreateFollowup()` runs from the two send paths and nowhere else; the
reports view's `followup-status` only *displays* pending follow-ups. So
`c813f366` cannot have one added through the panel, with or without Pro.

That is a product gap in its own right: hit the wall once and that campaign
has no second chance. → backlog.

Options, therefore:

- **(a)** comp Pro, ask him to cancel and re-create the campaign — costs a
  new customer ten minutes of rework half an hour after paying
- **(b)** comp Pro, and create the follow-up for him server-side once he
  sends us the wording — one email round trip, and the campaign paces over
  eight days so a day's delay costs nothing
- **(c)** tell him plainly, offer nothing

Recommended: **(b)**.

## FINAL — approved, one month of Pro. Written 2026-09-01 00:55 Istanbul.

```sql
UPDATE users
SET comp_plan       = 'pro',
    comp_plan_until = '2026-10-01 23:59:59+00'
WHERE lower(email) = 'timhaverkamp@improve4all.nl';

-- Verify by reading it back, not by trusting the UPDATE's row count.
SELECT email, plan, comp_plan, comp_plan_until
FROM users
WHERE lower(email) = 'timhaverkamp@improve4all.nl';
```

Expect `starter` / `pro` / `2026-10-01`. `effective_plan()` merges `comp_plan`
over `plan` while `comp_plan_until` is in the future, so nothing needs undoing.

**Run the SQL before the email goes out** — it says the account is already on
Pro, and that has to be true when he reads it.

### When to send

His campaign starts **2026-09-01 08:00 UTC**, which is 11:00 Istanbul and
**10:00 his time** (Netherlands, CEST).

Send at **08:00 CEST = 09:00 Istanbul.** Start of his working day, two hours
before the campaign begins, and the message is about something that has not
happened yet rather than something he has to undo.

Not razor-critical if he reads it late: the campaign paces 15 a day over
roughly eight days, and a follow-up fires N days after each *individual*
recipient receives the first mail — so attaching one a day or two in still
catches nearly everyone. Earlier is simply cleaner.

Subject: **About the follow-up on your campaign**

> Hi Tim,
>
> Thanks for subscribing yesterday. I went through the new subscriptions and
> looked at your account: your campaign to 108 recipients starts in a couple
> of hours, 15 a day, and it looks healthy.
>
> One thing I want to flag before it begins, rather than let you find out the
> slow way. **The automatic follow-up you switched on is not attached to it.**
> Follow-ups are on our Pro plan; Starter — which is what you bought, and the
> right plan for the scheduled sending you were after — does not include them.
> You did get a message at the time, but it only told you the rule and not
> what to do about it. That is our fault, not yours, and we are fixing the
> message this week.
>
> There is a second thing I would rather admit than have you trip over: a
> follow-up can currently only be attached at the moment you press Send. So
> this campaign cannot have one added from the panel now, on any plan. That
> is a gap in the product, and it is being fixed too.
>
> So, two things from my side.
>
> **I have put your account on Pro until 1 October at no charge.** You keep
> the $9 Starter subscription you signed up for and nothing else changes; the
> Pro access simply expires on its own. Follow-ups, A/B subject testing and
> the AI writer are all yours in the meantime.
>
> **And for this campaign specifically** — if you reply with the subject line
> and text you want the follow-up to use, and how many days after each person
> receives the first email it should go out, I will attach it from our side.
> There is no rush: the follow-up is counted per recipient, from the day each
> of them gets your first email, so it still works even once the campaign is
> under way.
>
> If you would rather not wait for me, the other route is to cancel the
> scheduled campaign and set it up again with the follow-up switched on —
> that now works, since your account is on Pro.
>
> Either way, just tell me which you prefer.
>
> Ali

Send notes: BCC `outmassapp@outlook.com`. No call offered — async only.

---

## Superseded — first final, written before midnight

Subject: **About the follow-up on your campaign**

> Hi Tim,
>
> Thanks for subscribing today. I went through the new subscriptions this
> evening and looked at your account: your campaign to 108 recipients is
> scheduled for tomorrow morning at 15 a day, and it looks healthy.
>
> One thing I want to flag before it starts, rather than let you find out
> the slow way. **The automatic follow-up you switched on is not attached to
> it.** Follow-ups are on our Pro plan; Starter — which is what you bought,
> and the right plan for the scheduled sending you were after — does not
> include them. You did get a message at the time, but it only told you the
> rule and not what to do about it. That is our fault, not yours, and we are
> fixing the message this week.
>
> There is a second thing I would rather admit than have you trip over:
> a follow-up can currently only be attached at the moment you press Send.
> So this campaign cannot have one added from the panel now, on any plan.
> That is a gap in the product; it is being fixed too.
>
> So, two things from my side.
>
> **I have put your account on Pro for the next month at no charge.** You
> keep the $9 Starter subscription you signed up for and nothing else
> changes; the Pro access simply expires at the end of September on its own.
> Follow-ups, A/B subject testing and the AI writer are all available to you
> in the meantime.
>
> **And for this campaign specifically** — if you reply with the subject
> line and text you want the follow-up to use, and how many days after each
> person receives the first email it should go out, I will attach it from
> our side before the campaign gets that far. Your campaign paces over about
> eight days, so there is plenty of room; a day either way costs nothing.
>
> If you would rather not wait for me, the other route is to cancel the
> scheduled campaign and set it up again with the follow-up switched on. It
> has not sent anything yet, so nothing is lost but a few minutes.
>
> Either way, just tell me which you prefer.
>
> Ali

Send notes: BCC `outmassapp@outlook.com`. No call offered — async only.
Campaign starts 11:00 Istanbul on 1 September; send tonight.

---

## Superseded first draft (kept for the record)

Subject: **About the follow-up on your campaign**

> Hi Tim,
>
> Thanks for subscribing today. I was going through new subscriptions and
> looked at your account — your campaign to 108 recipients is scheduled for
> tomorrow morning, 15 a day, and it looks healthy.
>
> One thing I want to flag before it starts, because you would otherwise
> find out the slow way: the automatic follow-up you switched on is not
> attached to it. Follow-ups are on our Pro plan, and Starter — which is
> what you bought, and the right plan for the scheduled sending you were
> after — does not include them. You saw the message at the time, but it
> did not tell you what to do about it, and that is our fault rather than
> yours.
>
> There is a second problem I would rather admit than have you discover:
> a follow-up can only be attached at the moment you press Send. So even
> on Pro, this campaign cannot have one added now from the panel. That is a
> gap in the product and it is on our list.
>
> [COMP PARAGRAPH — include only if Ali approves]
> So here is what I would like to do. I have put your account on Pro for
> the next month at no charge — you keep paying the $9 Starter you signed
> up for, nothing else changes, and it reverts on its own. If you send me
> the subject line and text you want the follow-up to use, and how many days
> after each person receives the first email it should go out, I will attach
> it to this campaign from our side before it gets that far. Everything you
> send from then on can have follow-ups set up normally in the panel.
> [END COMP PARAGRAPH]
>
> If you would rather not wait, the other route is to cancel the scheduled
> campaign and set it up again with the follow-up switched on — it has not
> sent anything yet, so nothing is lost but the few minutes.
>
> Either way, tell me which you prefer and I will take care of it.
>
> Ali

Send notes: BCC `outmassapp@outlook.com`. No call offered — async only.
The campaign starts 11:00 Istanbul on 1 September, so this wants sending
tonight to be useful.

## Claims check

- "your campaign is scheduled for tomorrow morning, 15 a day" — from the
  campaign row, verified.
- "Starter does not include follow-ups" — `campaigns.py:1412` requires
  `effective_plan == 'pro'`, verified.
- "a follow-up can only be attached at the moment you press Send" —
  `maybeCreateFollowup` call sites `sidebar.js:2383`, `:2541`, verified.
- "it reverts on its own" — `comp_plan_until` is evaluated by
  `effective_plan()`; no beat task, nothing to undo. Verified 2026-08-30.
- Nothing claims multi-stage sequences, which we do not have.
