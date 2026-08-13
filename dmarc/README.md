# DMARC reports

Drop the `.gz` / `.zip` attachments from the DMARC aggregate emails here, then:

```bash
python scripts/dmarc_report.py
```

With no arguments the script reads this folder. Exit code 0 means every
message in every report authenticated; 1 means something sent as us and did
not; 2 means nothing was read at all — which is deliberately not the same as
a clean run.

## What these are

Aggregate reports go to the address in the `rua=` tag of
`_dmarc.getoutmass.com`, currently `outmassapp@outlook.com`. One arrives per
receiver per day. Microsoft sends two, from separate pipelines:
`protection.outlook.com` (Outlook.com) and `enterprise.protection.outlook.com`
(Microsoft 365 tenants).

They matter more here than they would for most products: every OutMass
customer is on a Microsoft mail host by definition, so Microsoft's report is
not one opinion among several — it is the only one. MailerSend reporting
"Delivered" means the far end accepted the message, not that it believed it.

## Why the files are not committed

`.gitignore` keeps the reports themselves out of git. They arrive daily, they
are operational data rather than source, and they name sending IPs and
infrastructure. The folder and this file are tracked so the path exists.

## What to watch for

- **A FAIL row from an IP we recognise** — our own sending path is broken.
  Fix it before tightening the DMARC policy.
- **A FAIL row from an IP we do not** — somebody is sending as us. That is
  what `p=reject` stops.
- **The alignment note.** The envelope sender is `mta.getoutmass.com` and the
  header sender is `getoutmass.com`, so SPF aligns only under the relaxed
  policy we publish. Never set `aspf=s`; it would leave DKIM carrying the
  whole thing alone.

The policy is `p=none` today — monitoring only, nothing is blocked. Before
moving to `quarantine` and then `reject`, wait for a report window that
contains a Stripe billing email: the Stripe sending domain was submitted
2026-08-11 and has not appeared in a report yet. Tightening first would
quarantine our own billing mail.
