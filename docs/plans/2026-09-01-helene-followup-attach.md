# Hélène — attaching the follow-up she asked for (2026-09-01)

She replied at 16:15 Istanbul with the follow-up text, and asked three
questions. Two of them turned out to be bug reports.

> Please make sure the formatting is right and firstname is showing up
> correctly.

Neither was true when she wrote it. Both are fixed in `7dea631`, and neither
would have been found without her asking.

## What was wrong

**"Hi None,"** — `contact.get("first_name", "")` returns the default only when
the KEY is missing. PostgREST always returns the column, so a NULL first name
came back as `None`, the default never fired, and `str(None)` put the word
**None** into the greeting. All three send paths had it independently. They
now share one `build_merge_context()`.

**A link would have flattened her email.** One `<a href>` made the whole body
count as authored HTML and every newline in it became whitespace — the exact
bug she reported this morning, which she would have got back by taking the
feature she asked about next. `render_body` now distinguishes block markup
(the author laid it out) from inline markup (an ordinary email with a link in
it).

**Neither fix reaches her until the backend is deployed.** Her first follow-up
is due 2026-09-15, so there is time, but nothing should be attached to her
campaign until it is out.

## Checked: her list is clean

```
campaign_id  17a969ec-58d2-4c46-beee-825d344f6e05
user_id      18203a91-27a9-45d2-a76a-54aa2b640509
name         CBRE          status scheduled     daily_send_cap 5
contacts     66            no_first_name 0
first_sent   2026-09-01 07:34:57+00
last_sent    2026-09-01 09:40:22+00
```

**`no_first_name = 0`.** All 66 of her contacts have a first name, so the
"Hi None," defect would never have reached her — she asked about a bug that
was real and was not hers. Say that plainly rather than implying she was
rescued from something.

The two timestamps are the ten that went out today (five at 07:35, five more
at 09:40 after the manual resume). The other 56 have `sent_at` NULL and are
still to come at five a day, finishing around 2026-09-12. Every follow-up
therefore falls between 2026-09-15 and 2026-09-26 — inside her comped Pro,
which runs to 2026-10-01.

## The condition — a decision, not a default

She wrote *"add this for the follow up after 14 days"* and did not name a
condition. Her own text says *"I wanted to follow up on my previous note"*,
which is a nudge to people who did not respond.

The panel hardcodes `not_opened` (`extension/sidebar.js:3067`), and that is the
wrong choice here for a reason the panel itself states: its own hint text says
open tracking is *"distorted by Outlook and Apple Mail blocking or pre-loading
pixels"*. Conditioning on it would skip people who never saw the mail but
registered a false open, and bump people who read it and are still thinking.

**Use `condition = 'all'`.** Anyone who has replied is excluded regardless of
condition — the worker filters `replied_at is null` before anything else — so
`'all'` means exactly "everyone who has not answered", which is what she asked
for.

## The insert

Run it only after the backend carrying `7dea631` is deployed: the signature
link below is safe only from that commit onward.

The subject is read from her own campaign rather than retyped, so it cannot be
a near-miss. A follow-up is a new message, not a threaded reply — there is no
`In-Reply-To` — so the `Re:` prefix is what makes it read as a continuation.

```sql
insert into follow_ups
  (campaign_id, user_id, delay_days, subject, body, condition, status, scheduled_for)
select
  c.id,
  c.user_id,
  14,
  'Re: ' || c.subject,
  'Hi {{firstName}},

I hope you are well,

I wanted to follow up on my previous note and add one thing: one reason I set up Circular Workplaces after leaving CBRE was because I could see sustainability strategies often focus on energy and carbon, but waste is where the quick wins actually are.

The thing is, most teams don''t have the skillset or bandwidth to address it properly. That''s why I started Circular Workplaces, to help companies tackle waste without needing a full-time resource. We bring years of expertise in this space.

Would be great to have a quick conversation and see if this is something worth exploring together.

Have a nice day,

Helene Carpentier
Founder, Circular Workplaces
<a href="https://www.circularworkplaces.com">www.circularworkplaces.com</a>',
  'all',
  'scheduled',
  now() + interval '14 days'
from campaigns c
where c.id = '17a969ec-58d2-4c46-beee-825d344f6e05';
```

The apostrophes in `don''t` and `That''s` are doubled because SQL. Getting that
wrong fails the statement rather than sending something odd, but check it.

Then confirm it landed rather than assuming:

```sql
select id, delay_days, condition, status, scheduled_for, subject,
       left(body, 30) as body_starts
from follow_ups
where campaign_id = '17a969ec-58d2-4c46-beee-825d344f6e05';
```

Expect one row: `delay_days 14`, `condition all`, `status scheduled`,
`scheduled_for` 2026-09-15, subject beginning `Re: `.

## Her three questions, answered honestly

**"Is there a way to amend a campaign directly on the extension?"**
No. There is no edit path for a campaign at all — no endpoint, no control.
Stopping one is new in 0.3.2, which is in store review and not yet live for
her, so it cannot be offered as an answer today either.

**"Is there a way to add links into the text?"**
Now yes, but only by typing the HTML by hand, which is not an answer for
someone writing an email. The honest offer is to set them up on her behalf
while a proper control is built.

**"Add a logo in signature?"**
Only if the image already lives at a public URL — we host nothing. Her site
almost certainly has one. Worth asking for the exact URL rather than guessing
at it.

## Draft reply

Subject: **Re: Your follow-up wasn't set up — my fault, and it's fixed**

> Hi Hélène,
>
> Thank you — and you were right to ask about the first name. I checked your
> list: all 66 contacts have one, so it will show correctly for every person on
> it. Your question did find a real problem for lists that have gaps, and that
> is fixed now too.
>
> **Your follow-up is attached.** It goes out 14 days after each person
> received your original, so it follows the campaign rather than arriving all
> at once, and anyone who has replied to you is left out automatically.
>
> On your other two questions:
>
> **Links** — I have set up the link on your website in the signature. Adding
> them yourself isn't straightforward yet; it's on the list, and in the
> meantime send me the text and I'll set them up for you.
>
> **A logo in the signature** — possible, and I can add it if you send me the
> web address of your logo image.
>
> **Editing a campaign after it has started** — not possible at the moment.
> That is a real gap and I'd rather say so than have you look for it.
>
> Ali

Send notes: BCC `outmassapp@outlook.com`. No call offered — async only.
