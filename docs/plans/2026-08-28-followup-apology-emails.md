# Follow-up silent failure — the five emails

**Send from** support@getoutmass.com, **BCC** outmassapp@outlook.com.

**Before sending:** grant each account one month of Pro (`manual_promo_until`).
The wording says "is on Pro", not "will be" — it only reads correctly if the
grant lands first, and that is deliberate.

**Dates checked 2026-08-30.** These were drafted on the 28th, and every
"today" in them had gone stale by the time they were read two days later.
The relative dates are gone now; only fixed ones remain. If they are still
unsent a week from now, re-read them anyway — an apology that misdates
itself is a second small error sitting on top of the first.

**When:** drafted on a Sunday. Our own rhythm data puts 85% of user activity
in Mon–Thu, so a Monday morning send gets read and acted on where a Sunday
one gets skimmed and buried. Helene's is the only one with any urgency, and
two days have already passed on it.

## What happened, for the record

`/campaigns/{id}/followups` is Pro-only and answers 402. The panel handled that
answer with a debug log that is off by default, so the checkbox stayed ticked,
the subject and body the user had written stayed on screen, the campaign went
out, and nothing said the follow-up had not been created.

Our pricing page and store listing both say follow-ups are Pro. So this was
never mis-selling — it was the product staying silent about a limit we had
published honestly everywhere else. Nobody reads the pricing page in the middle
of building a campaign; they read the panel.

Fixed in 0.2.3: the alert fires, the checkbox unticks itself, both Pro-only
toggles carry a PRO badge, and the refusal is now visible in telemetry.

## Who, and the send that followed

Each of these enabled the toggle and then sent. The campaign named is the one
that went out immediately afterwards — the clearest case. Later sends may have
carried the same ticked box; we cannot tell from the events, so the emails do
not claim a number.

| Person | Enabled | Sent right after |
|---|---|---|
| lucia@skylineprp.com | 16 Jul 17:12 | 110 recipients, 9 min later |
| tony@skylineprp.com | 20 Jul 17:37 | 60 recipients, 6 min later |
| marketing@bellmed.com | 14 Jul 20:26 | 1,822 on 17 Jul |
| faisal@samaed.com | 25 Jun 16:48 | 485 recipients, 20 min later |
| Helene@circularworkplaces.com | 28 Aug 11:58 | 66 recipients — SCHEDULED for 1 Sep, 5/day; none sent yet |

lucia and tony are both at skylineprp.com and pay separately. They will compare
notes, so the two emails must say the same thing — they do, apart from the
campaign detail.

---

## lucia@skylineprp.com

**Subject:** Your follow-ups never went out — that was our fault

Hi Lucia,

I found a bug in OutMass and you are one of the people it affected, so I want
to tell you before you find it yourself.

When you turned on "Auto follow-up for non-openers" on 16 July and sent your
110-recipient campaign nine minutes later, the follow-up was never created.
Automatic follow-ups are a Pro feature and you are on Starter — but the panel
never said so. It let you tick the box, write the follow-up, and press Send,
and then said nothing at all when our server declined to schedule it.

The limit was correct. Staying quiet about it was not, and that part is
entirely on us.

Two things I have done:

Your account is on **Pro for the next month, at no charge** — nothing to do
at your end. Your follow-ups will now actually be created, along
with A/B subject testing and the AI writer. If it is useful, keep it; if not,
you drop back to Starter automatically and nothing changes.

And the next release makes the panel say it out loud: the Pro-only controls are
labelled, and if a follow-up is ever refused you get told at that moment rather
than never.

If you would like me to set up a follow-up on a recent campaign so it goes out
properly, reply and I will do it.

Sorry about this.

Ali
OutMass

---

## tony@skylineprp.com

**Subject:** Your follow-ups never went out — that was our fault

Hi Tony,

I found a bug in OutMass and you are one of the people it affected, so I want
to tell you before you find it yourself.

When you turned on "Auto follow-up for non-openers" on 20 July and sent your
60-recipient campaign six minutes later, the follow-up was never created.
Automatic follow-ups are a Pro feature and you are on Starter — but the panel
never said so. It let you tick the box, write the follow-up, and press Send,
and then said nothing at all when our server declined to schedule it.

The limit was correct. Staying quiet about it was not, and that part is
entirely on us.

Two things I have done:

Your account is on **Pro for the next month, at no charge** — nothing to do
at your end. Your follow-ups will now actually be created, along
with A/B subject testing and the AI writer. If it is useful, keep it; if not,
you drop back to Starter automatically and nothing changes.

And the next release makes the panel say it out loud: the Pro-only controls are
labelled, and if a follow-up is ever refused you get told at that moment rather
than never.

If you would like me to set up a follow-up on a recent campaign so it goes out
properly, reply and I will do it.

Sorry about this.

Ali
OutMass

---

## marketing@bellmed.com

**Subject:** Your follow-ups never went out — that was our fault

Hello,

I found a bug in OutMass and your account is one of the ones it affected, so I
want to tell you before you find it yourself.

You turned on "Auto follow-up for non-openers" on 14 July, and the campaigns
you sent after that — including the 1,822-recipient send on 17 July — went out
without the follow-up ever being created. Automatic follow-ups are a Pro
feature and you are on Starter, but the panel never said so. It let you tick
the box, write the follow-up, and press Send, and then said nothing when our
server declined to schedule it.

The limit was correct. Staying quiet about it was not, and that part is
entirely on us.

Two things I have done:

Your account is on **Pro for the next month, at no charge** — nothing to do
at your end. Follow-ups will now actually be created, along with
A/B subject testing and the AI writer. If it is useful, keep it; if not, you
drop back to Starter automatically and nothing changes.

And the next release makes the panel say it out loud: the Pro-only controls are
labelled, and if a follow-up is ever refused you get told at that moment rather
than never.

Given the size of your sends, if you would like me to set up a follow-up on one
of them so it goes out properly, reply and I will do it.

Sorry about this.

Ali
OutMass

---

## faisal@samaed.com

**Subject:** Your follow-ups never went out — that was our fault

Hi Faisal,

I found a bug in OutMass and your account is one of the ones it affected, so I
want to tell you before you find it yourself.

When you turned on "Auto follow-up for non-openers" on 25 June and sent your
485-recipient campaign twenty minutes later, the follow-up was never created.
Automatic follow-ups are a Pro feature and you are on Starter — but the panel
never said so. It let you tick the box, write the follow-up, and press Send,
and then said nothing when our server declined to schedule it.

The limit was correct. Staying quiet about it was not, and that part is
entirely on us.

Two things I have done:

Your account is on **Pro for the next month, at no charge** — nothing to do
at your end. Follow-ups will now actually be created, along with
A/B subject testing and the AI writer. If it is useful, keep it; if not, you
drop back to Starter automatically and nothing changes.

And the next release makes the panel say it out loud: the Pro-only controls are
labelled, and if a follow-up is ever refused you get told at that moment rather
than never.

If you would like me to set up a follow-up on a recent campaign so it goes out
properly, reply and I will do it.

Sorry about this.

Ali
OutMass

---

## Helene@circularworkplaces.com

> **DO NOT SEND THIS DRAFT. Corrected 2026-08-30 from the database.**
>
> It was written on the 28th from PostHog's `send_completed`, and that event
> means the server ACCEPTED the send, not that anything went out. The
> campaign row says otherwise:
>
> | | |
> |---|---|
> | status | `scheduled` |
> | scheduled_for | 2026-09-01 07:30 UTC (Tue, 08:30 her time) |
> | daily_send_cap | 5 |
> | sent_count | 0 of 66 — every contact still `pending` |
>
> So she scheduled it herself for the Tuesday and paced it at five a day: a
> fortnight of sending, finishing around 14 September. **Not one email has
> gone out.** Two sentences below are therefore false — "the campaign sent
> fine" and "Your campaign went out to all 66 people" — and one of them was
> going to a customer who would have known immediately that we had not
> looked.
>
> What it changes, beyond the wording:
>
> * **Nothing has been lost.** The apology is about a follow-up that was
>   never created, not about a send that went wrong.
> * **A follow-up now would be worse than none.** Until the fix of
>   2026-08-30, the worker read "no contact sent yet" as "nobody left to
>   bump" and closed the follow-up permanently. Hers would have come due
>   before her campaign began.
> * **There is no hurry.** Her campaign starts on the Tuesday and runs a
>   fortnight, so the follow-up matters around the 14th, not today.
>
> Rewrite this section once the plan is settled; the other four are
> unaffected, their campaigns did send.


**Subject:** Your follow-up did not get scheduled — that was our fault

Hi Helene,

Thank you for subscribing on Friday. I owe you a correction two days later,
which is not the introduction I would have chosen.

On Friday you turned on "Auto follow-up for non-openers" at 11:58, and your
66-recipient campaign went out at 12:19. The campaign sent fine — but the follow-up was
never created. Automatic follow-ups are a Pro feature and you subscribed to
Starter, and the panel never said so: it let you tick the box, write the
follow-up, and press Send, then stayed quiet when our server declined to
schedule it.

I found it while looking at how your first day had gone.

The limit was correct. Staying quiet about it was not, and that part is
entirely on us.

So your account is on **Pro for the next month, at no charge** — nothing to
do at your end. Your follow-ups will now actually be created,
along with A/B subject testing and the AI writer. If it is useful, keep it; if
not, you drop back to the Starter plan you paid for and nothing changes.

The next release also makes the panel say it out loud: the Pro-only controls
are labelled, and a refused follow-up is reported at that moment rather than
never.

Your campaign went out to all 66 people. If you would like the follow-up sent
to those who have not opened it, reply and I will set it up.

Sorry to start this way.

Ali
OutMass


---

# Helene — the email to send (written 2026-08-30, for Monday 31 Aug)

**From** support@getoutmass.com · **BCC** outmassapp@outlook.com
**Send** Monday 31 August, around 09:00 London (08:00 UTC). She is in
Croydon; her campaign starts Tuesday morning, so Monday gives her a day to
reply before it does.

**Facts checked against the database on 2026-08-30, not against the events:**

| | |
|---|---|
| campaign | scheduled for 1 Sep 07:30 UTC (08:30 her time), 5/day, 66 recipients, **none sent** |
| finishes | around 14 September |
| plan | Starter, paid 28 Aug 12:18 UTC |
| comp | Pro until 28 September, applied 2026-08-30 |

**What she was told at the time, and what she was not.** She turned on A/B
subject testing at 11:37 and the follow-up at 11:58. Both are Pro. The A/B
refusal alerts (`sidebar.js:2216`) so she probably saw that one; the
follow-up refusal did not, which is the bug. The email says so in that order
— claiming she was told nothing about either would be wrong, and she would
know it.

**Why we cannot simply switch it on for her.** `maybeCreateFollowup` is only
reachable from the send flow (`sidebar.js:2267`, `:2421`); the panel has no
way to attach a follow-up to a campaign that already exists. Her Pro comp
fixes every future campaign and cannot fix this one, so this one needs her
text and our hands. That asymmetry is the reason the email asks for
something rather than just announcing a gift.

**Do not** offer to write the follow-up for her. The text she wrote on
Friday was never persisted anywhere — it lived in two DOM inputs and was
dropped on the 402 — so anything we composed would be our marketing copy
going out from her mailbox to her prospects under her name.

**Four things deliberately vague.** This is being scheduled rather than sent
by hand, so every phrase that counts days from today is a staleness trap —
the same one that made the first version of this file say her campaign had
gone out. "Three days in" became "almost immediately after"; "Tuesday
morning" became the date. And two claims were narrowed to what can be
verified: the next update is not promised for "this week" because two store
review queues decide that, and the A/B message is described as something the
product shows rather than something she saw, because an alert() leaves no
trace and I cannot know.

---

**Subject:** Your follow-up wasn't set up — my fault, and it's fixed

Hi Helene,

Thank you for subscribing on Friday. I owe you a correction almost
immediately after, which is not the introduction I would have picked.

When you set up the automatic follow-up at 11:58, it was never created. It
is a Pro feature and you had just subscribed to Starter — but the panel
didn't say so. It let you tick the box, write the follow-up, and carry on,
and then said nothing at all when our server declined it. The A/B subject
test you turned on a few minutes earlier is also Pro, and that one does show
a message when it is declined. The follow-up showing nothing was a bug, and
it is fixed in the next update.

Your campaign itself is fine. It starts on Tuesday 1 September and is set to
go out to five people a day, so the 66 should finish around the 14th.
Nothing has been sent yet, and nothing has been lost.

Two things I have done.

**Your account is on Pro until 28 September, at no charge** — that is the
day your next Starter payment is due, so it makes a natural point to decide.
Follow-ups, A/B subject testing and the AI writer all work now. If you want
to keep Pro, upgrade before then; if not, do nothing and you stay on Starter
exactly as you are.

And the next update labels both Pro controls, so you can see which is which
before relying on one.

There is one thing Pro cannot fix by itself. The panel can only attach a
follow-up while a campaign is being sent, and yours is already scheduled —
so this campaign's follow-up has to be added from my side. If you still want
it, reply with the subject and the message you'd like the follow-up to say,
and how many days after the first email it should go, and I will set it up
to run when the campaign finishes. I do not have what you wrote on Friday —
it was lost with the error, which is part of the same bug — so I would
rather ask than guess at your words.

If you would rather leave it, that is fine too, and nothing else changes.

Sorry to start this way.

Ali
OutMass
