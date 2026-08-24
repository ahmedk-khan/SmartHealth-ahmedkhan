import argparse
import asyncio

from app.db import SessionLocal
from app.services.search_service import search_services


parser = argparse.ArgumentParser(description="Evaluate published service retrieval.")
parser.add_argument("query", help="Search query")
parser.add_argument("--limit", type=int, default=5)
args = parser.parse_args()

db = SessionLocal()
try:
    results = asyncio.run(search_services(db, args.query, args.limit))
    for result in results:
        print(result)
finally:
    db.close()
