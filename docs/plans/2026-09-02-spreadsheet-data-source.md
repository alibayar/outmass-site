# Google Sheets as a data source — pros, cons, and the cheaper comparison

2026-09-02. Question from Ali: should a campaign's recipient list be able to
come from a Google Sheet instead of an uploaded CSV?

Every claim below is marked **[repo]** (I read the file and quote the line),
**[inference]** (my reasoning from repo facts), or **[general]** (outside
knowledge, with what would settle it). Three lenses ran on this; two of their
load-bearing claims were refuted on cross-examination and one of mine was —
§6 lists them.

---

## 1. Google Sheets, straight

### The honest pros

**It deletes the encoding failure class.** A Sheet is read as JSON; there are
no bytes to guess a codepage for. That failure class has documented victims:
`extension/tests/csv-decode.test.js` opens with a zh-CN user whose GBK CSV was
rejected seven times before they churned, a user in Poland on a ru-locale
browser, and a paying customer in SA/AE rejected 32 times across three
sessions. **[repo]** And `2026-08-08-csv-encoding-confirmation-design.md` says
the Latin half of the problem is permanently unfixable by guessing — "the
information needed is not in the bytes." **[repo]**

**It removes a re-export step from every repeat campaign.** There is no saved
list in OutMass: `backend/schema.sql:35-37` keys `contacts` to
`campaign_id ... ON DELETE CASCADE`, with no lists or audiences table
anywhere. **[repo]** So a user running many campaigns re-uploads from scratch
each time — hrcargo ran 34 campaigns in 14 days, hrds 20 in 12
(`2026-08-31-post-microsoft-strategy.md` §2.5). **[repo]**

**The ingest seam is genuinely cheap.** `campaigns.py:87-89` already accepts
`contacts: list[dict]` as an alternative to `csv_string`, and `:660` already
branches on it. Rows from any producer can join the existing pipeline with no
API contract change. **[repo]**

**Competitive optics.** Mailmeteor and YAMM are Sheets-native; a prospect
comparing them will see the gap.

### The honest cons

**It is the one axis where every rival is strongest and we would arrive last.**
`2026-09-01-the-october-picture.md` §3 defines a wedge as something absent from
*both* rivals. Sheets is present in both and is their origin. **[repo]** Worse,
three live blog pages rest on the opposite argument:
`docs/blog/yamm-alternative-for-outlook.html:116` says a Google add-on "would
have to be a different product built against Microsoft's APIs. That's exactly
what OutMass is," and `:238` concedes the live sheet as a real YAMM advantage.
Building a worse copy of it turns "Outlook-native" into "a worse YAMM." **[repo]**

**A second identity provider, which the schema currently forbids.**
`schema.sql:85-92`: `user_tokens.user_id ... UNIQUE`, one refresh token, no
provider column. **[repo]** `users.requires_reauth` is a single boolean read by
`settings.py:93` and written by `ms_token.py:102-143`, which also sends a
reconnect email. **[repo]** A broken Google token would therefore tell a user
with a perfectly healthy mailbox to reconnect Outlook — unless a second flag,
a second banner, a second email and a second copy of the refresh/alert path
are built. That is a hand-run migration plus a permanent second thing that can
break at 3am.

**A second consent screen, at the product's measured leak.**
`2026-08-28-closing-the-consent-leak.md` §1: 39 people started a sign-in in
thirty days, 17 never got in — 44% lost at one screen. **[repo]** Adding a
Google-branded prompt to a product installed to use with Microsoft lands on
exactly that surface.

**Google's verification is a clock Ali does not control.** `spreadsheets.readonly`
is a sensitive scope requiring app verification; `drive.file` (per-file, via
the Picker) is non-sensitive; broad `drive`/`drive.readonly` are restricted
and pull in a third-party security assessment. **[general]** Google's own page
states an unverified app is capped at 100 new users after showing the
unverified-app screen. **[general]** *Settles it in ten minutes, free:* Google
Cloud Console → OAuth consent screen → Add scope, which labels each scope
Non-sensitive/Sensitive/Restricted. Review turnaround and any fee: I do not
know, and anyone who quotes a number for those is inventing it.

**The Picker cannot run in this extension.** `manifest.json:61-63` sets
`script-src 'self'`, and the certification notes state "No remote code is
loaded." **[repo]** So the file-chooser must be rebuilt server-side — roughly
what `onedrive.py` already cost for Microsoft.

**Wrong audience for the strongest pro.** The people the encoding chain hurt
are Excel users on Microsoft accounts; in the zh-CN case, behind a border
where Google does not resolve. **[inference]**

### Day cost, parts named

| Part | Days |
|---|---|
| Google Cloud project, OAuth client, consent-screen brand config | 0.5 |
| Backend second provider: migration + ledger entry + named-SELECT verify, token model, refresh, error classification, second reauth flag through `/settings` | 2 |
| Extension auth sibling: `launchWebAuthFlow` variant, in-flight dedup, settle page, error copy, test siblings | 1 |
| Drive/Sheet picker: backend list endpoint + sidebar UI + worksheet and header-row selection | 1.5 |
| Ingest | 0.25 |
| Copy: ~12-15 locale keys × 14 files (enforced by `locale-consistency`), privacy page, certification notes, three blog posts whose migration pitch is literally "export your Sheet as CSV" | 1 |
| Verification submission + the demo video that does not exist yet | 0.5 |
| **Total** | **6-8 days, plus an external wait** |

The cheap variant — paste a Sheet URL, `spreadsheets.readonly`, no Drive scope,
no picker — drops to about **4.5-5 days**, with the same verification wait and
the same permanent second-provider burden. **[inference; sizing anchored on the
OneDrive feature, which cost 12 locale keys × 14 files, a migration, a router,
a picker and two post-launch incident fixes.]**

---

## 2. The comparison that matters: Excel on OneDrive

**Did the "we already hold the scopes" claim survive cross-examination? Partly
— and the part that failed changes the answer.**

**What survived, verified line by line:**

- `backend/config.py:142-145` defines
  `MS_GRAPH_ONEDRIVE_SCOPES = "Files.Read.All Files.ReadWrite"`. **[repo]**
- `auth.py:729` takes `include_onedrive: bool = Query(False)`; `:802-803`
  appends the scopes at `/authorize`; `:937-948` re-appends them at token
  exchange from the `od` flag in state; `ms_token.py:348-349` re-appends them
  on every refresh when `has_onedrive_scope` is set. **[repo]**
- Graph is called server-side, so `manifest.json` needs no change: no new host
  permission, no re-approval prompt on existing installs. **[repo]**

So: **no new OAuth provider, no second identity store, no manifest change, no
new Chrome-store permission disclosure.** That half of the hypothesis holds.

**What did not survive — three corrections:**

1. **It is not consent-free.** The scopes are *deliberately* absent from
   `MS_GRAPH_SCOPES` (`config.py:104`) and `MS_GRAPH_FIRST_SIGNIN_SCOPES`
   (`config.py:119`); the comment at `:136-141` says why in so many words —
   keeping them off the first screen "preserves conversion." **[repo]** So
   every user who has never used OneDrive attachments gets OutMass's own
   explainer modal (`sidebar.html:574-590`) and then a Microsoft incremental
   consent screen. Cheaper than Google's — same provider, verified publisher,
   after the user is invested rather than before — but not free.

2. **The scopes existing is not the feature existing.** `onedrive.py` has
   exactly two endpoints: `GET /browse` (`:78`) and `POST /share-link`
   (`:270`). **There is no endpoint that reads a file's contents.** **[repo]**
   What the existing work buys is the picker UI, the incremental-consent
   plumbing and a hard-won error taxonomy (`_NO_DRIVE_MARKERS`, `:46-56`,
   exists because mapping a licence-403 to `needs_files_scope` produced
   "endless consent windows (seen live 2026-07-16)"). Not the capability.

3. **A live privacy promise forbids it.** `docs/privacy.html:94`: the Files
   scopes are used "*solely* to read the metadata of files you explicitly
   select... We never download, browse, modify, or read the contents of your
   OneDrive files." **[repo]** Reading a spreadsheet's cells breaks that
   sentence. Under this project's claims-follow-product rule the rewrite comes
   *before* the code. One English page — but non-negotiable. The consent modal
   string carries the same promise in 14 locale files. **[repo]**

**Two further constraints that shrink the benefit:**

- The Graph *workbook* API (live cell reads without downloading) is, to my
  knowledge, unsupported for consumer OneDrive and documented only for
  business accounts. **[general]** `2026-09-01-delivery-report-decision.md`
  calls consumer `outlook.live.com` about half the base. If that holds, half
  the users get "download the file and parse it," not a live sheet — which is
  a CSV upload with extra steps. *Settles it:* one call against a personal
  drive with a real token.
- Enumerating a SharePoint team library needs `Sites.Read.All`, which is
  **not** held — a genuinely new scope. **[general]** This matters because
  `2026-08-24-practitioner-channels.md` concludes "the dominant job is an
  organization emailing its own list," and org lists often live on a team site.

**Honest price: about 2-2.5 days** for the OneDrive version — against 6-8 for
Google — but it is a build, not a switch, and it carries a mandatory privacy
rewrite and a consent screen. **[inference]**

---

## 3. What the repo says about demand

**Nobody has asked for either. Not once.**

I grepped `docs/`, `backend/` and `extension/` for "google sheet". The only
hits are SEO copy in three blog posts and one unrelated ad-keyword string in
`2026-08-24-microsoft-qa-answers.md:217`. **[repo]** No support thread, no
backlog item, no feature request — for Sheets, for a live list, or even for
`.xlsx` upload.

What users actually asked for, all downstream of the list existing:

- Helene (2026-09-01): attach a follow-up to an already-running campaign; stop
  a campaign; body formatting. **[repo]**
- Tim: converted at a scheduling wall — refused 18:07:27, paid 18:09:35, the
  only feature-wall conversion in the product's history. **[repo]**
- bellmed: pacing; the daily send limit is literally called "the bellmed
  feature" in `backlog.md:732`. **[repo]**

Both recorded competitive losses are at the far end of the pipeline, not the
front: Alan left for SecureMailMerge over per-recipient attachments; Mary Bass
left for QuickMail at $49/mo over volume (`backlog.md:1101-1105`). **[repo]**
Neither is a data-source complaint. "Sheets wins deals" has no support anywhere
in this repo.

And the size distribution argues against both: **median send is 4 recipients**
over 90 days (`backlog.md:1082`), though 5 users fired 17 sends of 300+, max
1,876. **[repo]** A four-row list is a paste problem, not a sync problem — and
there is no paste box either.

---

## 4. Recommendation

**No to Google Sheets — not in September, and on this evidence not at all.
Also no to the OneDrive version this month. If a spreadsheet feature is ever
built, build the one that needs neither Google nor Microsoft: accept `.xlsx`
in the file input we already have.**

Why it beats the runner-up (OneDrive/Excel, ~2-2.5 days):

- It is the only member of the family whose value is proven by scars rather
  than assumed. Every documented ingestion casualty — zh-CN 7 rejections then
  churn, Poland `csv_upload_failed` at 09:53 then `oauth_failed` at 09:58 then
  gone, a paying customer rejected 32 times, mercedes fighting two rejections
  near midnight on their first campaign — was created by one step: **Excel →
  Save as CSV.** That is where text becomes bytes in an ambiguous codepage.
  An `.xlsx` is a zip of UTF-8 XML; reading it directly makes the class
  structurally impossible. **[repo + inference]**
- It costs **no OAuth, no consent screen, no host permission, no second
  provider, no store disclosure, and no privacy rewrite** — the only option in
  this family that touches none of them.
- Today an `.xlsx` cannot even be selected: `sidebar.html:122` is
  `accept=".csv"`, and the drop handler (`sidebar.js:736-741`) rejects it with
  a message telling the user to go back to Excel and re-save. **[repo]**
- Cost: **1-2 days.** Not a one-liner — `manifest.json:61-63` forbids remote
  code and the extension vendors no third-party library, so a parser must be
  bundled locally (SheetJS-class, or a minimal zip + `sharedStrings.xml`
  reader), plus the mandatory 14-locale pass. **[inference]**

**But it still does not jump the queue.** `2026-09-01-the-october-picture.md`
line 302: "Do 1-6 (about 4.5 days), then stop and look at the October return
rate before spending anything on 7-11." **[repo]** Item 1 (the `sent_count`
denominator) actively gets worse the moment follow-ups start working. Monthly
retention is 8%, longest-ever relationship 25 days. **[repo]** An `.xlsx`
reader belongs in the 7-11 band, behind Helene's follow-up attach — she
actually asked for hers.

---

## 5. The cheapest experiment — about one hour, no code

So the decision does not rest on this document being right.

**(a) PostHog, via `backend/scripts/ask.py`** (built for exactly this):
`sidebar.js:740` has been firing
`csv_upload_failed {error_code: "unsupported_file_type", ext: <ext>}` on every
rejected drop since that gate was instrumented, and nobody has ever queried it.
**[repo]** Pair it with `recipients_uploaded` (`sidebar.js:1406-1411`), which
carries `recipient_count` and `csv_encoding`. That gives, for free: how many
people have literally tried to hand OutMass a spreadsheet, the real upload
failure rate, the encoding mix, and the list-size distribution — i.e. whether
the pain is **format** or **source**.

**(b) One SQL statement on Supabase:** for each user with 3+ campaigns, the
email-set overlap between successive campaigns (`contacts` is indexed on
`campaign_id`, `schema.sql:147`). High overlap → people re-upload the same
list, and the missing feature is a **saved list inside OutMass**, which needs
no Google and no Microsoft. Low overlap → every campaign is a fresh list, and
no live source is wanted by anyone.

**What to refuse:** "ship a thin version and see if anyone uses it." With 37
people who have ever uploaded and 22-26 who have ever sent
(`2026-08-31-post-microsoft-strategy.md:127`), no in-product usage signal can
reach significance — the same n-argument that already killed the trial-at-wall
measurement.

---

## 6. What was refuted here

Findings that sounded right and did not survive:

1. **"The extension already requests Files.Read.All, so OneDrive needs no
   consent screen."** Refuted. The scopes are requested *only* behind
   `?include_onedrive=true` and are deliberately excluded from both default
   scope sets to protect first-sign-in conversion (`config.py:136-141`). Every
   user who has not used OneDrive attachments faces an incremental Microsoft
   screen plus our own modal. What is true is narrower: no new *provider*, no
   new *store permission*, no *manifest* change.

2. **"Everything a OneDrive spreadsheet source needs exists except the cell
   read."** Refuted. There is no content-read endpoint, no spreadsheet parser
   anywhere in the codebase (no SheetJS in the extension, no openpyxl in
   `requirements.txt`), and the sidebar's only ingestion path takes CSV *text*
   and posts `csv_string`. "Except the cell read" is the feature.

3. **"`privacy.html` is already false on the word 'browse'."** Refuted as
   stated. The sentence's object is "the contents of your OneDrive files," and
   `/browse` lists folder children, not file contents. Not a false claim — but
   the wording invites the misreading and is worth one line of cleanup.

4. **"Adding Google Sheets needs three things Google requires, all
   unavoidable."** Partly refuted. A `drive.file` + Picker design reads a
   user-chosen Sheet without a sensitive scope, so sensitive-scope verification
   is avoidable in principle — but the CSP blocks the Picker here, and the
   second provider, Cloud project and consent screen remain. Google is still
   strictly more expensive; the "verification is mandatory" framing was too
   strong. **[general]**

Refuted but worth closing anyway, cheaply, whether or not any of this is built:

- **`docs/store-listing/certification-notes.txt` does not disclose the Files
  scopes at all.** Its PERMISSIONS block lists Mail.Send, Mail.Read,
  storage/alarms/identity and the hosts — nothing about OneDrive, though the
  feature is advertised in all 14 store descriptions at line 27. **[repo]**
  One paragraph, owed regardless.
- **`privacy.html:94` will need rewriting before any OneDrive file read**, and
  the same promise is duplicated in the consent-modal string across 14 locale
  files. Worth knowing now so it is not discovered mid-build.

Where I could be wrong, and what would settle it: the Graph workbook API's
support for consumer OneDrive (one call with a real personal-account token),
Google's current scope classifications (the Cloud Console labels them), and
Google's verification turnaround (nothing in this repo or in my knowledge
gives a trustworthy number).
