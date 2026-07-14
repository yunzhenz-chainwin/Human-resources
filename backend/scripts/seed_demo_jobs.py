"""Idempotently add demo requisitions to the configured database."""

from app.db.session import SessionLocal
from app.services.demo_data import seed_demo_requisitions, seed_matching_showcase


def main() -> None:
    with SessionLocal() as db:
        created = seed_demo_requisitions(db)
        showcase, candidates = seed_matching_showcase(db)
    print(f"Demo requisitions created: {len(created)}")
    print(f"Matching showcase ready: {showcase.req_no}, candidates: {len(candidates)}")


if __name__ == "__main__":
    main()
