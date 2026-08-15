"""The green check, printed in full.

    cd backend && python scripts/green.py

This is the long form of what the beat sends to Telegram every morning. Both
call workers.green_report.build — one builder, two front-ends, so the terminal
and the phone can never disagree about whether we are green.

Prefer the Telegram one. It runs inside production, against production
credentials, and therefore cannot be pointed at the wrong database — which is
exactly what happened to the first run of this script, on a laptop, where the
users table came back empty and every check reported "0 accounts, ok".

Reach for this when you want the reasoning that does not fit in a Telegram
message, or when you want the answer right now instead of tomorrow morning.
Run it with production credentials, and note that Gate 1 then describes the
process YOU started, not the web service.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_db  # noqa: E402
from workers.green_report import (  # noqa: E402
    EmptyDatabase,
    as_text,
    build,
)


def main() -> None:
    print("OutMass — green check")
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    try:
        print(as_text(build(get_db(), role="this process")))
    except EmptyDatabase as e:
        print(f"\nSTOP — {e}")
        print(
            "\nNothing else is printed, because every line below would have "
            "been computed over an empty list and shown as though it passed."
        )
        raise SystemExit(2)
    except Exception as e:  # noqa: BLE001
        print(f"\ncould not build the report: {e}")
        raise SystemExit(1)

    print(
        "\nThe gates get WORSE with traffic — close them first.\n"
        "Everything below them gets BETTER with traffic: they are the things\n"
        "you only learn from users, and marketing is how you learn them."
    )


if __name__ == "__main__":
    main()
