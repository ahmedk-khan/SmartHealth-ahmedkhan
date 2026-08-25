import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.settings import settings
from app.db import SessionLocal
from app.services.search_service import search_services


def load_cases(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as file:
        cases = json.load(file)
    if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
        raise ValueError("Evaluation dataset must be a list of objects")
    return cases


async def evaluate(cases: list[dict[str, object]], limit: int) -> dict[str, object]:
    db = SessionLocal()
    results = []
    try:
        for case in cases:
            query = case["query"]
            expected_service = case["expected_service"]
            matches = await search_services(db, str(query), limit)
            hit = any(
                result["service_name"] == expected_service or result["service_id"] == expected_service
                for result in matches
            )
            results.append({"query": query, "expected_service": expected_service, "hit": hit, "results": matches})
    finally:
        db.close()
    hits = sum(result["hit"] for result in results)
    return {"top_k": limit, "threshold": settings.retrieval_min_similarity, "total": len(results), "hits": hits, "hit_rate": hits / len(results) if results else 0.0, "cases": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate published service retrieval.")
    parser.add_argument("query", nargs="?", help="Run one search query")
    parser.add_argument("--limit", type=int, default=settings.retrieval_top_k)
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/retrieval_eval.json"))
    args = parser.parse_args()

    if args.query:
        db = SessionLocal()
        try:
            results = asyncio.run(search_services(db, args.query, args.limit))
            for result in results:
                print(result)
        finally:
            db.close()
        return

    print(json.dumps(asyncio.run(evaluate(load_cases(args.dataset), args.limit)), indent=2))


if __name__ == "__main__":
    main()
