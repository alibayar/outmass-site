# How we write to customers

Internal. `docs/plans/` is excluded from the public Jekyll site.

Rules that were scattered across individual drafts, gathered here so they are
visible rather than remembered. Each one exists because of a specific incident;
the incident is the argument.

---

## Say what happened, whether it is fixed, and what happens next

Not how the bug worked.

On 2026-09-01 two paying customers hit the same fault within an hour. The first
drafts explained that Outlook receives HTML, that a line break there is only
whitespace, and that the immediate-send path converted it while the scheduled
worker did not. Ali cut all of it: *"Müşteriler bu kadar teknik detaya ihtiyaç
duymuyorlar."*

He was right. The mechanism is what **we** needed in order to fix it. The
customer needs only what lets them decide something — how many were already
sent, what happens to the rest, what they get back.

Admit the fault in one clause, without the anatomy. "A bug on our side meant
scheduled campaigns lost their line breaks" is enough.

And after a refund request, a long technical explanation reads as justifying
ourselves rather than answering.

## Never make someone argue for their own money

If a customer asks for a refund, refund it and say so. Do not ask whether they
still want it now that the thing is fixed, do not offer a discount instead, and
do not attach a question to it.

The fix being real does not change this. "But we fixed it" in reply to a refund
request turns a customer into an opponent.

Ask a question only where the action is **irreversible and possibly no longer
needed** — deleting an account someone requested in order to stop a campaign
that is now already stopped. That is a check, not friction, and it is obvious
which one it is from whether we benefit from the answer.

## Async only

Never offer a call or a screenshare. Email, and a screenshot if something needs
showing.

## BCC `outmassapp@outlook.com`

Every direct support email. Without it the thread exists only in one mailbox.

## Claims follow the product

Never describe a capability that is not live, and never promise a date for one.
"There is a Stop button now, coming with the next update" is fine because it
exists and is packaged. "We're building X" is fine. "X will be there next week"
is not.

## Do not stack gestures

One remedy per incident. A customer who already has a comped plan does not also
get a discount and an apology credit — piling them on reads as buying someone
off rather than fixing the thing.

Bug compensation is exempt from the usual "is this a gift or a crutch" test;
everything discretionary is not, and goes to Ali first.

## Numbers must be checked before they are written

Every figure in a customer email gets verified against the database or the
code first — not from telemetry that means something adjacent.

`send_completed` means *accepted*, not *delivered*. On 2026-08-28 an apology
draft told a customer her campaign "sent fine" on the strength of that event
while the campaign was still scheduled with zero sent. The row said otherwise.

## Credit a finder without a count

When someone reports something that turned out to be real, tell them what
their push prevented — not how many people it touched.

"You stopped other people running into the same thing" gives them the credit.
"It was affecting all 66 users" opens two doors nobody asked us to open: it
tells them how small we are, and it moves the subject from what they did to
how long we served everyone a wrong number. The second one turns a thank-you
into a disclosure, and they did not ask for a disclosure.

Ali, 2026-09-03, cutting a count from the note owed to Hélène Carpentier after
she refused to believe a 100% open rate and turned out to be right: *"kaç
kişiyi etkilediğini falan karıştırmayalım."*

This is the mirror of the numbers rule below. A figure that helps them decide
something is checked and written; a figure that only sizes our failure is left
out.

## What a good reply looks like

Four short paragraphs at most:

1. The state of the thing they are worried about, with the number.
2. What we did, or are doing, with no conditions attached.
3. The fault, admitted in a clause, with no anatomy.
4. The one question, if there genuinely is one.

Then stop. No sign-off pitch, no "we'd love to keep you", no roadmap.
