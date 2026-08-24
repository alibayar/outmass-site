# Reaching the people who actually send — channel plan (2026-08-24)

Every channel we have worked so far (AlternativeTo, SaaSHub, SoftwareSuggest,
Capterra/GetApp/Software Advice, SourceForge, Softonic, G2) targets someone
*researching software*. The people who actually run campaigns find us a
different way: they type their problem into a search box. This plan covers
that second path. Five research agents verified everything below live in
August 2026; costs and gates are quoted from the channels' own pages.

## 0. The finding that reframes everything

**Microsoft is shipping native mail merge into Outlook on the web.**
Verified against Microsoft's own sources on 2026-08-24 (roadmap item **423047**,
fetched from microsoft.com's release-communications feed):

- Official name: "Outlook: Mail Merge (Advanced) on Outlook on the Web and new
  Outlook for Windows". Status **In development**, **preview August 2026**,
  **GA September 2026**, entry last modified 29 May 2026.
- Microsoft's own new-vs-classic feature comparison page lists mail merge as
  *Available* in classic Outlook and *Partially Available* in new Outlook, with
  that row linking to roadmap 423047.
- Word-driven mail merge **does not work in new Outlook at all** — it needs
  MAPI, which only classic Outlook exposes; a Microsoft Q&A moderator says so
  and gives "turn off Try the new Outlook" as the workaround. This is a live
  pain: people whose merges broke after the upgrade are looking for an answer
  right now.
- What ships today is Mail Merge (Basic): each recipient gets their own copy,
  no per-recipient personalization, recipients entered by hand.
- Exchange Online limits are unchanged and apply regardless: 10,000 recipients
  per rolling 24h, up to 1,000 per message, 30 messages/minute, plus a
  tenant-wide external-recipient cap. Microsoft's own words on that page:
  customers who need to send bulk commercial email "should use third-party
  providers that specialize in these services."

**Correction to the first draft of this doc:** secondary sources said pilot
June–July 2026 and listed specific missing features. The primary roadmap says
preview August / GA September, and Microsoft says **nothing at all** about
tracking, reply detection, follow-ups, scheduling, pacing, unsubscribe handling
or reporting for the Advanced feature — silence, not denial. Data sources and
licence coverage are likewise unpublished. We write "Microsoft has not said",
never "it cannot do".

Two consequences:

1. **Positioning.** "Mail merge in Outlook" is on its way to being a free
   Microsoft feature, so it cannot stay our headline claim. What survives is
   everything *after* Send: who opened, who clicked, who replied, follow-ups
   that stop on reply, pacing that protects the sender, campaign reports.
   Our own store/site copy currently leads with mail merge and targets
   "founders and SDRs doing outbound" — which is also wrong against measured
   usage (see §1). Rewriting user-visible copy needs Ali's onay; it belongs
   in the 0.2.3 store-listing review pass.
2. **Content.** The confusion is happening right now — Microsoft Q&A threads
   ask "does New Outlook support mail merge?", and a YouTube video literally
   titled "Why New Outlook's Start Mail Merge Doesn't Work" is collecting the
   traffic. Answering that question honestly is both the highest-intent
   content we can write and the truthful sales pitch.

**Before any of this reaches customer-facing copy, verify the capability list
against Microsoft's own documentation.** Claims discipline applies to claims
about competitors too, and a roadmap item is not a shipped feature.

## 1. Who actually sends (measured, 120 days, by recipients)

| Sender | Recipients | Shape of the job |
|---|---|---|
| samaed.com | 5,599 | education org → students/parents |
| bellmed.com | 2,816 | medical supply → customers |
| personal Outlook accounts | 607 / 36 sends | solo operators, consultants |
| skylineprp.com | 519 | PR agency → journalists |
| hrds.com | 375 | staffing → candidates |
| overdeliverinc.com | 260 | B2B services |
| mercedesscientific.com | 83 | scientific supply → customers |

The dominant job is **an organization emailing its own list**, not cold
outbound prospecting. Channel choice follows from that.

## 2. Do first — free, one-shot, keeps working

1. **Blog: "Does new Outlook have mail merge?"** Update
   `docs/blog/mail-merge-in-outlook.html` (currently classic Word+Excel only)
   and/or split off a dedicated post covering what native Advanced Mail Merge
   does and doesn't do. Competing pages: AdminDroid's June-2025 post
   (pre-Advanced), geeky-gadgets' 2025 guide. ~4-6 hrs, evergreen.
2. **Microsoft Q&A** (`learn.microsoft.com/answers`, Outlook tags). The ICP
   asks there under their real names, and the threads themselves rank in
   Google. Live examples found: a user needing 1,000 personalized emails
   against a 150/day cap; two threads on emailing whole parent lists from a
   school. Disclosed, genuinely useful answers only — the tool named when it
   is the honest answer. ~2-3 hrs/month.
3. **Blog: "Email your whole list from Outlook — no Mailchimp."** Aimed at
   the school-office / PR / HR coordinator, i.e. our real #1 segment.
   Existing top results steer readers toward buying an ESP instead.
4. **YouTube gap video.** The "new Outlook mail merge doesn't work" niche is
   active and nobody shows the Outlook-Web fix. One screen recording, ~3-5 hrs.
   Also fills the empty video slots on Edge, G2 DM (+2% listing score) and the
   site.
5. **Chrome Web Store Featured badge nomination.** $0, one-shot, evergreen;
   self-serve nomination path documented at developer.chrome.com. Audit the
   listing against their best-practices checklist first.

## 3. Worth a shot — free but needs a relationship or luck

- **SchoolCEO (Apptegy)** — free quarterly magazine + newsletter, 25,000+ K-12
  superintendents and comms directors. Best played by co-writing with our
  education customer rather than pitching the product cold.
  `apptegy.com/schoolceo/submissions/`
- **Spin Sucks Community** (free PR Slack) and **PRNEWS Slack** (free) — where
  PR practitioners compare outreach tooling. Contribute first.
- **M365 & Power Platform community call demo slot** — Microsoft's own
  practitioner call, free 10-15 min demo request via `aka.ms/m365pnp/request/demo`.
  Confirmed running through July 2026.
- **eSchoolNews / K-12 Dive tips**, **School Marketing Insider** organic
  resource mention (their paid slot is $300 — ask for the free mention).
- **Roundup pitches**: "best PR/agency email tools" lists that already rank.

## 4. Paid, small, only as a deliberate test

- **Grow Your Agency Slack** — $35 one-time lifetime, 1,600+ agency owners,
  explicit "contribute first, pitch when invited" rule. Cheapest paid option
  with a real ICP match.
- **RecTech Media** $195 one-time recorded demo (recruiting audience) and
  **M365 Show** $99 episode sponsorship — both above our $50/channel ceiling.
  Park until MRR justifies a test.

## 5. Verified dead ends (do not spend time)

- **r/recruiting, r/humanresources** — live rules pages ban vendor
  self-promotion outright.
- **Microsoft AppSource / commercial marketplace** — needs an Office Add-in,
  not a browser extension. A thin add-in wrapper would be the price of entry:
  a product decision, not a marketing one.
- **TechSoup** — negotiated enterprise donation deals only, no self-serve path.
- **EDUCAUSE / NSPRA / CoSN / CASE / NAIS, PRSA chapters, ASAE marketplaces,
  ATS marketplaces (Bullhorn)** — all gate visibility behind booth-scale
  sponsorship ($650–$10,000) or a full API integration and security review.
- **Microsoft Partner Network designations** — free to join, but every
  visibility benefit is sales-assisted and scale-gated.
- **Recruiting Brainfood** paid slots — sponsor-per-issue economics
  ($500–3,000). A free resource mention is the only realistic path.

## Search Console baseline (2026-08-24)

Recorded so the content channel can be measured rather than believed.

**A four-month-old bug, found by the blog post's review and fixed the same
day.** `docs/sitemap.xml` declared a namespace that does not exist
(`sitemap-protocols.com` instead of `sitemaps.org`). Search Console had been
reporting "Hatalı ad alanı — Satır 2, Etiket: urlset" on every read since the
sitemap was submitted on 29 April. Google tolerated it and still discovered 13
pages, but the file was flagged for four months. After the fix and a
re-submit: **status Başarılı, 15 pages, read 24 August**.

**Indexing state on the day:** 9 pages indexed, 4 not.

| URL | Reason | Last crawl |
|---|---|---|
| blog/mail-merge-in-outlook.html | discovered, not indexed | never |
| blog/mailmeteor-alternative-for-outlook.html | discovered, not indexed | never |
| blog/yamm-alternative-for-outlook.html | discovered, not indexed | never |
| blog/outlook-mail-merge-limit.html | crawled, not indexed | 29 Apr 2026 |

**The diagnosis is authority, not content.** Measured before guessing: every
one of those pages is 2,278–2,536 words, and the page Google crawled and
rejected is the *most* internally linked on the site (six inbound links). So
"write more" and "link more" are both answered by the data. A young domain
gets discovered and deprioritised; the cure is external signal and time.

Which is what this week's directory work actually was. AlternativeTo, SaaSHub,
SoftwareSuggest and Capterra all went live in the eight days to 24 August, with
GetApp, Software Advice, SourceForge and Softonic still in review — real links
from established, frequently-crawled sites. Their effect arrives on a lag of
weeks, and the indexing gap should close along the same curve.

**Actions taken today:** sitemap namespace fixed and re-submitted; the three
posts edited today given a truthful fresh `lastmod`; indexing requested for
both new posts and all four unindexed URLs.

**Check back around 2026-09-07:** are those four indexed? Has the Performance
tab moved off zero impressions? Those two answers, not a feeling about the
writing, tell us whether the content channel is working.
