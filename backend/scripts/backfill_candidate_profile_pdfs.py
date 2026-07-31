"""Backfill clearly labelled system-generated PDFs for talent records without one."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from app.db.session import SessionLocal
from app.services.candidate_profile_pdf import backfill_candidate_profile_pdfs


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create system-generated talent profile PDFs only when a candidate has no "
            "available PDF. The default is a read-only preview."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write generated PDFs and ResumeFile records.",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        result = backfill_candidate_profile_pdfs(db, dry_run=not args.apply)
        if args.apply:
            db.commit()
        else:
            db.rollback()
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
