import json

from app.db.session import SessionLocal
from app.services.initial_data import seed_initial_data

if __name__ == "__main__":
    with SessionLocal() as database:
        result = seed_initial_data(database)
    print(json.dumps(result, ensure_ascii=False, indent=2))
