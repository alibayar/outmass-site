# Reaching the people who actually send — channel plan (2026-08-24)

Every channel we have worked so far (AlternativeTo, SaaSHub, SoftwareSuggest,
Capterra/GetApp/Software Advice, SourceForge, Softonic, G2) targets someone
*researching software*. The people who actually run campaigns find us a
different way: they type their problem into a search box. This plan covers
that second path. Five research agents verified everything below live in
August 2026; costs and gates are quoted from the channels' own pages.

## 0. The finding that reframes everything

**Microsoft is shipping native mail merge into Outlook on the web.**
"Outlook Mail Merge (Advanced)" sits on the Microsoft 365 roadmap with
preview/rollout targeted **June–July 2026**, for Outlook on the web and new
Outlook for Windows; Microsoft's own guidance tells admins to keep the classic
Word workflow for business-critical sends. Rollout is staged and has already
slipped more than once.

What it reportedly does: per-recipient personalized messages, each with its
own To field, without Word.

What it reportedly does **not** do (secondary sources — YNOT Mail, AdminDroid,
Windows Forum — **not** Microsoft's own documentation): open/click tracking,
reply detection, automated follow-ups, scheduling, rate limiting, unsubscribe
handling, bounce/complaint processing, campaign reporting. It also stays bound
by ordinary mailbox sending limits.

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
