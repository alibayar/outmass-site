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

## Target 1 — "Complete mail merge features in the new Outlook"

`learn.microsoft.com/answers/questions/5945262` — asked 2026-07-13, no accepted
answer, still open. The moderator replied with a feedback-portal link and a
roadmap mention but **no workaround**, which is what the asker needed. High
value, low crowding.

> Disclosure: I build OutMass, a third-party add-in for Outlook, so treat the
> last paragraph accordingly. The rest is just what I have had to learn.
>
> The reason the merge is missing rather than broken: Word's mail merge drives
> Outlook through MAPI, and only classic Outlook for Windows exposes that
> interface. New Outlook does not, so Word tries to open classic Outlook and the
> merge stops there. A moderator confirmed exactly this on another thread here
> ("depends on MAPI integration, which is only available in the classic Outlook
> for Windows"), so it is expected behaviour rather than a fault on your machine.
>
> **What works today**
>
> - If you need the full Word merge back: turn off the "Try the new Outlook"
>   toggle and run it from classic Outlook. Everything behaves as before.
> - The mail merge you can see in new Outlook is the basic version: it gives
>   each recipient their own copy of the message, so nobody sees the recipient
>   list. It does not personalize the body per recipient — which is why it can
>   feel like a relabelled BCC.
>
> **What is actually planned**
>
> Microsoft 365 roadmap item 423047, "Mail Merge (Advanced) on Outlook on the
> Web and new Outlook for Windows", is the one to watch. As of 24 August 2026 it
> reads: status In development, preview August 2026, general availability
> September 2026. Its description says fields will be replaced per recipient so
> emails can include content such as the recipient's name. Worth noting that
> several articles still quote earlier dates for this item that have already
> passed, so it is worth reading the roadmap entry itself rather than a summary
> of it.
>
> **If you need personalization on Outlook on the web before then**, third-party
> add-ins fill the gap — SecureMailMerge and Mailmeteor both work in the Outlook
> ecosystem, and mine (OutMass) is a Chrome/Edge extension that merges from a
> CSV inside Outlook on the web and sends through your own account with the
> Graph API. Any of them beats waiting if the sends are time-sensitive.

## Target 2 — a "my merge stopped working after the upgrade" thread

Several are open (`5786491`, `5813458`, `5761318`, `5778805`, `5634950`). Pick
**one** that has no complete answer yet, and adapt — do not paste this verbatim
into several.

> Disclosure: I build a third-party Outlook add-in, so I have spent more time in
> this particular hole than is healthy.
>
> This is almost always the new-Outlook switch rather than anything wrong with
> your document or your list. Word's merge talks to Outlook over MAPI, and only
> classic Outlook for Windows provides it; on new Outlook, Word opens (or tries
> to open) classic Outlook and the send never happens. Two checks that confirm
> it quickly: the messages do not appear in Sent Items, and no error is raised —
> the merge simply completes in Word and nothing leaves.
>
> The fix that works today is to turn off "Try the new Outlook" and run the
> merge from classic Outlook. If classic is no longer installed on the machine,
> the alternatives are to run the merge on another machine that still has it, or
> to use a tool that sends through Microsoft Graph rather than MAPI — several
> exist for Outlook on the web.
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
