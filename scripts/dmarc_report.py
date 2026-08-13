#!/usr/bin/env python3
"""Read DMARC aggregate reports and say, in one screen, whether our mail authenticated.

Aggregate reports arrive daily as .gz (Microsoft) or .zip (Google) attachments at
the address in the `rua=` tag of _dmarc.getoutmass.com. The XML inside is not
readable by eye, and the thing it reports on — our transactional mail passing SPF
and DKIM *aligned to getoutmass.com* — fails silently when it fails. Nobody
complains; mail just lands in spam.

Usage:
    python scripts/dmarc_report.py                 # everything in dmarc/
    python scripts/dmarc_report.py path/to/dir     # or a folder you name
    python scripts/dmarc_report.py report.xml.gz   # or one file

Exit 0: every message authenticated. 1: something sent as us did not.
2: nothing was read — deliberately distinct from a clean run.
"""

from __future__ import annotations

import glob
import gzip
import io
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

OUR_DOMAIN = "getoutmass.com"

# The Windows console here is cp1254, which cannot print an em dash — and the
# failure lands AFTER the report it was describing, so the useful output is
# already gone.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:  # pragma: no cover — very old Python
    pass

# RFC 7489 §7.2.1.1: receiver!policy-domain!begin!end[!unique].extension.
# Pointing this script at ~/Downloads must not try to parse a logo zip and
# then count it as a report that contained no messages.
REPORT_NAME = re.compile(r"^[^!]+![^!]+!\d+!\d+.*\.(xml|xml\.gz|zip|gz)$", re.I)


def _read_xml(path: Path) -> str:
    """Return the report XML from a .gz, .zip, or bare .xml file."""
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw).decode("utf-8", errors="replace")
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".xml")]
            if not names:
                raise ValueError(f"{path.name}: zip holds no .xml")
            return z.read(names[0]).decode("utf-8", errors="replace")
    return raw.decode("utf-8", errors="replace")


def _text(node, path: str, default: str = "") -> str:
    found = node.find(path)
    return (found.text or "").strip() if found is not None and found.text else default


def _stamp(epoch: str) -> str:
    try:
        return datetime.fromtimestamp(int(epoch), timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return f"?{epoch}"


def _aligned(auth_domain: str, header_from: str, relaxed: bool) -> bool:
    """DMARC identifier alignment. Relaxed lets a subdomain match its parent."""
    auth_domain, header_from = auth_domain.lower(), header_from.lower()
    if auth_domain == header_from:
        return True
    return relaxed and auth_domain.endswith("." + header_from)


def summarise(path: Path) -> tuple[int, int, list[str]]:
    """Print one report. Returns (messages, failures, strict-alignment warnings)."""
    root = ElementTree.fromstring(_read_xml(path))
    meta, policy = root.find("report_metadata"), root.find("policy_published")

    org = _text(meta, "org_name", "?")
    begin, end = _text(meta, "date_range/begin"), _text(meta, "date_range/end")
    adkim, aspf = _text(policy, "adkim", "r"), _text(policy, "aspf", "r")
    published = _text(policy, "p", "?")

    print(f"\n{org}  ·  {_stamp(begin)} → {_stamp(end)} UTC")
    print(f"  policy: p={published} sp={_text(policy, 'sp', published)} "
          f"adkim={adkim} aspf={aspf} pct={_text(policy, 'pct', '100')}")

    messages = failures = 0
    warnings: list[str] = []

    for record in root.findall("record"):
        row, ids = record.find("row"), record.find("identifiers")
        auth = record.find("auth_results")
        count = int(_text(row, "count", "0") or 0)
        messages += count

        # policy_evaluated is DMARC's own verdict — already alignment-aware.
        dkim_ok = _text(row, "policy_evaluated/dkim") == "pass"
        spf_ok = _text(row, "policy_evaluated/spf") == "pass"
        passed = dkim_ok or spf_ok
        if not passed:
            failures += count

        header_from = _text(ids, "header_from", "?")
        mark = "PASS" if passed else "FAIL"
        print(f"\n  [{mark}] {count:>4} msg  from {_text(row, 'source_ip', '?')}"
              f"  →  {_text(ids, 'envelope_to', '?')}")
        print(f"         header-from {header_from}   "
              f"envelope-from {_text(ids, 'envelope_from', '?')}   "
              f"disposition {_text(row, 'policy_evaluated/disposition', '?')}")

        for sig in auth.findall("dkim") if auth is not None else []:
            domain, result = _text(sig, "domain", "?"), _text(sig, "result", "?")
            relaxed_ok = _aligned(domain, header_from, relaxed=True)
            strict_ok = _aligned(domain, header_from, relaxed=False)
            tag = "aligned" if relaxed_ok else "unaligned"
            print(f"         DKIM {result:<9} {domain} (s={_text(sig, 'selector', '?')}) [{tag}]")
            if relaxed_ok and not strict_ok and result == "pass":
                warnings.append(f"DKIM {domain} aligns to {header_from} only under adkim=r")

        for sig in auth.findall("spf") if auth is not None else []:
            domain, result = _text(sig, "domain", "?"), _text(sig, "result", "?")
            relaxed_ok = _aligned(domain, header_from, relaxed=True)
            strict_ok = _aligned(domain, header_from, relaxed=False)
            tag = "aligned" if relaxed_ok else "unaligned"
            print(f"         SPF  {result:<9} {domain} [{tag}]")
            if relaxed_ok and not strict_ok and result == "pass":
                warnings.append(f"SPF {domain} aligns to {header_from} only under aspf=r")

    return messages, failures, warnings


# Where the reports live once they have been dragged out of an email.
INBOX = Path(__file__).resolve().parent.parent / "dmarc"


def main(argv: list[str]) -> int:
    if not argv:
        # No arguments reads the project's own folder rather than printing
        # help. The daily use of this script is "did last night's mail
        # authenticate", and that should not need an argument to answer.
        if not INBOX.is_dir():
            print(__doc__)
            return 2
        argv = [str(INBOX)]

    # A path given by name is one the caller means; anything found by scanning
    # a directory has to earn its place, because that directory is somebody's
    # Downloads folder.
    named: list[Path] = []
    found: list[Path] = []
    for arg in argv:
        candidate = Path(arg).expanduser()
        if candidate.is_dir():
            for pattern in ("*.xml", "*.xml.gz", "*.zip", "*.gz"):
                found += [
                    p for p in map(Path, glob.glob(str(candidate / pattern)))
                    if REPORT_NAME.match(p.name)
                ]
        elif candidate.exists():
            named.append(candidate)
        else:
            named += [Path(p) for p in glob.glob(arg)]

    paths = sorted(set(named) | set(found))
    if not paths:
        print("No DMARC reports found.", file=sys.stderr)
        return 2

    reports = total = failed = 0
    warnings: list[str] = []
    for path in paths:
        try:
            messages, fails, warns = summarise(path)
        except Exception as exc:  # a malformed report must not hide the others
            print(f"\n  !! {path.name}: {exc}", file=sys.stderr)
            continue
        reports += 1
        total, failed = total + messages, failed + fails
        warnings += warns

    print(f"\n{'-' * 62}")
    # `reports` counts what actually parsed. Counting the files we matched
    # would report a clean run over a folder of things that are not reports.
    print(f"{reports} report(s)   {total} message(s)   {failed} DMARC failure(s)")

    if reports == 0:
        # Exit 2, not 0. This script is meant to be read as a check, and
        # "no failures found" must not be indistinguishable from "nothing was
        # read" — that is the whole class of bug it exists to report on.
        print(
            "\nNothing parsed as a DMARC report. Point this at the .gz or .zip "
            "attachment from a DMARC aggregate email, or at the folder holding "
            "them.",
            file=sys.stderr,
        )
        return 2

    for warning in sorted(set(warnings)):
        print(f"  note: {warning} — do NOT publish strict alignment")

    if failed:
        print("\nSomething sent as us and did not authenticate. Read the FAIL rows above:")
        print("  · a source IP we recognise  → our own sending path is broken, fix before tightening p=")
        print("  · a source IP we do not     → someone is sending as us; that is what p=reject stops")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
