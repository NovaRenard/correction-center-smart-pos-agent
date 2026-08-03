"""Emit a ready-to-paste mock CRM payment command without contacting any terminal."""

from __future__ import annotations

import argparse
import json
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a mock CRM payment.start command")
    parser.add_argument("--amount", type=int, required=True)
    args = parser.parse_args()
    if args.amount <= 0:
        parser.error("amount must be a positive integer")
    print(
        json.dumps(
            {
                "type": "payment.start",
                "commandId": str(uuid4()),
                "operationId": str(uuid4()),
                "payload": {"amount": args.amount, "ownCheque": False},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
