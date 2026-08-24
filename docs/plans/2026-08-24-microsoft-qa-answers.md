# Microsoft Q&A — answer drafts and rules of engagement

Channel #2 from `2026-08-24-practitioner-channels.md`. People ask the exact
question we answer, under their real names, on a site whose threads rank in
Google for years. Answers are posted from Ali's own Microsoft account.

## Rules (read before posting)

1. **Answer the question completely, even without us.** If the honest answer is
   "switch back to classic Outlook", say that first and fully. A post that
   solves nothing and links a product is spam, and Microsoft Q&A moderators
   remove it.
2. **Disclose in the first line.** "Disclosure: I build OutMass, a third-party
   Outlook add-in" — every time, no exceptions.
3. **Only mention the product where it is genuinely one of the answers**, and
   name the alternatives too when they exist.
4. **Never post the same text twice.** Six threads with identical wording is a
   spam pattern. Answer two or three well rather than six mechanically.
5. **Skip resolved threads.** If an accepted answer already covers it, adding a
   reply is noise — even a good one.
6. **Skip old threads** unless the asker is still active. A 2024 thread with an
   accepted answer helps nobody.
7. **Facts get re-checked before posting.** The roadmap dates below were true on
   2026-08-24; check roadmap item 423047 again if posting later. Microsoft's own
   staff answers are currently quoting dates that have already passed — do not
   repeat that mistake in the other direction.

## Which account

Post as **bayar_ali@hotmail.com**, under the name Ali Bayar. Microsoft Q&A is a
personal-identity forum: people answer as themselves and reputation accrues to
the person. A brand account (outmassapp@) reads corporate on a community forum,
outmass.review@ is a test account and using it would be deceptive, and partner@
is the tenant admin. Pick one account and stay with it — the reputation score
is what makes later answers carry weight.

## What checking the threads actually showed (2026-08-24)

The threads we found from search are mostly **already answered**:

| Thread | State | Verdict |
|---|---|---|
| 5761318 "New Outlook not sending email merge" | accepted answer covers MAPI + workaround; an MVP added that the toggle is being removed and classic can be started from the Start menu | skip |
| 5611677 "not being received by recipient" | solid Microsoft-staff answer | skip |
| 1822752 "limit of recipients" | accepted answer, from 2024 | skip |
| 5945262 "Complete mail merge features" | open, no accepted answer — but the moderator already posted the roadmap card (preview Aug 2026 / GA Sept 2026, ID 423047) | answer, trimmed |

**The lesson for this channel:** its value is being early on a fresh question,
not retrofitting old ones. Every thread above was answered within days of being
asked. Set a watch on the Outlook tags and answer new mail-merge questions on
day one — that is how an answer becomes the accepted one and keeps earning for
years.

## Target 1 (trimmed) — "Complete mail merge features in the new Outlook"

`learn.microsoft.com/answers/questions/5945262` — asked 2026-07-13, still open.
Note it is a **feature request addressed to Microsoft**, not a help request, so
the product mention stays to one clause at the end. Do not repeat the roadmap
dates: the moderator's answer already shows that card.

> Disclosure: I build a third-party Outlook add-in, so factor that into the last
> line. The rest is just what I have had to learn.
>
> Adding the part the roadmap entry above does not explain — *why* it is missing
> rather than broken. Word's mail merge drives Outlook through MAPI, and only
> classic Outlook for Windows exposes that interface. New Outlook does not, so
> Word tries to hand the merge to classic Outlook and it stops there. That is
> also why what you are seeing looks like three half-features: the mail merge in
> new Outlook today is the basic version, which gives each recipient their own
> copy of the same message. It does not personalize the body per recipient,
> which is exactly why it feels like BCC with extra steps.
>
> Until the Advanced version actually lands, the only way to get the full Word
> merge is classic Outlook — turn off "Try the new Outlook", or, on builds where
> that toggle has been removed, start Outlook (classic) from the Start menu and
> set it as the default mail app. Worth doing before a big send anyway: Word's
> merge has no pacing of its own, and Exchange Online allows about 30 messages a
> minute and 10,000 recipients per rolling 24 hours, so large merges tend to
> crawl or stop partway rather than fail loudly.
>
> If the sends cannot wait for September, third-party add-ins do personalization
> on Outlook on the web today (SecureMailMerge and Mailmeteor among them; mine is
> OutMass). Otherwise classic Outlook remains the complete answer.

## Target 2 — a fresh "my merge stopped working" thread

Do not paste into the old ones listed above. When a new one appears, adapt:

> Disclosure: I build a third-party Outlook add-in, so I have spent more time in
> this particular hole than is healthy.
>
> This is almost always the new-Outlook switch rather than anything wrong with
> your document or your list. Word's merge talks to Outlook over MAPI, and only
> classic Outlook for Windows provides it; on new Outlook, Word opens (or tries
> to open) classic Outlook and the send never happens. Two checks that confirm it
> quickly: the messages do not appear in Sent Items, and no error is raised — the
> merge simply completes in Word and nothing leaves.
>
> The fix that works today is to run the merge from classic Outlook. If the
> "Try the new Outlook" toggle is gone on your build, start Outlook (classic)
> from the Start menu and set it as the default mail app. If classic is not
> installed at all, the alternatives are another machine that still has it, or a
> tool that sends through Microsoft Graph rather than MAPI.
>
> One thing worth knowing before a big send, whichever route you take: Exchange
> Online allows 10,000 recipients per rolling 24 hours and about 30 messages a
> minute per mailbox, and Word's merge has no pacing of its own. A few-thousand
> recipient merge will hit the per-minute ceiling and crawl, and a second day of
> sending can stop entirely once the 24-hour recipient count is used up.

## After posting

Note the thread URL and date in this file so we do not answer the same thread
twice, and so a future check can see whether these answers earned upvotes,
accepted-answer status, or traffic.

| Date | Thread | Posted by | Outcome |
|---|---|---|---|
| _pending_ | 5945262 | Ali | — |
