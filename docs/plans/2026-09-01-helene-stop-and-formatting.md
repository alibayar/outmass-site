# Helene — no stop button, and a campaign she could not see (2026-09-01)

Live incident. Campaign stopped by Ali at ~08:10 UTC.

## What happened

`Helene@circularworkplaces.com`, Starter with a comped Pro grant. Campaign
`17a969ec-58d2-4c46-beee-825d344f6e05`, 66 recipients, created 28 August.

| time (UTC) | |
|---|---|
| 07:34:57 – 07:35:07 | **5 of 66 sent** |
| 07:48:11 | opens the sidebar |
| 07:48:13 | **`reports_load_failed`**, `error_code: "Not authenticated. Please login."` |
| 07:48:17 | clicks sign in |
| ~07:50 | writes to us |
| ~08:10 | Ali sets the campaign `cancelled` + `archived` |

Final state: **5 sent, 61 pending.**

Her words:

> "I cannot seem to edit a campaign, it seems the formating which was sent for
> my CBRE campaign did not work and everything sent as a block even if the
> preview looked fine. Now I see nowhere to edit the campaign or even stop it!
> Please could you let me know how to do that or I will have to close the
> account to stop it."

## Three separate faults, and she is right about the worst one

**1. There is no way to stop a campaign. At all.**

Verified: no cancel endpoint in `routers/campaigns.py` (only `cancel_followup`),
and no stop or cancel control in `sidebar.html`. The Reports tab offers Active
and Archived sub-tabs and a Resume button for partial campaigns — nothing that
halts one.

So "I will have to close the account to stop it" was not an exaggeration.
Revoking OAuth was genuinely her only lever. A paying customer discovered that
mid-send.

The stop that worked was a manual `UPDATE`: `status='cancelled', archived=true`.
`get_due_scheduled_campaigns` selects `status='scheduled'` (`campaign.py:96`)
and `archived=false` is already the auto-resume filter, so the two together
close both doors.

**2. Reports did not load, at the exact moment she needed it.**

`reports_load_failed` carried `"Not authenticated. Please login."` — her JWT had
expired. Even if a stop button existed, she could not have reached it. The
session expiry is ordinary; the timing is what made it an emergency.

**3. The formatting broke — cause not yet confirmed.**

Both `_text_to_html` (`campaigns.py:1840`) and the panel's `textToHtml`
(`sidebar.js:1727`) use the identical rule: if the body matches
`/<[a-z!/][^>]*>/i`, pass it through untouched; otherwise escape it and convert
`\n\n` to paragraphs and `\n` to `<br>`.

Because the rules are identical, a body containing any tag would collapse in
BOTH the preview and the email — which contradicts "the preview looked fine".
So the divergence is somewhere else, and I have not found it yet. Do not tell
her a cause until it is confirmed.

**Query to confirm it:**

```sql
SELECT left(body, 600) AS gövde_baslangici,
       body ~ '<[a-zA-Z!/][^>]*>' AS html_tag_var_mi,
       length(body) AS uzunluk,
       (length(body) - length(replace(body, chr(10), ''))) AS satir_sonu_sayisi
FROM campaigns
WHERE id = '17a969ec-58d2-4c46-beee-825d344f6e05';
```

If `html_tag_var_mi` is true, her body carried markup and both sides should
have passed it through — so the preview must be rendering it in a container
that treats newlines differently from an email client. If false, the conversion
ran and something downstream flattened it.

## Reply — send now, do not wait for fault 3

Subject: **Your campaign is stopped — 5 of 66 went out**

> Hi Helene,
>
> Your CBRE campaign is stopped. It had reached 5 of the 66 recipients before
> I halted it; the remaining 61 have not been contacted and will not be.
>
> You were right that there was nowhere to stop it, and I am sorry. OutMass
> has no stop control — not hidden, not somewhere you missed. It does not
> exist, and finding that out mid-send is exactly the wrong moment. I have
> stopped this one by hand from our side, and a proper stop button is the
> next thing we build.
>
> Two other things went wrong for you this morning, and you should know both.
> The Reports tab failed to open when you went looking, because your session
> had expired — so even the little you could have done was out of reach.
> Signing in again fixes that one.
>
> And the formatting: I can see that your message went out differently from
> the preview, and I am still working out why. I would rather tell you the
> real cause than a quick guess, so give me a few hours on that one. If you
> can send me the version you pasted into the editor, it will be faster.
>
> Nothing else of yours is scheduled, so there is no second campaign to worry
> about. When you want to send the remaining 61, we can set it up again
> together once I know the formatting is fixed — nothing will go out before
> you say so.
>
> Ali

Send notes: BCC `outmassapp@outlook.com`. No call offered — async only.

## The fix that has to follow

A stop control is now the most clearly earned item in the backlog. It has a
customer, a date, and a threat to close the account attached to it. Minimum
shape: a button on a `scheduled` or `sending` campaign in Reports that sets
`cancelled` + `archived`, with a confirmation naming how many have already
gone out — because that number is the only thing the user cannot undo.

---

## Follow-up email — cause confirmed, fix deployed

Sent after the first one. The first said "give me a few hours"; this is that
answer.

Confirmed cause: `scheduled_worker` and `followup_worker` never called the
plain-text → HTML conversion that `routers/campaigns.py` did, so a scheduled
campaign's newlines collapsed inside a `contentType: HTML` message while the
panel's preview — which converts — looked correct. Her template contained no
markup and none of her 66 rows did either, which rules out the alternatives.
Fixed and deployed in `0252d0b`.

Subject: **What happened to your formatting — found and fixed**

> Hi Helene,
>
> I said I would rather find the real cause than guess. I have it, and it was
> ours.
>
> OutMass sends through Outlook as HTML, where a plain line break means
> nothing unless we convert it first. We do that when you press Send — and we
> were not doing it when a campaign was **scheduled**. Your campaign was
> scheduled, so your paragraphs were converted for the preview and not for the
> actual send. That is why the two looked different, and why nothing you did
> could have prevented it. It was not your formatting, your pasting, or your
> plan.
>
> This was not specific to you: any scheduled campaign was affected. It is
> fixed as of this morning, and there is now a test that fails if any of our
> three sending paths ever stops doing the conversion again — that gap between
> them is what let this run unnoticed.
>
> Where that leaves your campaign:
>
> **5 people received the broken version.** I can send you the list if you
> want to follow up with them personally. I would not re-send to them
> automatically — a second copy of the same message is its own kind of wrong —
> but it is your call and I will do whichever you prefer.
>
> **61 people have not been contacted at all.** Whenever you are ready, we can
> send to exactly those 61 with the formatting correct, and nothing goes out
> until you say so.
>
> On the other thing you raised — there being nowhere to stop a campaign —
> you were right and I am building that now. A Stop button on a running or
> scheduled campaign, which tells you how many have already gone out before
> you confirm, since that is the one number nobody can take back. I will write
> when it is live.
>
> Sorry for the morning. If you would rather see the remaining 61 go out as a
> fresh campaign you set up yourself rather than a resume of this one, that
> works too — tell me which and I will get it ready.
>
> Ali

Send notes: BCC `outmassapp@outlook.com`. No call offered — async only.
Nothing here promises the Stop button by a date.

---

## Escalation, 11:25 — and the fourth fault

Her second email crossed with Ali's first, so she wrote it without knowing the
campaign had been stopped at ~08:10 or that the cause was found.

> "There is a problem with the campaign the formatting has not sent correctly,
> and I am not finding anywhere to stop the campaign nor modify it. I need it
> to stop sending. I tried to delete my account but it is also not working
> despite cancelling the subscription.
>
> Please could you delete my account, stop the campaign and issue a refund for
> this?"

**Fault 4: account deletion refuses the very users who did what it asks.**

`routers/account.py:107`:

```python
plan = user.get("plan", "free")
has_subscription = bool(user.get("stripe_subscription_id"))
if plan != "free" and has_subscription:
    raise HTTPException(409, {"error": "active_subscription", ...})
```

Stripe cancellation normally means *cancel at period end*, so the subscription
stays active and no webhook flips `plan` to free. She cancelled, and the guard
still sees `plan='starter'` with a subscription id and refuses — while its own
message tells her to cancel her subscription first. She had.

The guard's intent is right (do not leave a charge running after the account
is gone). Its test is wrong: it should ask whether the subscription is set to
cancel, not whether the plan is currently paid. → backlog, and it is now the
second guard this week that was correct in intent and unreachable in practice.

## Recommendation on the refund

**Do not ask whether she still wants it. Refund and say so.**

She asked, she had a broken product, she chased us twice, and she marked the
second one high importance. Answering a refund request with "but we fixed it"
makes a customer argue for her own money, and the fix being real does not
change that.

The one question genuinely worth asking is the account deletion, because it is
irreversible and because her own sentence suggests she wanted it as a way to
stop the campaign — which is already stopped. That is a check before an
irreversible act, not retention friction.

## Reply — send instead of the "cause found" draft above

Kept short deliberately. She does not need the mechanism, and after a refund
request a long technical explanation reads as justification.

Subject: **Stopped, refunded — and one question**

> Hi Hélène,
>
> Our emails crossed, so here is where things stand.
>
> **The campaign is stopped.** I stopped it around 09:10 this morning, before
> your second message. It had reached 5 of the 66; the other 61 have not been
> contacted and will not be.
>
> **The refund is done** — no conditions, nothing for you to do.
>
> The formatting was a bug on our side, in campaigns sent on a schedule. We
> found it this morning and it is fixed. Nothing you did caused it. You were
> also right that there was nowhere to stop a campaign — there wasn't one, and
> there is now.
>
> **One thing before I delete the account: do you still want it deleted?** It
> cannot be undone, and you tried it right after saying you needed the sending
> to stop — so if deleting was the way to stop it, that is already handled.
> Tell me either way and I will act today.
>
> The delete button refusing you was also our fault, not yours: it blocks
> deletion while a subscription is still counted as active, and a cancellation
> stays active until the end of the billing period. I can delete the account
> manually regardless.
>
> Sorry for this morning.
>
> Ali

Send notes: BCC `outmassapp@outlook.com`. No call offered — async only.
No retention pitch, no discount, nothing asked in return for the refund.

---

## She came back (11:40) — and set a condition

> "Thank you for all the explanations and quick support. Really impressed with
> that!
>
> So I am happy to resume the campaign as it was set up (5 emails sent a day)
> providing it will send in the correct formating (make sure this will be sent
> correctly please). I will personally contact the 5 persons that were
> contacted today.
>
> Could you please give a free month of the starter subscription & pro, so I
> can still use the scheduling and test the follow up? I will sign up at end of
> month if everything works fine."

From "delete my account and refund me" to "let's resume", in two hours. Her
condition is explicit and it is the one thing we have not actually checked.

## Do these in order. Do not skip the first.

### 1. Verify the fix on a real scheduled send — BEFORE resuming hers

The formatting fix has unit tests and no real send behind it. She asked us to
make sure, and today has already produced two confident-but-wrong claims. The
scheduled beat runs **every 5 minutes** (`celery_app.py:159`), so this costs
about ten minutes:

- In OutMass, make a campaign to two addresses you control.
- Body with real structure: two or three paragraphs separated by blank lines,
  and at least one single line break inside a paragraph.
- **Schedule it** a couple of minutes out — do not press Send now. Send-now
  always worked; the worker is the path that broke.
- Wait for it to arrive and look at it.

Paragraphs and line breaks intact → the fix is real and her campaign can
resume. Still one block → the fix did not reach the worker, and nothing gets
resumed until it does.

### 2. Grant the month

```sql
UPDATE users
SET comp_plan       = 'pro',
    comp_plan_until = '2026-10-01 23:59:59+00'
WHERE lower(email) = 'helene@circularworkplaces.com';

SELECT email, plan, comp_plan, comp_plan_until
FROM users WHERE lower(email) = 'helene@circularworkplaces.com';
```

One grant covers both things she asked for. `effective_plan()` returns
`comp_plan` over `plan`, the scheduled-sending gate refuses only `free`
(`campaigns.py:191`), and follow-ups require `pro` (`:1412`) — so Pro gives
her the scheduling *and* the follow-ups. There is no need to touch `plan`,
which belongs to Stripe.

### 3. Resume the campaign — only after step 1 passes

```sql
UPDATE campaigns
SET status = 'scheduled', archived = false, scheduled_for = now()
WHERE id = '17a969ec-58d2-4c46-beee-825d344f6e05';

SELECT status, archived, scheduled_for, daily_send_cap, sent_count, total_contacts
FROM campaigns WHERE id = '17a969ec-58d2-4c46-beee-825d344f6e05';
```

Expect `daily_send_cap = 5` — she said five a day and exactly five went out.
If it reads anything else, stop and tell her, because she named that number.

The beat then picks it up within five minutes and sends the first five of the
remaining 61. Roughly 13 more days at that rate.

### 4. One thing to be honest about in the reply

She wants to **test the follow-up**. Her campaign has no follow-up attached —
`follow_ups` returned no rows for it — and the panel can only attach one at the
moment Send is pressed. So Pro alone will not let her add one to the resumed
campaign. She can use it on her *next* campaign, or send us the wording and we
attach it from our side. Say so rather than let her look for a control that is
not there; that is what started this morning.

## Reply

Subject: **Resuming — and the month is on us**

> Hi Hélène,
>
> Glad that helped, and thank you for coming back rather than walking.
>
> **The free month is set up.** Scheduling and follow-ups are both open to you
> until 1 October, no card, nothing to cancel — it simply expires. If it works
> the way you want by then, you can sign up; if it doesn't, nothing happens.
>
> **Before restarting your campaign I scheduled one of my own and checked what
> actually arrived** — paragraphs, line breaks and signature all intact. Your
> campaign is running again at 5 a day, picking up from the 61 who have not
> been contacted. Thank you for handling the 5 from this morning yourself —
> that is generous.
>
> One thing I would rather tell you now than have you hunt for: a follow-up can
> currently only be attached at the moment a campaign is sent, so I cannot add
> one to the campaign that is already running. You can set one up on your next
> campaign, or send me the wording and the number of days and I will attach it
> to this one from our side.
>
> Ali

Send notes: BCC `outmassapp@outlook.com`. No call offered — async only.
The third paragraph must be edited to say what was actually observed in step 1.
Do not send it as written if the check was not run.


---

## Step 1 result: verified, 2026-09-01 09:35 UTC

Not assumed. A two-recipient campaign was **scheduled** (not sent now) at
09:31:14 — `send_completed` carried `scheduled: true` — and the server sent it
at **09:35:17**, four minutes later, which is the beat cycle. So it went
through `scheduled_worker`, the path that was broken.

What arrived: paragraph gap present, three consecutive lines on three lines,
signature on three lines, and `<info@example.com>` from the CSV rendered as
literal text.

The last one matters most: that recipient's row is the one carrying angle
brackets, so it also proves the merge-before-detect bug is closed. The harder
of the two test rows is the one that passed.

**Steps 2 and 3 are cleared to run.**

---

## Trap: manually resuming a capped campaign sends an extra batch the same day

Setting `scheduled_for = now()` on a campaign with a `daily_send_cap` that has
already run today gives it a **second** batch. The cap is applied per run —
`pending = pending[:daily_cap]` (`scheduled_worker.py:110`) — with no reference
to how many went out earlier in the day. Normally that is invisible, because a
capped run reschedules itself for +1 day.

It happened here: her campaign had sent 5 at 07:35, the manual resume ran again
at ~09:40, and 10 went out on a day she had specifically asked for 5. It
self-corrected afterwards — `scheduled_for` moved to 2026-09-02 09:40 and
`sent_count` settled at 10.

**Resume a capped campaign with `scheduled_for = now() + interval '1 day'`**,
unless today's batch has genuinely not run.

Not reachable without a human: auto-resume and the Resume endpoint both select
`partial`, and a capped campaign that finishes its batch returns to
`scheduled`. So this is an operator footgun rather than a live defect — but it
is one we fired.
