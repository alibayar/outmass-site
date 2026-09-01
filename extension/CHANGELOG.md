# OutMass Changelog

All notable user-facing changes to the OutMass Chrome Extension.

## v0.3.2 — 2026-09-01

- **You can stop a campaign.** Until today you could not — not from the panel,
  not from anywhere. A campaign that was scheduled or part-way through simply
  ran to the end. There is now a Stop button on the campaign's report, and it
  tells you how many people have already received it **before** you confirm,
  because that is the one part nobody can take back.

  If a send is actually in progress at that moment, it finishes the few it
  already has in hand — at most ten — and then stops. So the number you are
  shown can end up slightly lower than the number who received it.

- **Scheduled campaigns keep your line breaks.** A campaign you scheduled was
  sent without the conversion that turns your paragraphs into email
  formatting, so it arrived as a single block even though the preview looked
  right. Sending immediately was never affected. This is fixed for scheduled
  campaigns and for follow-ups.

## v0.3.1 — 2026-09-01

- **A locked feature now tells you what it costs and how to get it.** Turning
  on follow-ups, A/B subject testing or the AI writer on a plan that does not
  include them used to produce a message naming the plan and nothing else — no
  price, no button, nowhere to go. All three now open the same panel the
  monthly limit uses, showing the plans that actually unlock what you clicked,
  with their prices. Only those: a plan that would not give you the feature is
  no longer offered.

- **A follow-up you set up is no longer thrown away.** Until now the single
  moment a follow-up could be attached to a campaign was the instant you
  pressed Send. If your plan could not run it, the subject line and text you
  had just written were discarded, and that campaign could never have one —
  even after upgrading. Your follow-up is now saved with the campaign and
  waits. When your plan can run it, the campaign's report offers to start it.

  Nothing starts by itself. If starting one would reach people immediately —
  which happens when a campaign finished long enough ago that the follow-up
  is already due — you are told how many before anything is sent.

- **"Write with AI" now says PRO**, like the follow-up and A/B controls beside
  it, instead of looking free until you press Generate.

- **Large campaigns no longer stop short and report themselves finished.** A
  campaign with more than a thousand recipients could send part of the list,
  find nothing wrong, and close as sent — leaving the rest unsent with no way
  to reach them. Such a campaign is now marked partial and finishes on its
  own. This affected uncapped campaigns over a thousand recipients; campaigns
  with a daily limit were never affected.

## v0.3.0 — 2026-08-31

- **OutMass no longer asks Microsoft for your subject lines.** Reply
  detection needs to know that someone answered, not what the conversation
  was about — but it asked Microsoft for the subject of the matching message
  anyway, and then did nothing with it. That request is gone. The note shown
  before the Microsoft permission screen now says so plainly: reply
  detection looks at who wrote to you and when, and never at what they
  wrote.

- **The sign-in explanation is calmer, and in your language.** That same
  note used to recite the permission names, which reads as a warning rather
  than an explanation to someone arriving there for the first time. It now
  says what the next screen is, what OutMass will be able to do, that
  nothing happens until you accept, and that you can withdraw it later — in
  all thirteen languages the panel speaks.

- **Follow-ups and A/B subject testing now say PRO on the control itself.**
  Both are Pro features and both looked like ordinary switches: you could
  tick one, close the panel, and believe it was on. They now carry a PRO
  badge, the same as the pricing page has always shown.

- **A follow-up your plan does not include now tells you, instead of
  vanishing.** The server refused to create it and the panel said nothing at
  all, leaving the switch ticked and the text you had written on screen.
  Five people had follow-ups set up this way that were never going to be
  sent. The panel now says the feature needs Pro, unticks the switch, and
  sends your campaign exactly as it would have otherwise.

- **A list larger than your monthly limit is no longer refused at the door.**
  800 recipients on a plan that sends 250 a month used to be rejected
  outright, so you never got to see the product work at all. Any plan can now
  upload up to 10,000 in one go. The monthly limit still decides how many
  actually leave — the rest wait for your next reset — and the panel tells you
  up front roughly how many months that will take, rather than implying they
  all go at once.

- **OutMass no longer asks to read your mail when you first sign in.**
  Reply detection is the only feature that needs it, and it cannot matter
  before you have sent anything — yet "Read your mail" was the most alarming
  line on a permission screen shown to someone who had not sent a single
  email. It is now asked for separately, later, when you turn reply
  detection on. Nothing changes if you already signed in.

- **"Sent" now means sent.** Pressing Send used to answer "Success! 42
  emails sent" the instant the server accepted the job — before a single
  message had been attempted. If something then went wrong part-way, nothing
  ever corrected it: one person was told 9 had gone out when 2 had. The
  message now says what is starting, and a line under the button follows the
  send and tells you what actually happened — all of them, or how many, or
  that it is still running and Reports will have the answer.

- **Follow-ups say what the delay counts from.** "After how many days?" now
  adds that the clock starts when each person receives your email, not when
  the campaign begins — which matters if you spread a campaign over days. And
  a campaign with a follow-up waiting says the same thing in Reports instead
  of only showing a count.

- **Scheduled sending suggested the wrong time, everywhere but one.** Turning
  it on offered "tomorrow at 9am" — but the suggestion was built in UTC and
  then read back as your own clock, so it arrived shifted by however far you
  are from Greenwich. London saw 8am, Berlin 7am, Istanbul 6am, and Beijing
  one in the morning. A suggestion is something most people accept, so this
  had been quietly choosing bad send times for anyone not sitting on UTC.
  It now offers nine in YOUR morning.

- **Small fixes.** The plan list offers only the plans you can actually buy
  from where you are standing, and the button comes back if you close the
  payment page without paying. A sign-in window left open and closed much
  later no longer reports a second failure against whichever account you
  have signed into by then. And when Microsoft is still setting OutMass up
  inside a brand-new organisation — a short race on their side that clears
  in seconds — OutMass waits and tries once more by itself instead of
  blaming itself and stopping.

### Already live, whichever version you are on

These two are server-side, so they reached you without an update.

- **"Follow up 3 days later" now means three days after each person
  received it.** For a campaign that goes out in one go, that is what it
  always meant. For one spread over days — scheduled ahead, or paced by a
  daily limit — it did not: 66 recipients at 5 a day take a fortnight, and
  the follow-up either fell due before the first email had even left (and
  then marked itself finished, having emailed nobody) or arrived for
  everyone at once at the end, sixteen days late for whoever was first on
  the list. The follow-up now trails the campaign, going out to each
  recipient on their own three days, and stops only once everyone has had
  theirs. Nothing changes for a campaign that goes out at once.

- **One refused message no longer condemns the rest of your list.** If
  Microsoft refused a send part-way through a scheduled campaign because of
  the mailbox rather than the recipient, every remaining address was marked
  permanently undeliverable — out of reach of both Resume and the automatic
  retry — and the campaign then reported itself as sent. It now stops,
  leaves the untouched recipients waiting, and records why, so the campaign
  carries on from where it stopped.

## v0.2.2 — 2026-08-15

- **OutMass will write to you in the language you read it in.** Every email
  we send after your first sign-in — quota reached, plan changes, reconnect,
  the lot — has been English regardless of the language you have the panel
  set to, because we had no way of knowing which one that was. The panel now
  tells the server which language it is showing, and the emails are written
  in twelve more: Arabic, Chinese (Simplified and Traditional), French,
  German, Hindi, Japanese, Portuguese (Brazil and Portugal), Russian,
  Spanish and Turkish. Nothing is sent anywhere else; it is the same value
  the panel already uses to render itself. Two honest limits: the very first
  welcome email stays English, because it is sent before the panel has ever
  talked to us — and if you have not updated, or your language is not one of
  these, everything stays in English exactly as before.

- **The monthly-limit message now shows both plans, with prices.** 0.2.1
  put real prices on the Account tab's plan list; this release brings the
  same list to the two places it was still missing. The message you get
  when you reach your monthly limit part-way through a send used to offer
  one button, with no price, that bought Starter whichever plan you
  actually wanted; it now shows both plans with their price and limit. And
  the toolbar popup's upgrade buttons carry the real current price instead
  of one written into the extension. As everywhere else: when the panel
  cannot reach the server, buttons show no price rather than a stale one.

- **The quota bar and the Account tab can no longer disagree about your
  plan.** They could: the bar above the editor might say "250/250 (Pro
  Plan)" while the Account tab said Free, at the same moment — each was
  reading a different stored copy of the same answer, and changing accounts
  could leave the previous account's numbers standing next to the new
  plan. Everything now paints from one fresh server answer and repaints
  the moment that answer changes. And when the panel genuinely cannot
  reach the server, the Account tab shows a dash instead of quietly
  displaying "Free / 0" — which used to look exactly like a real free
  account.

- **An out-of-date memory of your plan can no longer stop your send.**
  Right after an upgrade, the pre-send check could still be holding
  yesterday's answer — and refuse the send at the Free limit for a
  customer who had just paid for more. That check now blocks only on a
  live answer from the server, fetched at the moment you press Send. When
  that answer cannot be fetched, the send proceeds unchecked and the
  server remains the judge, exactly as before — which also means the
  up-front "only the first N will be sent" warning cannot appear offline;
  the server still stops at your limit and reports what was saved.

- **An in-place upgrade now says so, instead of reporting a failure.** If
  you already have a subscription and pick the higher plan, there is no
  payment page to open: Stripe adjusts the existing subscription and
  charges the prorated difference. The panel used to treat that success as
  a failed attempt to open a payment page — you were upgraded, charged
  correctly, and told "Could not create payment page." It now says what
  happened. (The toolbar popup always got this right; the panel's plan
  list did not.)

- **German, French and Spanish now read like themselves.** The same defect
  0.2.1 fixed for Turkish, in three more languages: German written as
  ASCII transliteration ("fuer", "Empfaenger"), French and Spanish with
  their accents dropped outright — Spanish worst, where dropping the tilde
  changes the word: the panel offered to archive "esta campana", a bell.
  119 strings corrected across the three (32 German, 42 French, 45
  Spanish), wording unchanged, and the check that already guards Turkish
  now guards all four.

## v0.2.1 — 2026-08-13

A patch release that grew. OutMass asks Microsoft for less than it used to,
explains what Microsoft is about to ask before you get there, no longer
leaves a stopped campaign looking like one that simply never sent — and the
Account tab starts showing real prices.

- **OutMass no longer asks to read Microsoft's login site.** The install
  screen listed permission for `login.microsoftonline.com` and
  `graph.microsoft.com` — two sites OutMass never actually contacts. Sending
  happens on the server, and signing in uses Chrome's own sign-in window,
  which needs no permission from you. Both are gone, so the list Chrome shows
  you at install is shorter and truer.

- **The panel now says what Microsoft is about to ask for.** Since 0.2.0 the
  panel opens by itself the first time you reach Outlook, which meant many
  people arrived at Microsoft's permission screen having read nothing about
  it. Before you sign in, the panel now explains in one sentence what OutMass
  will be allowed to do and what it will not — the same wording that has been
  in the toolbar popup, in your own language. It appears only on a first
  sign-in; reconnecting does not repeat it.

- **A campaign stopped by an expired Outlook connection now says so.** If
  your Microsoft authorisation expired while a scheduled campaign was waiting
  to go out, that campaign stopped — and in Reports it looked identical to
  one that had simply not sent anything. It now says it is paused and that
  signing in to Outlook again is what puts it back in play. For a recent
  campaign that then happens by itself (below); an older one is left for us
  to look at rather than sent behind your back.

- **You can now see what a plan costs before you reach the payment page.**
  The Account tab used to show a single "Upgrade Plan" button that took you
  straight to Stripe — so the only way to learn the price was to open a
  payment form, and Pro could not be bought from the panel at all. Both
  plans are now listed with their price and their monthly limit, and you
  choose. The prices come from Stripe and the limits from the server, so
  neither can drift out of date — and when the panel cannot reach the
  server, it shows the plain button rather than a price it is not sure of.

- **If your plan ends, the panel says so — and why.** A subscription that
  ran out or a trial that finished used to leave no trace anywhere in
  OutMass; the first sign was hitting the Free limit in the middle of a
  send. For a couple of weeks afterwards the Account tab now explains what
  happened, right above the plans, so starting again is one click rather
  than a hunt. (You also get an email at the moment it happens — unless you
  cancelled it yourself, in which case you already know.)

- **Turkish now reads like Turkish.** Around a fifth of the Turkish
  interface had been typed without the letters ç, ğ, ı, ö, ş and ü —
  "gonder" for "gönder", "Arsivle" for "Arşivle" — so the panel was half
  properly written and half not. Sixty-seven strings corrected, wording
  unchanged.

- **Two controls no longer hang off the edge of the panel.** The Delete
  button next to the template list sat outside the panel in French and in
  several other languages, forcing the panel to scroll sideways to reach it.

### Behind the scenes (backend — affects all extension versions)

- **A scheduled campaign stopped by an expired connection is no longer lost.**
  It used to be set aside permanently: signing in again cleared the warning
  but never brought the campaign back, and nothing in Reports said what had
  happened, so the recipients simply never heard from you. Reconnecting now
  returns those campaigns, follow-ups and A/B tests to the queue, and they go
  out on the usual schedule — a campaign that spreads over several days picks
  up at its normal daily pace rather than sending everything at once.
  Anything older than a week, and anything you have archived, is deliberately
  left alone rather than surprising a list that has gone stale.

- **A failed renewal no longer takes your plan away on the first attempt.**
  When a subscription payment failed, the plan dropped to Free immediately —
  even though the card is retried for about two weeks and often succeeds.
  Your plan now stays until the subscription actually ends.

- **Your monthly usage is counted as a campaign sends, not only at the end.**
  If a send was interrupted halfway — a deploy, a restart — the emails that
  had already gone out were not counted against your quota. Accurate either
  way now, and a hiccup while counting can no longer make a delivered
  recipient look unsent and get them a second copy.

## v0.2.0 — 2026-08-08

A minor version rather than another patch, because two things behave
differently rather than merely better: a contact list OutMass cannot read now
opens a dialog asking which language it is in, instead of being loaded with
quietly broken names; and the panel gained a permission it can ask for on its
own.

- **OutMass can now turn reply detection back on by itself.** Reply detection
  needs Microsoft's permission to see your inbox, and until now that
  permission could only be granted at sign-in — if it was missing there was
  no way to fix it from inside OutMass, and nothing told you it was missing.
  The panel now says so plainly and can ask for that one permission on its
  own, without signing you in again. Nothing changes if you already granted
  it, which today is everyone: this is groundwork for asking for less at
  sign-in, and you will see that change announced when it happens.

- **The panel opens itself the first time you reach Outlook.** After installing, you no longer have to hunt for the round OutMass button in the corner — open Outlook once and the campaign panel is already there. It happens exactly once; after that the panel opens only when you ask for it.
- **A slow sign-in no longer gets told it failed.** If the Microsoft window stayed open for five minutes, OutMass used to say "sign-in timed out, please try again" — untrue, because that window is still open and still works. It now tells you both options, in your own language (the message was English-only before).
- **A hint while you're signing in.** If a sign-in is still going after a minute, the panel quietly notes that an organisation requiring admin approval for new apps will say so on Microsoft's screen — the single most common reason a first sign-in stalls, and something Microsoft's page doesn't spell out.
- **Clicking Sign in again now brings the sign-in window to the front.** If the Microsoft window opened behind Outlook or on another screen, clicking Sign in again used to only tell you a window was open somewhere. Now it also brings that window forward.
- **The panel button can no longer do nothing.** When OutMass updates itself, any Outlook tab you already had open quietly loses its connection to the extension until the page is refreshed. Clicking "Open Campaign Panel" in that tab used to do nothing at all, however many times you tried it, with no explanation. It now tells you to reload the Outlook tab — which is all it takes.
- **Dropping the wrong file now tells you.** Dragging an Excel .xlsx file — or anything that isn't a CSV — onto the recipient box did absolutely nothing: no message, no hint, so the drop zone looked broken. It now says what happened and how to save your file as a CSV.
- **Contacts.CSV works when you drag it.** Exports from a CRM or from Outlook often arrive with an uppercase .CSV extension. Those already worked when you picked them through the file browser, but were silently ignored when dragged in. Both routes now behave the same.
- **A file that can't be read now says so** — instead of leaving you waiting for a preview that never arrives. This comes up with files on a disconnected network drive, or a USB stick that was unplugged.
- **Reports says when it can't load your campaigns.** If the server had a problem, the list said "no campaigns found", which read as though your campaigns were gone. It now reports the error for what it is.
- **Lists written in your own alphabet now load.** Excel saves in whatever character set your computer uses, and until now OutMass could only read UTF-8 and the two Chinese ones — so a contact list written in Russian, Ukrainian, Bulgarian, Serbian, Arabic, Persian, Hebrew, Greek or Thai was rejected or garbled. OutMass now reads the alphabet of the language OutMass itself is set to, falling back to your browser's.
- **And when it still can't tell, it asks instead of giving up.** Turkish, Polish, Baltic, Vietnamese and Western European character sets genuinely cannot be told apart by looking at the file — the same bytes are valid in all of them — so OutMass no longer pretends otherwise. It shows you the first few names decoded, with a list of languages to choose from: pick one, watch the names in the preview, and load the file when they look right. It starts on its best guess, so usually that is a single click.
- **A file we can't read is never half-read.** Some lists — Polish and other Central European ones especially — used to load with names quietly shortened or replaced: `Łukasz` came through as `kasz`, and nothing said anything was wrong. That cannot happen any more: OutMass either reads a file correctly or asks you which language it is in. Chinese lists are unaffected, including ones with only a couple of Chinese names in them.

### Behind the scenes (backend — affects all extension versions)

- **A failed sign-in now finds its way back to you.** When Microsoft reports a problem during sign-in (for example, your organization requires admin approval), the error used to sit in a window that stayed open until you noticed and closed it — and the extension never learned the reason. That window now shows the reason for a few seconds and then returns to OutMass on its own, so the Sign in button is immediately usable again and the message tells you what actually happened.
- **Declining a permission no longer reopens the same permission screen.** If you said no on Microsoft's consent screen — or Microsoft refused for any other reason — OutMass could not tell the difference between that and the page failing to load, so it helpfully tried again, showing you the screen you had just dismissed. It now recognises the difference and stops.

## v0.1.27 — 2026-07-29

- **OutMass now speaks Portuguese.** The whole panel is available in Português (Brasil) and Português (Portugal) — two separate translations, not one shared approximation, so each reads the way you actually write. Pick either in Settings → Interface Language, or let OutMass follow your browser. The AI Email Writer can now draft in Portuguese too.
- **繁體中文 is now a real translation.** Browsers set to Traditional Chinese used to fall back to the Simplified text. There is now a proper Traditional translation written in Taiwan terminology (軟體, 檔案, 資訊, 範本 — not converted Simplified wording), selectable as 繁體中文 in Settings, and the AI Email Writer can draft in Traditional Chinese. Your recipients' unsubscribe pages follow the same rule: someone reading Traditional Chinese no longer gets a Simplified page.
- Both Chinese options are now labelled explicitly in the AI writer (Simplified / Traditional) instead of one ambiguous "Chinese".
- **The Sign in button can no longer go dead.** If a Microsoft sign-in window was left open and forgotten (behind another window, on another screen), clicking Sign in again used to do nothing at all, silently, however many times you tried. Now clicking again first points you to the already-open window — and if you still can't find it, your next click simply opens a fresh one. A stuck sign-in also reports itself instead of hanging forever.
- **Clearer message when a campaign hits your monthly limit.** OutMass used to tell you to come back and press Resume after your reset. It now says what actually happens: the remaining recipients are saved and go out automatically after your monthly reset — upgrading is only if you want them sooner. The Resume hint in Reports was reworded for the same reason.

### Behind the scenes (backend — affects all extension versions)

- **Recipients skipped at your monthly limit now send themselves.** When a campaign hits your monthly quota, the remaining recipients used to wait for you to remember the Resume button after your reset. Now OutMass resumes them automatically as soon as your quota resets (or right after an upgrade) — and emails you at the moment of the cap so you know exactly how many are saved and when they'll go out.
- **Automatic resume now covers your whole billing month.** It only looked at campaigns from the past two weeks, so recipients parked early in your month could sit there past your reset. It now follows your own monthly cycle instead of a fixed two weeks.
- **Scheduled campaigns that run into your monthly limit no longer report as finished.** A scheduled send whose list was longer than your remaining quota sent what it could and then marked itself complete, leaving the rest waiting with nothing to pick them up. Those campaigns are now correctly marked as partially sent, so the automatic resume finishes them after your reset.
- Unsubscribe pages are now available in Portuguese for your recipients (11 languages total).

## v0.1.26 — 2026-07-18

- **Your CSV columns now appear as clickable tag chips under the editor.** Upload a CSV and every column shows up as a {{tag}} you can click to insert at the cursor — no more typing a tag from memory and finding out at Send time that your file has no such column.
- **Stay signed in while you're active.** Your OutMass session now renews itself in the background as you use it. Previously it quietly expired every 24 hours, and the first Send of the day could fail with a sign-in prompt. (Signing in again after a long break is still required — that part is a security feature.)
- **No more repeated sign-in windows when adding a OneDrive attachment.** If OneDrive access couldn't be enabled, the picker used to open the Microsoft sign-in window again and again. Now it asks at most once per attempt and then explains what's going on (e.g. your Microsoft account may not include OneDrive) and how to proceed. The underlying authorization bug was fixed on our servers, so for most people OneDrive attachments simply work now — no extension update needed.
- Clearer wording on the Microsoft-permissions notice about what OutMass stores: OutMass never reads your other emails, and your campaigns are stored securely to power scheduling and follow-ups.

### Behind the scenes (backend — affects all extension versions)

- **Follow-ups now skip anyone who has replied.** If a recipient answers your campaign, scheduled follow-ups ("didn't open" / "didn't click") will no longer be sent to them. Nobody gets an automated bump mid-conversation.

## v0.1.25 — 2026-07-15

- **NEW: Daily send limit — spread one campaign over multiple days.** In the Schedule section, set an optional "Daily send limit" (e.g. 30): OutMass sends up to that many emails per day, server-side, and automatically continues the next day until your whole list is done. Great for careful cold outreach and gradual warm-up. (Not combinable with A/B testing in this first version. Requires Starter or Pro, like scheduled sending.)
- **The panel now tells you when you haven't signed in yet.** Previously you could build an entire campaign without an account and only hit a cryptic English error at Send. Now a sign-in banner appears at the top of the panel from the start, and Send/Test explain in your own language that sending needs a Microsoft sign-in first (composing still works without one).
- **New-install welcome page.** Right after installing, OutMass opens a short "your first campaign in 3 steps" page — where to find the panel in Outlook, how to sign in, and how to send — instead of leaving you to guess.
- **OutMass now talks to its servers via our own domain (api.getoutmass.com), with the old address kept as an automatic fallback.** Some corporate and national networks block shared hosting domains outright — on those networks OutMass could never connect (or even sign in). Whichever address works on your network is used automatically. Because this adds a new permission, **Chrome/Edge may ask you to re-approve the extension with one click** — that's expected; scheduled sends and follow-ups run on our servers and are never interrupted.

## v0.1.24 — 2026-07-14

- **CSV files from Excel now work in more encodings.** Excel's default "CSV" save on Chinese (and some other) systems isn't UTF-8, which OutMass used to reject outright. OutMass now auto-detects and reads GBK/GB18030 and Big5 files too — and when a file truly can't be read, the error finally tells you the exact fix: save it as "CSV UTF-8 (Comma delimited)" in Excel. (All 11 languages.)
- **Honest message when OutMass can't reach its servers.** If your network, VPN or firewall blocks the connection, sending used to fail with a generic error that looked like an account or plan problem. You now get a clear "this is a connection issue — not your plan" message, and the panel shows a banner as soon as it detects the servers are unreachable (it re-checks and disappears by itself once the connection is back).
- Requests that can't get through now stop after 20 seconds instead of hanging, and failures are reported with their real cause so we can help faster if you contact support.

## v0.1.23 — 2026-07-08

- OutMass now works on Microsoft's **new Outlook web address** (outlook.cloud.microsoft). Microsoft has started moving business accounts there automatically — on moved accounts the OutMass panel and the corner button never appeared, and "Open Campaign Panel" just opened a plain Outlook window. Both now work on the new address.
- Because this update teaches OutMass about the new address, **Chrome/Edge may ask you to re-approve the extension with one click** ("New permissions required"). That's expected — one click and you're back. Scheduled sends and follow-ups run on our servers and are never interrupted.
- "Open Campaign Panel" is now more patient: when it opens a fresh Outlook tab, it keeps trying until the panel is actually ready (slow loads and Outlook's sign-in redirects no longer swallow it).

## v0.1.22 — 2026-07-02

- No more silent partial sends at your quota limit. If your campaign has more recipients than your remaining monthly allowance, OutMass now tells you exactly how many were sent and how many are waiting (e.g. "47 sent, 53 pending") — the rest stay saved, and Resume sends them after an upgrade or your monthly reset. Previously the send quietly stopped at the limit and looked like everything went out.

### Behind the scenes (backend — affects all extension versions)

- The "monthly limit reached" message is now in English (it was accidentally shown in Turkish for everyone).

## v0.1.21 — 2026-06-26

- Smoother first sign-in. The sign-in screen now explains up front why Microsoft asks for mail permissions — OutMass sends from your own Outlook account and never stores your email content — so the Microsoft consent prompt isn't a surprise. (Localized in all 11 languages.)
- Chinese-language users now see the Chinese interface on every variant (Traditional, Hong Kong, Singapore, generic zh), not only Simplified-China — previously those locales fell back to English.
- internal: suppressed a harmless "Could not establish connection. Receiving end does not exist." console error that could appear when opening the campaign panel before an Outlook tab's content script had loaded. No user-visible change. (The v0.1.20 sign-in fixes are unchanged and already live.)

## v0.1.20 — 2026-06-25

- Fixed a sign-in loop that hit Microsoft 365 **work & school accounts**. The "Open Campaign Panel" button now opens *your* Outlook — work accounts land on outlook.office.com, personal accounts on outlook.live.com — instead of always opening the personal host, which bounced work users to a Microsoft sign-in page that looked like an endless login loop.
- Hardened the session: a routine background refresh (when you open the popup) can no longer sign you out on a transient hiccup. Only deliberate sign-out or a real expiry ends your session now.

## v0.1.19 — 2026-06-25

- Smoother sign-in. Clicking "Sign in" (or the reconnect banner) several times in a row no longer opens multiple Microsoft sign-in windows at once — OutMass now reuses the one already in progress. This also clears the stray "didn't approve access" errors that came from closing the extra windows.

## v0.1.18 — 2026-06-25

- Large sends now stay within Outlook's limits automatically. OutMass paces every send (~30 emails/min) so it no longer trips Microsoft's rate limit — and before a big send (500+ recipients) you'll see a heads-up with the estimated time and a reminder that very large cold lists deliver best when spread over several days.
- Clearer feedback confirmation. After you send a message from the Support tab, OutMass now confirms we received it and will reply to your email — instead of a bare "submitted".

### Behind the scenes (backend — affects all extension versions)

- Re-mailing your own list is no longer blocked by a failed send. Cross-campaign de-duplication now only skips recipients who were actually delivered to (or are still queued in a live campaign) — recipients left un-sent by a failed or partial campaign are no longer treated as "already contacted".
- Unsubscribe and open/click links with a truncated or garbled ID (e.g. from some email security scanners) now return a clean page instead of a server error.
- Less noise in our error tracking from harmless browser-internal warnings, so real issues surface faster.

## v0.1.17 — 2026-06-24

- More reliable sign-in. If the Microsoft authorization page occasionally failed to load on the first try (a brief server hiccup), OutMass now wakes the backend and retries once instead of erroring out. (Consent prompts you decline are never retried.)
- Accurate monthly quota. The usage bar and the pre-send check now read your real sent-this-month count from the server, so you're warned about your remaining quota up front instead of only hitting a limit error after building a whole campaign.
- Clearer "limit reached" prompt. The upgrade dialog now shows exactly how much of your plan you've used (e.g. "250 / 250") instead of a numberless wall.
- Smoother recovery if your sign-in expires while composing. Sending now shows the one-click reconnect banner (and keeps your work) instead of a raw error, and won't leave a half-created campaign behind.
- Easier to reopen OutMass. A small floating OutMass button now sits in the corner of Outlook so you can open the sidebar anytime, without going through the menu.
- Clearer CSV import. Rows with no email address are now counted and shown (like duplicates are), and the "missing email column" error points you to the example file.
- Fixed a rare glitch where a stray "session expired" banner could appear right after you deliberately signed out.

### Behind the scenes (backend — affects all extension versions)

- Scheduled and A/B campaigns no longer silently drop recipients on a send hiccup — failures are recorded and the campaign is marked "partial" so **Resume** can finish it. A single malformed record can no longer freeze A/B winner evaluation for everyone.
- Over-quota scheduled campaigns now wait and retry after your monthly reset instead of being marked failed.
- A large send that outruns the ~1-hour Microsoft token now stops cleanly and becomes resumable (Resume refreshes the token and finishes the rest) instead of dropping the remainder.
- Fixed a reconnect-banner loop, and a case where a fully-failed follow-up was reported as sent.

## v0.1.16 — 2026-06-20

- Clearer sign-in errors. If your organization requires an administrator to approve new apps (common on Microsoft 365 work accounts), OutMass now explains what happened and how to proceed — contact support or use a personal Outlook.com account — instead of showing a generic failure.

## v0.1.15 — 2026-06-17

- Fixed the prices shown on the upgrade buttons and upgrade dialog. The "$" before a number was being swallowed by the translation system, so Starter showed no price and Pro showed "9/mo" instead of "$19/mo". Prices now display correctly in all languages.

## v0.1.14 — 2026-06-14

- internal: fixed product analytics region (events were being sent to the US PostHog endpoint while the project is in the EU, so all extension usage telemetry was silently dropped since launch). Now sends to the EU endpoint via CORS; removed the now-unused US host permission. No user-visible change.

## v0.1.13 — 2026-06-02

- Sending account is now shown above the Send button ("Sending as: …"), so you always know which OutMass account a campaign goes out from — with a quick Change link to switch.
- Polish: in-app notifications now refresh instantly when you switch accounts, and the notification panel closes cleanly once everything is read/dismissed.

## v0.1.12 — 2026-06-02

- In-app notifications: a new bell in the sidebar header shows announcements and updates, with a highlighted banner for important news (like a gift or a new release). A matching card appears in the extension popup under Manage Subscription. Read and dismiss right where you work — no need to check email.

## v0.1.11 — 2026-06-01

- Bigger free plan: 250 emails/month (was 50). Starter raised to 2,500/month. Upload limits raised to match. Enjoy the extra room!

## v0.1.10 — 2026-05-30

- Clearer, localized error messages when a merge tag doesn't match your CSV columns (e.g. {{firstName}} casing/spacing). Now tells you exactly which column to add or which tag to fix, in your language.
- More reliable Resume: failed recipients are now distinguished as temporary (retried on Resume) vs permanent (skipped), so a partial campaign finishes correctly.
- internal: auto-expiring manual plan promos.

## v0.1.9 — 2026-05-05

- internal: comprehensive anonymous funnel + engagement telemetry (PostHog) covering install, sign-in, compose, CSV upload (incl. failures), test send, real send, upgrade intent, onboarding, AI writer, templates, scheduling, follow-ups, attachments, exports, and more. Per-user extension version tracking. account_deleted is sent anonymously (identity reset first). No user-visible behavior change. Privacy policy covers this disclosure.

---

## v0.1.8 — 2026-04-29

### OneDrive picker error messages
- When the signed-in Microsoft account has no OneDrive (some old
  Outlook.com accounts and work accounts without an SPO license),
  the picker now shows a clear "this account doesn't have OneDrive"
  message in your interface language, instead of a generic "Could
  not load" error.
- Other failure cases now include the underlying error code in the
  picker status line so it's easier to triage if anything goes wrong.

---

## v0.1.7 — 2026-04-29

### OneDrive picker rebuilt
- The OneDrive file picker has been replaced with a native, in-sidebar
  file browser. Previously it embedded Microsoft's hosted picker via
  iframe — which Microsoft serves with `X-Frame-Options: DENY` for
  personal accounts, producing a blank "onedrive.live.com refused to
  connect" page.
- The new picker shows your OneDrive contents directly: folders first,
  files after, both alphabetical. Click a folder to navigate; breadcrumb
  links jump back. Click a file to attach it. No external iframe, no
  third-party page load — just a clean list inside OutMass.

---

## v0.1.6 — 2026-04-29

### Smarter engagement metrics
- New **Engaged** number on the Reports detail view: distinct
  recipients who opened, clicked, OR replied. More honest than raw
  open rate, especially given how Outlook and Apple Mail Privacy
  Protection distort pixel-based opens.
- New **Replied** number, populated by a daily Inbox scan that
  detects genuine replies to your campaigns. Strongest engagement
  signal we have — counts only real replies from your recipients.
- Inline hint under each metric explains why it exists and why open
  rate alone can mislead.

### Resilience for partially-failed sends
- **Resume sending** button: if a campaign ends in `partial` status
  (some recipients failed to receive due to a transient network or
  rate-limit issue), the Reports detail view now shows a Resume
  button that retries only the still-pending recipients.
- Behind the scenes, every Microsoft Graph send is wrapped in a
  bounded retry (3 attempts, exponential backoff) for HTTP 5xx and
  network errors — so most transient hiccups never reach you.
- Explicit per-phase HTTP timeouts mean a single slow Microsoft
  Graph response can't hang the worker queue indefinitely.
- A daily background sweep detects campaigns stuck in `sending`
  status (worker crashed mid-loop, etc.) and recovers them
  automatically — either to `partial` (if some recipients went out)
  or back to `scheduled` for a clean retry.

---

## v0.1.5 — 2026-04-26

### Attachments via OneDrive sharing links
- New **Attachments** section in the compose area (below the body
  field). Click **+ Add OneDrive link**, choose a file from your own
  OneDrive, and a sharing link is automatically created and added
  to the email.
- Recipients see a clean clickable chip (e.g. "📎 brochure.pdf") that
  opens the file in OneDrive. The file lives in your OneDrive — we
  never download, store, or read it.
- Inbox-friendly by design: links don't trigger spam filters the way
  raw attachments do, and you can update the file later without
  re-sending the email.
- First-time use shows a one-off consent dialog explaining the
  OneDrive permission. The OneDrive permission is optional — if you
  never use this feature, it's never requested.

---

## v0.1.4 — 2026-04-24

### User lifecycle & legal posture
- **Uninstall landing page.** When you remove the extension, Chrome opens
  a friendly page reminding you that any paid subscription is separate
  from the extension and helping you cancel it. Optional feedback form
  tells us why you left.
- **Delete my account** (Account tab → Danger Zone). Self-service
  permanent removal of your OutMass account and all data, with a typed
  DELETE confirmation + irreversibility checkbox. Active subscriptions
  must be cancelled first. A GDPR-compliant anonymised audit record is
  retained for legal and fraud-prevention purposes.

### Behind the scenes (backend, affects every extension version)
- **Immutable audit log.** Every authorization, campaign creation,
  recipient upload, send trigger, and per-email Graph API dispatch is
  recorded with timestamp, IP (anonymised after 12 months), and
  SHA-256 hashes of content. Evidence chain for disputes and chargeback
  defence. Does not store raw recipient addresses.
- **Inactivity follow-up**. Paid users who stop logging in get up to
  three warm, non-threatening reminder emails (30, 60, 90 days) that
  their subscription is still active. Default-off feature flag.
- **Chargeback handling**. A disputed charge automatically cancels the
  subscription and alerts the operator for evidence review.
- **Schema hardening.** FK CASCADE chain across campaigns/contacts/
  tokens/templates/events so a single account-delete transaction
  cleans up every dependent row atomically.

---

## v0.1.3 — 2026-04-21

### Sign-in & authorization
- **Session expired banner** — when your OutMass sign-in times out, a
  one-click reconnect banner appears instead of an opaque "Invalid token"
  modal blocking Settings save / send / AI / templates / exports.
- **Multi-extension OAuth support** — the backend now routes each sign-in
  to the calling extension's chromiumapp.org subdomain via the OAuth
  `state` parameter. Dev builds and the store build can now sign in
  against the same backend without env-var swaps.

### Localization
- **Scheduled-send time, reports dates, and alerts** now use your
  selected interface language. Previously the datetime preview silently
  fell back to your OS locale because the code passed the translations
  dict instead of a BCP-47 tag to `toLocaleString`. Four call sites
  fixed, all routed through a single `getActiveLocale()` helper.
- **Reports tab date column** no longer hardcoded to Turkish.
- **Campaign-name auto-date suffix** (used when you leave the campaign
  name blank) now reflects the selected language.

### Campaigns & email
- **Unsubscribe footer label** in sent emails now respects your
  Settings → Unsubscribe text override. Previously scheduled sends,
  follow-ups, and async-queued emails all hardcoded the Turkish
  default regardless of what you typed.

### UX polish
- **Manage Subscription button** in the sidebar Account tab now shows a
  clear backend error message on failure instead of silently doing
  nothing. Both sidebar and popup now append the backend error detail
  to the "Portal could not open" alert so you can distinguish config
  issues ("Stripe not configured") from account-state issues ("No Stripe
  customer found").

### Backend-only (affects all extension versions deployed against this backend)
- **Token lifecycle hardening.** Scheduled campaigns and follow-ups with
  a dead Microsoft refresh_token now transition to `status='failed_auth'`
  instead of silently looping forever. Users receive a MailerSend
  reconnect email on the first flag transition (not on every retry). A
  daily 03:00 UTC beat task proactively refreshes every connected
  user's token so dead refresh_tokens surface *before* the next
  scheduled send window, not after users miss it.

---

## v0.1.2 — prepared but not shipped

Packaged in the previous session, superseded by v0.1.3.

- **Reconnect-to-Outlook banner** when your Microsoft authorization has
  expired, so scheduled sends no longer fail silently.
- **Test Send** no longer creates placeholder campaigns in Reports.
- **Scheduled sending** shows a proper upgrade prompt when the feature
  is locked to your current plan.
- **i18n named-placeholder substitution** fixed for non-English locales
  (`$EMAIL$`, `$N$`, etc.).
- **Settings placeholder text** cleaned up — removed developer's
  personal data from the Sender Information sample values.
- **Localized datetime** in the scheduled-send success alert.

All of the above are also included in v0.1.3.

---

## v0.1.1 — 2026-04-21 (shipped to Chrome Web Store)

- 10-language store listing descriptions (TR, DE, FR, ES, RU, AR, HI,
  ZH_CN, JA, EN).
- Stateless Test Send (no placeholder campaign row).
- Misc UX polish.

## v0.1.0 — initial public release

First Chrome Web Store publication.
