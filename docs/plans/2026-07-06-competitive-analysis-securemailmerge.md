# Competitive Analysis — SecureMailMerge vs OutMass (2026-07-06)

Internal reference. `docs/plans/` is excluded from the public Jekyll site, so this
never ships to getoutmass.com. Written after losing a trial user (Alan) to
SecureMailMerge; facts below were read off the live SecureMailMerge site on
2026-07-06 — re-verify before quoting, competitor pages drift.

---

## TL;DR

- **We DO have a competitor** — the "we have no competitor" assumption was wrong.
- But it serves a **different center of gravity**. We overlap on "Outlook mail
  merge"; we diverge on everything around it.
- **SecureMailMerge = privacy-first personalized *document/mail distribution***
  (no tracking, data never leaves the device, per-recipient attachments, every
  Outlook platform).
- **OutMass = tracked *outbound campaign* engine** (GMass-for-Outlook: opens/
  clicks/replies, follow-ups, A/B, AI) — which SecureMailMerge **cannot do by
  design**.
- We didn't lose Alan at our own game; his job was **their** shape.

---

## The lost deal (Alan — post-mortem)

- **Who:** Alan (alan@sandstone.co.uk). Installed 0.1.18 on 2026-06-26, signed in
  fine, then hit the work-account host bug (0.1.18 sent M365 work accounts to the
  personal `outlook.live.com`), never reached compose, churned. His support email
  sat in **our junk folder** — reply latency, not product, sealed it: *"having not
  heard back from you, we have already chosen an alternative."*
- **Buyer persona surprise:** Alan is an **agency/consultant** evaluating tools
  **for a client** — he was using his own email only for trials. Buyer ≠ end user.
  Agencies are a potential channel (one agency → many client deployments) but also
  carry specific needs. N=1, noted.
- **Why SecureMailMerge won (his words):** the client needs **an individual PDF
  attached per recipient**, and **does not want to use OneDrive** — i.e. a real
  attachment, not a cloud link. OutMass structurally can't do this today.

---

## Feature comparison (current, 2026-07-06)

| | **OutMass** | **SecureMailMerge** |
|---|---|---|
| **Type / reach** | Chrome/Edge extension — **Outlook Web only** | **Office Add-in** — new Outlook, classic desktop, web, **Mac** |
| **Send mechanism** | Graph API, **server-side** async/paced worker | From user's M365 account; data processed **on-device**, only finished message handed to M365 |
| **Data/privacy** | Campaign data processed + stored on our servers | **"Data never leaves your computer, never sent to our server"** — core positioning |
| **Per-recipient attachments** | ❌ OneDrive **link**, campaign-wide, body footer | ✅ **Individual file per recipient** (filename column + upload files) |
| **Open / click tracking** | ✅ | ❌ *"Zero tracking. No pixels, no click logging, ever."* |
| **Reply detection** | ✅ | ❌ |
| **Follow-up sequences** | ✅ | ❌ |
| **A/B testing** | ✅ | ❌ |
| **AI writing** | ✅ | ❌ |
| **Scheduling / pacing** | ✅ | ✅ (start day, hours, delays) |
| **Unsubscribe handling** | ✅ | ❌ |
| **Price** | Free 250/mo · Starter $9/2.5k · Pro $19/10k | Free for personal (with footer) · Commercial **~$10–15 / user**/mo |
| **Send limit** | Plan quota | None from them; bounded by M365's 10k/24h |

Sources: securemailmerge.com (home, /pricing, /comparison, /faq) and the Microsoft
Marketplace listing, read 2026-07-06.

---

## Strategic read — two centers of gravity

Both do "personalized bulk email from Outlook," so we **compete in that overlap**.
But the products optimize for **opposite ends**:

- **SecureMailMerge** — for someone who wants to send **each person their own
  personalized email/document, privately, without tracking**. Classic "mail merge"
  in the Office/Word lineage, modernized: HR payslips, finance invoices, school
  certificates, personalized letters. **Alan's client was exactly this.**
- **OutMass** — for someone running an **outbound campaign** who needs to know
  **who opened / who didn't reply / auto-follow-up / optimize**. Sales, marketing,
  cold outreach, newsletters. This is the GMass job, and SecureMailMerge **cannot**
  do it (zero tracking, no follow-ups — by design and as a selling point).

So the buyer self-selects: *personalized-document + privacy + no tracking* → them;
*tracked outreach + follow-ups + optimization* → us.

---

## Lessons / implications

1. **Don't try to out-privacy them.** "Most private / data-never-leaves-device" is
   their flag, and it's the *opposite* of our architecture (our whole value —
   tracking, follow-ups, async sending — needs server-side processing). Own the
   **other** end instead: *"the outreach/campaign engine for Outlook."* Their
   product is empty there.
2. **Their structural edge is platform reach.** As an Office Add-in they run in
   desktop + Mac + web; we're **web only**. Most Outlook users live in the desktop
   app and never see us. This is a real distribution ceiling — see "Office Add-in
   option" below.
3. **They out-market us.** They run their own comparison/SEO pages ("Best Mail
   Merge Tools for Outlook Compared"). That's precisely the comparison-page / GEO
   play we should be doing — reinforces the existing marketing backlog.
4. **Attachments are their home turf** (privacy + per-recipient together). Chase it
   only on repeat demand; even then we'd be entering their strength, not ours.

---

## Attachments — conscious trade-off (not a forever-no)

We deliberately avoid real attachments today. The reasoning is sound, especially on
**security**: with OneDrive links the file bytes never touch our servers; handling
real attachments makes us a **custodian/conduit of sensitive files** (bigger breach
blast radius, more compliance surface, an abuse/malware vector, and it muddies the
clean *"we never store your email content"* promise). **Cost** is real but minor
(mainly engineering complexity + Graph throttling on large sends), not a big money
line.

**If repeat demand appears, a "secure-v1" is buildable:**
- **Size:** ~**3 MB/file** goes in a single Graph `sendMail` request (stream-through,
  no storage — the clean path). 3–25 MB needs a chunked upload session (more moving
  parts). 25 MB is the typical Outlook mailbox message ceiling anyway.
- **Per-recipient UX (industry-standard shape):** a **filename column** in the CSV
  + a **bulk ZIP/folder upload**; match filename → recipient; attach each recipient
  their own file. (This is how SecureMailMerge and GMass do it.)
- **The one honest architectural wrinkle:** "never store" is cleanest for **immediate
  (browser-open) sends** — bytes go straight through. Our **async/paced/scheduled**
  sending (a core strength — sends continue after the tab closes) means the server
  must **hold the files during the send window** → **transient encrypted custody +
  delete-after-send**, not literally zero-touch. Two knobs to accept up front: size
  cap (~3 MB) and immediate=zero-storage / scheduled=transient-custody.
- **Re-open trigger:** this need recurs ~2–3 more times.

---

## Strategic option — an OutMass Office Add-in

The single highest-**ceiling** move, because it directly neutralizes their
structural advantage (reach into desktop + Mac Outlook = the majority of Outlook
users). Assessment:

**Feasible? Yes.** An Outlook Add-in is a web app we host, loaded into Outlook via
a manifest, using the **Office.js** API and a **task pane** (a side panel — maps
directly onto our existing sidebar). **One** add-in runs across new Outlook (Win),
classic desktop (Win), Mac, and web.
- **Reusable:** the backend (Graph send, tracking, quota, billing, DB), most of the
  sidebar UI markup/CSS, and the campaign/CSV/merge logic. Our async server-side
  send model is unaffected — the add-in is just a different front-end calling the
  same backend.
- **Rewrite:** auth (`chrome.identity.launchWebAuthFlow` → Office **SSO** /
  OAuth), the Outlook-interaction layer (content-script DOM injection → Office.js;
  lighter for us than a typical add-in since we mostly generate+send via Graph
  rather than manipulate the live compose window), packaging (MV3 manifest → Office
  add-in manifest), and distribution. Plus **multi-host QA** (API requirement sets
  differ across new/classic/Mac/web).
- **Magnitude:** a real project — weeks of focused work + a permanent second
  platform to maintain. High backend leverage, but not a weekend port.

**Cost? Essentially zero in money; real in time.**
- **Microsoft fees:** add-ins are **free-to-download** (you can't charge through
  them and don't need to). We keep our **own Stripe billing**, so **no Microsoft
  revenue share**. The Partner Center marketplace account is free and we **likely
  already have it** (from the publisher verification). Hosting is negligible
  incremental (we already run a domain/Railway). *Confirm current Partner Center
  terms at submission.*
- **Real cost:** engineering time (the rewrite) + ongoing multi-platform QA +
  AppSource validation is **stricter/slower** than the Chrome Web Store (process
  time, not money). Note you can also distribute **without** AppSource — direct
  sideload or M365 admin-center deployment for orgs — bypassing that validation for
  direct/enterprise use.

**Timing — the honest call: right direction, wrong moment.** We're **pre-PMF**
(1 retained user — Faisal). Building a whole second platform before the product is
proven to retain on **one** is the classic "scale before PMF" trap. Reach is a
**multiplier** — apply it *after* the product converts/retains, not before.
**Sequence:** prove retention on the web extension (cheap to iterate) → **then**
port to an Add-in to scale reach. Logged as the **#1 post-PMF strategic option.**

---

## Sources
- https://www.securemailmerge.com/ · /pricing/ · /comparison/ · /faq/
- https://marketplace.microsoft.com/en-us/product/office/wa200005174
- https://learn.microsoft.com/en-us/office/dev/add-ins/publish/publish-office-add-ins-to-appsource
- https://learn.microsoft.com/en-us/partner-center/marketplace-offers/monetize-addins-through-microsoft-commercial-marketplace
