# Tim — the layout broke on his first scheduled window (2026-09-01)

`TimHaverkamp@improve4all.nl`, Starter with a comped Pro grant, paid 31 August.
Campaign `c813f366-d407-45c6-95cc-8a2a93016f16`, 108 recipients, 15 a day.

He wrote at 11:26, replying to a different email of ours:

> "I sent the first 15 emails this morning via Outmass, but the layout came out
> completely wrong. The layout was correct in the first two test emails. How is
> this possible? I'd like to prevent the rest of the emails from being sent
> because the layout is incorrect. How do I stop a campaign?"

## Facts behind the reply

- His 15 went out at **08:05:27 UTC**. The fix (`0252d0b`) deployed after that.
  Backend is on `0280451` now, verified against `/`.
- So the **remaining 93 go out tomorrow at 08:00 UTC and will be correct**. He
  does not need to stop — but it is his call, and the offer has to be
  unconditional.
- His two test sends were correct because test sends took the path that
  converted; the scheduled send took the one that did not. He described that
  split without being able to know it — second independent confirmation the
  same morning, after Helene's.
- The cap held exactly: 15 of 108, campaign back to `scheduled`. The close-out
  change from `01e18bb` behaved.

## Reply

Subject: **Layout problem — found and fixed this morning**

> Hi Tim,
>
> Thanks for flagging it, and sorry. This was a bug on our side: campaigns
> sent on a schedule lost their line breaks, while test emails kept them —
> which is why your two tests looked right. We found it this morning and it
> is fixed.
>
> The 15 that went out earlier had the wrong layout and I cannot undo those.
> **The remaining 93 go out tomorrow morning as planned, and will look
> correct.** So there is no need to stop the campaign — though if you would
> rather stop it anyway, just say so and I will do it within minutes.
>
> On how to stop one: you could not — there was no button. There is one now,
> on the campaign report, and it reaches you with the next update.
>
> If you would like the 15 addresses so you can follow up with them yourself,
> just ask.
>
> Your follow-up from yesterday is still waiting on your wording whenever you
> want it — no rush.
>
> Ali

Send notes: BCC `outmassapp@outlook.com`. No call offered — async only.

The draft first said "you are the second person to ask today". Ali did not
want another customer's experience mentioned, and suggested saying we had
caught it in our own testing instead. We had not — Helene reported it at
07:50 and that is how we learned of it — so the clause was simply dropped.
"We found it this morning" stays: it says when, and claims nothing about how.
No compensation offered: he already has a month of Pro, and stacking another
gesture reads as buying him off rather than fixing it.

## The one claim that has to stay true

**Verified ahead of time, 2026-09-01 09:35 UTC.** A two-recipient campaign was
scheduled rather than sent now (`send_completed` carried `scheduled: true` at
09:31:14) and the server sent it at 09:35:17 — through `scheduled_worker`, the
path that was broken. Paragraphs, line breaks and signature all arrived intact,
so the claim in this email rests on a real send rather than only on tests.

Still worth confirming after 08:00 UTC tomorrow by
looking at what a recipient actually received — not at `emails_sent`, which
only counts. If it is wrong again, the fix did not reach the worker and this
needs re-opening before the third batch.
