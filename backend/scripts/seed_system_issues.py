from app.db.session import SessionLocal
from app.services.system_issue_seed import seed_system_issues


def main() -> None:
    with SessionLocal() as db:
        created, updated = seed_system_issues(db)
    print(f"System issues seeded: {created} created, {updated} updated")


if __name__ == "__main__":
    main()
