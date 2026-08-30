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
7. **Facts get re-checked before posting.** Check roadmap item 423047 again
   before any answer that quotes it. Microsoft's own staff answers have quoted
   dates that already passed — do not repeat that mistake in the other
   direction.

## Roadmap 423047 — verification log

Read from Microsoft's own release-communications API, not from an article:
`microsoft.com/releasecommunications/api/v1/m365/423047`. Secondary coverage
has said June, July and August in the same week, so only this line counts.

| Checked | Status | Preview | GA | Card last modified |
|---|---|---|---|---|
| 2026-08-24 | In development | August CY2026 | September CY2026 | 29 May 2026 |
| 2026-08-27 | In development | August CY2026 | September CY2026 | 29 May 2026 |
| 2026-08-31 | In development | August CY2026 | September CY2026 | 29 May 2026 |

**2026-08-31: the August preview window closes today with the card
untouched since May.** That is not proof of a slip — Microsoft moves the
status when rollout begins, not when a date passes — but "preview in August"
and "still In development on the 31st" cannot both stay true for much longer.
Worth a check on the first working days of September: if GA arrives on time
the positioning shift stops being a plan and becomes urgent, and if the dates
move we get more room than we budgeted for. Either way we should learn it from
this API rather than from a headline.

The description field, read in full today, is also narrower than the feature
name suggests: "Mail Merge (Basic) will be improved upon to allow fields to be
replaced by values per email address ... the emails can further be
personalized to include content such as their name." Merge fields, and nothing
said about tracking, reply detection, follow-ups, scheduling, pacing or
reporting. That is the same silence this file already insists we describe as
silence — "Microsoft has not said", never "it cannot do".

**Nothing has moved.** "In development" is Microsoft's own word for *not
rolling out yet*; the states after it are "Rolling out" and "Launched". So the
08-24 blog post remains accurate: the basic mail merge already in new Outlook
gives each recipient their own copy of the same message, and the Advanced one
that personalises the body has not shipped.

**The 08-27 alert that prompted this re-check is a good example of why the
snippet is not the source.** It quoted a community thread reading "Users now
have mail merge, Quick Parts, Unified Inbox, and partial PST support, with
Advanced Mail Merge ..." — truncated exactly at the word the whole distinction
turns on. Read as "Advanced shipped", it would have sent us editing a correct
post.

**What to watch for:** the day `status` flips to Rolling out. That is when the
blog post needs its update and when "mail merge in Outlook" stops being
available to us as a headline claim at all.

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

## The watch (set up 2026-08-24, mechanics verified)

Being early is the whole game here, so the point of this section is to see a
question the day it appears rather than the month after.

**1. Follow the tag.** Signed in as bayar_ali@hotmail.com, open the tag page and
press Follow:
`learn.microsoft.com/en-us/answers/tags/1214/office-outlook-platform-windows-new-outlook-windows-business/`
That is the exact tag our first answer's thread carries — where "my merge broke
in new Outlook" questions land.

**2. Bookmark the unanswered feed.** Verified working, newest first, questions
with no answer at all:
`…/tags/1214/office-outlook-platform-windows-new-outlook-windows-business/?answerfilter=noanswers&orderby=createdat`
Useful parameters, confirmed on the live site: `answerfilter=noanswers |
unresolved | aiansweronly`, `orderby=createdat | updatedat | answercount`.
The `aiansweronly` filter is quietly the best one — a question whose only reply
is an AI answer is still effectively unanswered, and a real answer there tends
to become the accepted one.

**3. Google Alerts for the keyword net.** ✅ Two created 2026-08-24, because
`site:` is unreliable inside Alerts and one net alone would miss threads:
- `"mail merge" "new outlook"` — the broad net. Also doubles as competitive
  radar: when Microsoft actually ships Mail Merge (Advanced), this is where we
  hear it first.
- `site:learn.microsoft.com "mail merge"` — the narrow net. If it delivers
  nothing by mid-September, delete it; no loss.

**First delivery, 2026-08-25 — and it was junk.** The broad alert fired within a
day with "HOW TO MAIL MERGE IN OUTLOOK" on `ellaurel.gob.ec`, the site of a rural
parish government in Guayas, Ecuador. Checked, because a `.gob.ec` domain ranking
for our keyword is either very strange or very ordinary:

- The parish's own site is genuine. Its `inventario.` subdomain is **hacked** and
  serving auto-generated English spam under `/scholarship/` and `/browse/` paths
  ("merge cells in google sheets", "free lakeside collection catalog request by
  mail"). Classic parasite SEO: borrow a government domain's trust, spray keyword
  pages, monetise the clicks.
- The link Google showed leads to `reviewbooku.com/review/how-to-mail-merge-in-outlook-5043848`.
  That page is an ad farm — one auto-spun page per keyword, ~900 words of filler
  that never explains anything ("our platform gives you instant access... free PDF
  download"), three Adsterra iframe slots, no product, no video, no outbound link,
  and its own footer admits it: "(c) 2026 Review Template - Auto-generated layout."

**Action: none against the spam.** It is not a competitor, not a mention of us,
and not a link opportunity. Do not engage.

**Action on the alert:** in Google Alerts, edit `"mail merge" "new outlook"` ->
*How many* -> **Only the best results** (it defaults to "All results", which is
what let this through). If junk still dominates after a week, add `-download
-pdf -ebook` to the query.

**One thing worth keeping from it.** Google has indexed a hacked subdomain's
keyword page for the exact phrase our 2,400-word guide is still waiting on. That
is another point for the authority/crawl-budget reading of the indexing problem
(see `2026-08-24-practitioner-channels.md`) - the SERP is not judging our
content, it has not looked at it yet.

**Realistic expectation.** Checked on 2026-08-24, that tag had **five** unanswered
questions in total and none about mail merge; over the past year we found roughly
six mail-merge threads, all answered within days. So this is a fifteen-minutes-a-week
channel with maybe one or two genuinely answerable fresh questions a month — not a
daily habit. Do not force it: an answer written because the calendar said so reads
exactly like what it is.

## After posting

Note the thread URL and date in this file so we do not answer the same thread
twice, and so a future check can see whether these answers earned upvotes,
accepted-answer status, or traffic.

| Date | Thread | Posted by | Outcome |
|---|---|---|---|
| 2026-08-24 | [5945262 — Complete mail merge features in the new Outlook](https://learn.microsoft.com/en-us/answers/questions/5945262/complete-mail-merge-features-in-the-new-outlook) | Ali (bayar_ali@hotmail.com) | posted — first answer from this account; watch for upvotes / accepted status |

**No link to our blog was included, deliberately.** The answer already names the
product once; adding our own domain on top would double the promotional surface
on a thread that is a feature request, not a help request. The blog link is held
in reserve for a follow-up: if someone asks how the limits work or what the tool
actually does, linking it then is welcome rather than pushy.

**Check back around 2026-09-07:** did it earn upvotes, a reply, or accepted
status? That is the measurement that tells us whether this channel is worth the
monthly hours, and it is the first answer we can measure.
