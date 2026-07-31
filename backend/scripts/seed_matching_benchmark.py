from __future__ import annotations

import argparse
import json

from app.db.session import SessionLocal
from app.services.matching_benchmark import seed_matching_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the isolated, synthetic matching benchmark (development only)."
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    args = parser.parse_args()
    with SessionLocal() as db:
        result = seed_matching_benchmark(db)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"Seeded {result['total_cases']} benchmark cases "
            f"(created={result['created_cases']}, updated={result['updated_cases']})."
        )


if __name__ == "__main__":
    main()

