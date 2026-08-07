# CSV encoding confirmation — design

Status: **proposed, not approved.** Blocks on Ali (new user-visible strings in
14 locales, and a new step in the upload flow).

Companion: `handoff-2026-08-07.md`. Internal — `docs/plans/` never ships.

---

## The problem, stated precisely

`decodeCsvBuffer` in 0.1.28 will read a CSV in UTF-8, GBK, Big5, and the
single-script codepages the user's own languages name (Cyrillic, Arabic,
Hebrew, Greek, Thai). It will **not** read windows-1250, 1252, 1254, 1257 or
1258 — the Latin family — and that is deliberate, not an omission:

- Those tables have no invalid byte sequences. Every byte maps to some Latin
  letter, so a wrong one cannot fail; it returns plausible-looking mojibake.
- A real contact list is only 4-12% non-ASCII, because the email column
  dilutes it, so no volume rule separates a Turkish list from a diluted
  Chinese one.
- Measured: the first draft turned `Ayşe Yılmaz` into `Ayþe Yýlmaz` and
  `Małgorzata` into `Ma³gorzata`, accepted both as clean successes, and would
  have put them in a `{{name}}` merge field sent to a real recipient.

So the affected users — Turkish, Polish, Czech, Hungarian, Baltic,
Vietnamese, and anyone Western European whose file carries a stray accented
name or a Word smart quote — still get `csvErrEncoding` and are told to
re-save as "CSV UTF-8".

**We cannot guess our way out of this.** The information needed is not in the
bytes. It is in the user's head.

## Why this matters enough to build

Two confirmed losses came from the encoding chain being too narrow
(2026-08-07 and the 32 rejections a paying customer worked around without
telling us). Turkish is one of our 14 shipped locales and Ali's own market.
The "re-save as UTF-8" instruction is correct but it asks a non-technical
user to find a save-as dropdown option they have never noticed.

## Design

One new step, shown **only** when every automatic candidate has failed —
i.e. exactly where 0.1.28 shows an alert and stops.

```
┌─────────────────────────────────────────────────────┐
│  We could not tell how this file is written         │
│                                                     │
│  Pick the language of the names in it, and we will  │
│  read it that way. Check the preview before you     │
│  send — if the names look wrong, pick again.        │
│                                                     │
│  [ Western European (English, German, French…) ▾ ]  │
│                                                     │
│  Preview                                            │
│    name              email                          │
│    Ayşe Yılmaz       ayse@example.com               │
│    Çağrı Öztürk      cagri@example.com              │
│                                                     │
│  [ Use this ]     [ Cancel ]                        │
│                                                     │
│  Or re-save the file in Excel as "CSV UTF-8" and    │
│  upload it again — then this never comes up.        │
└─────────────────────────────────────────────────────┘
```

**The preview is the whole design.** It is not decoration: it converts an
unanswerable question ("which codepage is this?") into one anybody can
answer by looking ("do these names look right?"). The dropdown re-decodes
live, so the user sees `Ayþe` become `Ayşe` when they pick Turkish.

### Options in the dropdown

Ordered by the user's own languages first, then the rest:

| Label (en) | Encoding |
|---|---|
| Western European (English, German, French, Spanish…) | windows-1252 |
| Central European (Polish, Czech, Hungarian…) | windows-1250 |
| Turkish | windows-1254 |
| Baltic (Lithuanian, Latvian, Estonian) | windows-1257 |
| Vietnamese | windows-1258 |
| Cyrillic (Russian, Ukrainian…) | windows-1251 |
| Greek | windows-1253 |
| Hebrew | windows-1255 |
| Arabic | windows-1256 |
| Thai | windows-874 |
| Chinese (Simplified) | gb18030 |
| Chinese (Traditional) | big5 |
| Japanese | shift_jis |
| Korean | euc-kr |

The script ones are included even though the decoder tries them
automatically: if the automatic attempt was ambiguous (two of the user's
scripts fitted, so neither was used) this is where the user resolves it.

### What must NOT happen

- No default selection that is silently applied. The user picks, or the
  upload does not proceed. A pre-selected dropdown with a "Use this" button
  is a guess wearing a costume.
- Nothing is remembered across uploads in the first version. A remembered
  choice applied to a different file is the same silent-corruption bug
  through a slower door. Revisit only with evidence that people re-upload in
  the same encoding repeatedly.
- The automatic chain is not weakened. This screen appears only after it has
  returned null.

## Work

**Strings** — 7 new keys × 14 locales, plus 14 dropdown labels × 14 locales.
That is the bulk of the effort and the part that must not be machine-dumped:
`locale-consistency` enforces key parity, and the 0.1.26 review caught a
script-mixing defect a parity test structurally cannot see.

| Key | English |
|---|---|
| `csvEncodingPickTitle` | We could not tell how this file is written |
| `csvEncodingPickBody` | Pick the language of the names in it… |
| `csvEncodingPickPreview` | Preview |
| `csvEncodingPickUse` | Use this |
| `csvEncodingPickCancel` | Cancel |
| `csvEncodingPickHint` | Or re-save the file in Excel as "CSV UTF-8"… |
| `csvEncodingPickEmpty` | That reading did not produce a usable table |

**Code** — `decodeCsvBuffer` already returns `null` at exactly the right
point; `handleCSV`'s `if (!decoded)` branch becomes the trigger instead of an
`alert`. The picker needs the raw ArrayBuffer kept alive (it currently dies
with the FileReader callback) and a `decodeCsvBufferAs(buf, encoding)` that
skips every heuristic and just decodes.

**Telemetry** — extend the existing `csv_upload_failed` /
`recipients_uploaded` pair: `csv_encoding_prompted` with the candidate list
that failed, and `csv_encoding_chosen` with the encoding picked. That tells
us within weeks which codepages actually matter, and whether the automatic
chain should learn any of them. No file content, no names.

**Tests** — `csv-decode` gains `decodeCsvBufferAs` coverage per encoding;
`no-silent-dead-ends` gains an assertion that the `!decoded` branch reaches
the picker and not a dead end; `locale-consistency` and `i18n-usage` cover
the new keys automatically.

## Estimate and sequencing

Roughly a day: half of it the translations. It does **not** belong in 0.1.28
— that release is cut and the decoder in it is already a strict improvement
on 0.1.27 for the script languages. Ship it in 0.1.29, after the
`csv_encoding_prompted` counter has told us how often the dead end is
actually hit.

**Ali's call before any of it:** the dropdown adds a step to the upload flow
for the failure case only, and 98 new locale strings. Worth it if the dead
end is common; the counter is the cheap way to find out first, and it can
ship in 0.1.28 on its own.
