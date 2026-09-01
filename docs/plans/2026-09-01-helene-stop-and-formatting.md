# Helene — no stop button, and a campaign she could not see (2026-09-01)

Live incident. Campaign stopped by Ali at ~08:10 UTC.

## What happened

`Helene@circularworkplaces.com`, Starter with a comped Pro grant. Campaign
`17a969ec-58d2-4c46-beee-825d344f6e05`, 66 recipients, created 28 August.

| time (UTC) | |
|---|---|
| 07:34:57 – 07:35:07 | **5 of 66 sent** |
| 07:48:11 | opens the sidebar |
| 07:48:13 | **`reports_load_failed`**, `error_code: "Not authenticated. Please login."` |
| 07:48:17 | clicks sign in |
| ~07:50 | writes to us |
| ~08:10 | Ali sets the campaign `cancelled` + `archived` |

Final state: **5 sent, 61 pending.**

Her words:

> "I cannot seem to edit a campaign, it seems the formating which was sent for
> my CBRE campaign did not work and everything sent as a block even if the
> preview looked fine. Now I see nowhere to edit the campaign or even stop it!
> Please could you let me know how to do that or I will have to close the
> account to stop it."

## Three separate faults, and she is right about the worst one

**1. There is no way to stop a campaign. At all.**

Verified: no cancel endpoint in `routers/campaigns.py` (only `cancel_followup`),
and no stop or cancel control in `sidebar.html`. The Reports tab offers Active
and Archived sub-tabs and a Resume button for partial campaigns — nothing that
halts one.

So "I will have to close the account to stop it" was not an exaggeration.
Revoking OAuth was genuinely her only lever. A paying customer discovered that
mid-send.

The stop that worked was a manual `UPDATE`: `status='cancelled', archived=true`.
`get_due_scheduled_campaigns` selects `status='scheduled'` (`campaign.py:96`)
and `archived=false` is already the auto-resume filter, so the two together
close both doors.

**2. Reports did not load, at the exact moment she needed it.**

`reports_load_failed` carried `"Not authenticated. Please login."` — her JWT had
expired. Even if a stop button existed, she could not have reached it. The
session expiry is ordinary; the timing is what made it an emergency.

**3. The formatting broke — cause not yet confirmed.**

Both `_text_to_html` (`campaigns.py:1840`) and the panel's `textToHtml`
(`sidebar.js:1727`) use the identical rule: if the body matches
`/<[a-z!/][^>]*>/i`, pass it through untouched; otherwise escape it and convert
`\n\n` to paragraphs and `\n` to `<br>`.

Because the rules are identical, a body containing any tag would collapse in
BOTH the preview and the email — which contradicts "the preview looked fine".
So the divergence is somewhere else, and I have not found it yet. Do not tell
her a cause until it is confirmed.

**Query to confirm it:**

```sql
SELECT left(body, 600) AS gövde_baslangici,
       body ~ '<[a-zA-Z!/][^>]*>' AS html_tag_var_mi,
       length(body) AS uzunluk,
       (length(body) - length(replace(body, chr(10), ''))) AS satir_sonu_sayisi
FROM campaigns
WHERE id = '17a969ec-58d2-4c46-beee-825d344f6e05';
```

If `html_tag_var_mi` is true, her body carried markup and both sides should
have passed it through — so the preview must be rendering it in a container
that treats newlines differently from an email client. If false, the conversion
ran and something downstream flattened it.

## Reply — send now, do not wait for fault 3

Subject: **Your campaign is stopped — 5 of 66 went out**

> Hi Helene,
>
> Your CBRE campaign is stopped. It had reached 5 of the 66 recipients before
> I halted it; the remaining 61 have not been contacted and will not be.
>
> You were right that there was nowhere to stop it, and I am sorry. OutMass
> has no stop control — not hidden, not somewhere you missed. It does not
> exist, and finding that out mid-send is exactly the wrong moment. I have
> stopped this one by hand from our side, and a proper stop button is the
> next thing we build.
>
> Two other things went wrong for you this morning, and you should know both.
> The Reports tab failed to open when you went looking, because your session
> had expired — so even the little you could have done was out of reach.
> Signing in again fixes that one.
>
> And the formatting: I can see that your message went out differently from
> the preview, and I am still working out why. I would rather tell you the
> real cause than a quick guess, so give me a few hours on that one. If you
> can send me the version you pasted into the editor, it will be faster.
>
> Nothing else of yours is scheduled, so there is no second campaign to worry
> about. When you want to send the remaining 61, we can set it up again
> together once I know the formatting is fixed — nothing will go out before
> you say so.
>
> Ali

Send notes: BCC `outmassapp@outlook.com`. No call offered — async only.

## The fix that has to follow

A stop control is now the most clearly earned item in the backlog. It has a
customer, a date, and a threat to close the account attached to it. Minimum
shape: a button on a `scheduled` or `sending` campaign in Reports that sets
`cancelled` + `archived`, with a confirmation naming how many have already
gone out — because that number is the only thing the user cannot undo.

---

## Follow-up email — cause confirmed, fix deployed

Sent after the first one. The first said "give me a few hours"; this is that
answer.

Confirmed cause: `scheduled_worker` and `followup_worker` never called the
plain-text → HTML conversion that `routers/campaigns.py` did, so a scheduled
campaign's newlines collapsed inside a `contentType: HTML` message while the
panel's preview — which converts — looked correct. Her template contained no
markup and none of her 66 rows did either, which rules out the alternatives.
Fixed and deployed in `0252d0b`.

Subject: **What happened to your formatting — found and fixed**

> Hi Helene,
>
> I said I would rather find the real cause than guess. I have it, and it was
> ours.
>
> OutMass sends through Outlook as HTML, where a plain line break means
> nothing unless we convert it first. We do that when you press Send — and we
> were not doing it when a campaign was **scheduled**. Your campaign was
> scheduled, so your paragraphs were converted for the preview and not for the
> actual send. That is why the two looked different, and why nothing you did
> could have prevented it. It was not your formatting, your pasting, or your
> plan.
>
> This was not specific to you: any scheduled campaign was affected. It is
> fixed as of this morning, and there is now a test that fails if any of our
> three sending paths ever stops doing the conversion again — that gap between
> them is what let this run unnoticed.
>
> Where that leaves your campaign:
>
> **5 people received the broken version.** I can send you the list if you
> want to follow up with them personally. I would not re-send to them
> automatically — a second copy of the same message is its own kind of wrong —
> but it is your call and I will do whichever you prefer.
>
> **61 people have not been contacted at all.** Whenever you are ready, we can
> send to exactly those 61 with the formatting correct, and nothing goes out
> until you say so.
>
> On the other thing you raised — there being nowhere to stop a campaign —
> you were right and I am building that now. A Stop button on a running or
> scheduled campaign, which tells you how many have already gone out before
> you confirm, since that is the one number nobody can take back. I will write
> when it is live.
>
> Sorry for the morning. If you would rather see the remaining 61 go out as a
> fresh campaign you set up yourself rather than a resume of this one, that
> works too — tell me which and I will get it ready.
>
> Ali

Send notes: BCC `outmassapp@outlook.com`. No call offered — async only.
Nothing here promises the Stop button by a date.
