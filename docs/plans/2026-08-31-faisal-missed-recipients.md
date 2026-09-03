# Faisal — 109 recipients never sent, and why we are not sending them (2026-08-31)

Draft held for Ali. Not sent.

## The verified numbers

Blast-radius query across the whole `campaigns` table: **two rows, both his.**
No other campaign in the product reads as `sent` while holding sendable
recipients.

| campaign | created | contacts | delivered | never attempted | permanently failed |
|---|---|---|---|---|---|
| `91e7ce08` SYC Wave Batch 2 | 2026-06-30 | 1020 | 1000 | **20** | 0 |
| `49587d65` syc2 wave 1 | 2026-07-20 | 1210 | 999 | **91** | 120 |

**CORRECTED 2026-09-03, before sending.** Each campaign has exactly **one**
address on his suppression list — correctly held, not a miss. The 08-31 pass
caught the one inside the 91 and missed the one inside the 20, so the figure
below said 110. It is **109**: nineteen on Batch 2, ninety on wave 1. Plus 120
attempted and rejected, which are a different thing and may or may not be our
fault.

Suppression lives in its own `suppression_list` table, not in
`contacts.status` — a count of `status = suppressed` returns zero for both
campaigns and reads as though nobody was held. The daily alarm reports the raw
111 for the same reason. Three numbers for one fact, and the only one fit for
a customer email is the one that joins the table.

`91e7ce08` last delivered 2026-06-30 17:49, 43 minutes after it was created —
one uninterrupted pass, exactly 1000 rows. `49587d65` last delivered
2026-07-28 06:04, minutes after its `scheduled_for` of 06:00.

**Quota was not charged for any of them.** `increment_sent_count` is driven by
`sent_count`, which only advances on a delivered message
(`campaigns.py:1010`, `:1062`). Verified before writing it to a customer.

## The cause

`get_resumable_contacts` (`models/contact.py:218`) reads the recipient list
with no explicit bound, so PostgREST's server-side max-rows truncates it
silently. The close-out then decides from that already-truncated in-memory
list — `campaigns.py:1106` writes `"sent" if not errors and not quota_capped`
and never asks the database again. `sent` is terminal: no recovery path
selects it, and nothing compares `sent_count` to `total_contacts`.

Daily-capped campaigns are immune by accident: `scheduled_worker.py:284`
re-reads the database, but only inside `if daily_cap > 0`, and `continue`s
past the status write. Both of Faisal's campaigns have `daily_send_cap` NULL.

Free users are protected by their quota (250 < the cap). The exposed
population is paying customers with uncapped lists over the cap — which today
is Faisal alone.

## Why we are NOT sending the 110

Both campaigns advertise a programme that ran **1–7 August 2026**. Delivering
a stale invitation to a finished event, three weeks late, from his own
mailbox, is worse for him than those 110 people never hearing from him. This
is the one place where fixing the bug is the wrong move.

The 120 `failed` stay as they are. `_classify_failure` collapses a mailbox
refusal and a dead address into the same permanent bucket and nothing records
which it was, so a blind reset would re-attempt genuinely bad addresses and
risk his sender reputation.

## Order of operations

1. **Archive both campaigns first.** `archived = false` is already a filter in
   `get_resumable_partial_campaigns`, so archiving is the existing stop switch
   and needs no new code. Archive *before* any status change, or a beat can
   pick them up in the window between.
2. Only then correct statuses, if we correct them at all.
3. Send the email below.

## Draft

Subject: **Two of your campaigns came up short — what happened**

> Hi Faisal,
>
> I owe you a straight account of something we found today while going
> through our own data.
>
> On two of your campaigns — SYC Wave Batch 2 from 30 June, and syc2 wave 1
> from 20 July — a bug on our side meant **109 recipients were never sent
> to at all.** Nineteen on the first, ninety on the second. The campaigns
> reported themselves as finished, which is why neither you nor we noticed
> at the time. That was our fault. The cause is fixed and live now — a
> campaign can no longer report itself finished while it is still holding
> people it has not written to.
>
> Two things you should know about it:
>
> Your monthly quota was never charged for them — we only count an email
> once it has actually gone out, so nothing was taken from your allowance
> for messages that were never sent.
>
> And **we are deliberately not sending them now.** Both campaigns invite
> people to a programme that ran 1–7 August. Delivering that invitation
> three weeks after the event, from your address, would do more harm to you
> than the silence has. If you still want those people reached, the right
> way is a fresh campaign with current copy, and I am happy to help you set
> it up.
>
> One more thing from the same campaign, which is separate and probably not
> our bug: 120 addresses on syc2 wave 1 were attempted and refused by the
> receiving mail servers. Our records do not distinguish a bad address from
> a temporary refusal, so I cannot tell you which those were — but if that
> list came from an older source, it is worth a clean before the next send.
>
> Sorry for the trouble. If you would rather I walked the numbers through in
> writing in more detail, just say so.
>
> Ali

Send notes: BCC `outmassapp@outlook.com`. No call offered — async only.
Nothing here offers to resend, and nothing presents the 120 as recoverable.

## Freshness check — 2026-09-01

The draft was written on 08-31 and said the cause was "being fixed this week".
It shipped that same day (`01e18bb`, live on `api.getoutmass.com`), so the
sentence was already false by the time anyone read it. Corrected above to the
present tense.

Worth re-reading before sending anything that has sat for a day: a promise
about future work reads very differently from a statement that it is done, and
the difference is the whole reason he might reply.

## One thing for Ali to weigh

He has not opened the product since 2026-08-10. This email can go either way:
it is an honest admission that may rebuild trust, or a reminder of a bad
experience that closes the account. It is still the right thing to send —
he paid for 5,486 recipients and 109 of them silently did not happen — but
go in knowing it is not a neutral message.
