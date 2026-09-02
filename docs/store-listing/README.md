# Chrome / Edge Store Localized Listings

This directory contains the store listing content — **12 entries** in
`listings.json`: en, tr, de, fr, es, ru, ar, hi, zh_CN, zh_TW, ja, pt_BR.
(Count re-pinned 2026-08-15: this paragraph said "11" and described pt_BR as
"listing-only until the pt locales ship in 0.1.27" for ten days after 0.1.27
was published — the zh_TW entry was added the day after the sentence was
written and the sentence never moved.) There is deliberately no pt_PT entry
yet; whether the dashboards want one is an open question for Ali, tracked in
the backlog's store-listing entry.

## File: `listings.json`

Structure:
```json
{
  "en": { "title": "...", "summary": "...", "description": "..." },
  "tr": { ... },
  "de": { ... },
  "fr": { ... },
  "es": { ... },
  "ru": { ... },
  "ar": { ... },
  "hi": { ... },
  "zh_CN": { ... },
  "zh_TW": { ... },
  "ja": { ... },
  "pt_BR": { ... }
}
```

## Character limits (Chrome Web Store)

- **title**: max 45 characters
- **summary**: max 132 characters (hard limit)
- **description**: max 16,000 characters (we aim for ~2,000)

All content verified under limits (`node docs/store-listing/check-limits.js`).

## Language-count policy (claims discipline)

**The number to use is 13**, from 0.1.27 onward. Three different counts exist
and it matters which one the copy claims:

| Count | What it measures | 0.1.27 value |
|---|---|---|
| Locale folders | files in `extension/_locales/` | **14** |
| User-selectable translations | entries in Settings → Interface Language | **13** |
| Distinct languages (linguistic) | Chinese once, Portuguese once | **11** |

We claim **13** — the number a user can verify by opening the dropdown. Each of
the 13 is a separate translation with genuinely different text: `zh_CN` and
`zh_TW` are Simplified vs Taiwan-Traditional (different vocabulary, not a
character conversion), `pt_BR` and `pt_PT` likewise. Counting them once each
would undersell two translations, and "supported languages" universally means
locales in software localization.

Do NOT count the 14th folder: `zh` is a fallback duplicate of `zh_CN` for any
`zh-*` tag Chrome doesn't match (bare `zh`, zh-SG), and is never offered as a
choice.

Earlier this section said 10, then 11 — the count drifted across files and even
within one page (pricing.html said 11 and 10 in two places). `check-limits.js`
now fails if the entries disagree with each other.

**Timing (claims-follow-product):** the number may only go live together with
the release that makes it true. Chrome and Edge publish a listing edit and a
package submission together, so pasting the new count alongside the 0.1.27
upload is correct — pasting it while 0.1.26 is the live version is not.

## Search terms (Edge only)

`search_terms` in `listings.json` feeds **Edge Partner Center → Store listings
→ Details for \<language\> → Search terms**. Chrome Web Store has no such
field — it ranks on title/summary/description alone, so don't go looking for
it there.

Limits, from Microsoft's own docs (verified 2026-08-04): at most **7 terms**,
each **≤ 30 characters**, **≤ 21 words in total**, and terms must be relevant
to the extension (developer policy 1.1.4). They are never shown to users.

Two rules the checker enforces so they can't be argued away later:

- **No other company's brand.** Policy 2.2 requires metadata to be created by
  us or licensed from the rights holder; a competitor's trademark is neither,
  and the search volume isn't worth a takedown. "Outlook" and "Microsoft 365"
  are fine — we genuinely integrate with them.
- **Nothing we don't do** (SMTP, LinkedIn, WhatsApp, scraping).

Method that produced the current sets: a term repeating a word the listing
already contains is a wasted slot, because the store indexes the description
anyway. So each slot buys a token the entry does NOT have — and the terms are
what each market actually types, not translations of the English list
(German searches *Serienmail*/*Seriendruck*, Japanese 一斉送信, Turkish
*adres mektup birleştirme*, Taiwan *合併列印*).

## Copying text into the dashboards

**Do not copy out of `listings.json`.** It is JSON, so its line breaks are
stored as the two characters `\n` — pasting from it puts literal `\n` into the
dashboard instead of real line breaks.

Copy from `descriptions/<lang>.txt` instead. Each file has the three fields as
separate blocks with real line breaks and a character count:

```bash
node docs/store-listing/render.js
```

Those files are **generated** — edit `listings.json` and re-run the command.
`check-limits.js` fails if they fall out of sync, because they drifted once
before and spent three months advertising claims we had already removed
(timezone delivery, "Claude-powered", free = 50/mo, Starter = 2,000/mo).

Open them in an editor that reads UTF-8 (VS Code, or Notepad on Windows 11) so
the emoji and non-Latin text survive the copy.

## How to use

When submitting to the Chrome Web Store Developer Dashboard:

1. Go to Developer Dashboard → your extension → **Store listing**
2. For each language:
   - Click **Add localized listing**
   - Select the language code
   - Copy `title`, `summary`, `description` from listings.json
   - Add the SAME screenshots to each language (or localized screenshots if you
     want to translate the UI captures)
3. Save each localized listing
4. Submit for review

For **Edge (Partner Center)**: Edit → Store listings → one page per language;
paste the same content. NOTE: saving Edge listing changes creates a new
submission that goes through certification again (metadata-only reviews are
usually fast and do not touch the live package) — batch listing edits, don't
trickle them.

## Language codes (store mapping)

| Our key | Chrome Web Store | Edge Partner Center |
|---------|------------------|---------------------|
| en | English (US) / en_US | English (United States) |
| tr | Turkish / tr | Turkish |
| de | German / de | German |
| fr | French / fr | French |
| es | Spanish / es | Spanish |
| ru | Russian / ru | Russian |
| ar | Arabic / ar | Arabic |
| hi | Hindi / hi | Hindi |
| zh_CN | Chinese (Simplified) / zh_CN | Chinese (Simplified) |
| ja | Japanese / ja | Japanese |
| pt_BR | Portuguese (Brazil) / pt_BR | Portuguese (Brazil) |

## Updates

If pricing or features change, update **all entries** in `listings.json`, run
the limits check, and re-paste the affected localized listings in BOTH
dashboards. Store copy only claims what is LIVE (claims-follow-product rule).

## Two audience lines rescued from `softonic-en.txt`

That file was deleted on 2026-09-03: an unvalidated second paste source that
nothing regenerated, so it had drifted into carrying two claims we had already
corrected here. `check-limits.js` had started failing on its existence alone.

Four of its lines were not in `listings.json`. Two were the stale claims. The
other two are original copy that was never folded in, and they are kept here
rather than lost with the file:

> • Organisations emailing their own list — schools to parents, suppliers to
>   customers, associations to members
> • PR and agency teams reaching journalists or clients from their existing
>   mailbox

The first is the interesting one. Every audience bullet we ship describes cold
outreach — founders, SDRs, agencies running client campaigns. This one
describes the opposite case: a list that already expects to hear from you.
Schools, suppliers and associations have the sending problem without the
deliverability anxiety, and nothing in the current listing speaks to them.

Not adopted, because a BUILT FOR bullet is a claim about who we are for and
that is a positioning decision, not a copy edit. Worth a look next time the
listing is opened.
