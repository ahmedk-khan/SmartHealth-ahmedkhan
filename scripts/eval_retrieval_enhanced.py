#!/usr/bin/env python
"""
Retrieval Evaluation Script

Evaluates semantic search accuracy against the retrieval evaluation set.
Runs queries and checks if expected service appears in top-k results.

Usage:
    python scripts/eval_retrieval.py [--k 5] [--min_similarity 0.5]
"""

import sys
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional
from collections import defaultdict

# Add parent directory to path so we can import app
sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.services.search_service import search_services
from app.db import Base

logger = logging.getLogger(__name__)


def load_evaluation_set(eval_file: Path) -> dict:
    """Load evaluation set from JSON file."""
    with open(eval_file) as f:
        data = json.load(f)
    return data


async def run_evaluation(
    eval_set: dict,
    db: Session,
    k: int = 5,
    min_similarity: float = 0.5,
    verbose: bool = False,
) -> dict:
    """
    Run evaluation on all queries.
    
    Returns:
        Dictionary with results, statistics, and per-query details
    """
    results = {
        "config": {
            "k": k,
            "min_similarity": min_similarity,
            "total_queries": len(eval_set["evaluation_queries"]),
        },
        "by_category": defaultdict(lambda: {"total": 0, "correct": 0, "accuracy": 0.0}),
        "by_difficulty": defaultdict(lambda: {"total": 0, "correct": 0, "accuracy": 0.0}),
        "queries": [],
    }
    
    total_correct = 0
    total_queries = 0
    
    for q in eval_set["evaluation_queries"]:
        query_id = q["id"]
        query_text = q["query"]
        expected_service = q["expected_service"]
        category = q.get("category", "Unknown")
        difficulty = q.get("difficulty", "unknown")
        
        # Run search
        try:
            search_results = await search_services(db, query_text, k)
        except Exception as exc:
            logger.error(f"Query {query_id} failed: {exc}")
            search_results = []
        
        # Check if expected service in results
        found = any(r["service_name"] == expected_service for r in search_results)
        if found:
            total_correct += 1
        
        total_queries += 1
        
        # Get top result for detail
        top_result = search_results[0] if search_results else None
        
        query_result = {
            "id": query_id,
            "query": query_text,
            "expected_service": expected_service,
            "found": found,
            "rank": None,
            "top_result": top_result,
            "all_results": search_results,
            "category": category,
            "difficulty": difficulty,
        }
        
        # Find rank if found
        if found:
            for rank, result in enumerate(search_results, 1):
                if result["service_name"] == expected_service:
                    query_result["rank"] = rank
                    break
        
        results["queries"].append(query_result)
        
        # Update category stats
        results["by_category"][category]["total"] += 1
        if found:
            results["by_category"][category]["correct"] += 1
        
        # Update difficulty stats
        results["by_difficulty"][difficulty]["total"] += 1
        if found:
            results["by_difficulty"][difficulty]["correct"] += 1
        
        if verbose:
            status = "✓" if found else "✗"
            print(f"{status} Q{query_id}: '{query_text[:50]}...' → Expected: {expected_service}, Found: {found}")
    
    # Calculate overall accuracy
    overall_accuracy = total_correct / total_queries if total_queries > 0 else 0.0
    results["overall"] = {
        "total": total_queries,
        "correct": total_correct,
        "accuracy": round(overall_accuracy, 4),
    }
    
    # Calculate category accuracies
    for cat in results["by_category"]:
        total = results["by_category"][cat]["total"]
        correct = results["by_category"][cat]["correct"]
        acc = correct / total if total > 0 else 0.0
        results["by_category"][cat]["accuracy"] = round(acc, 4)
    
    # Calculate difficulty accuracies
    for diff in results["by_difficulty"]:
        total = results["by_difficulty"][diff]["total"]
        correct = results["by_difficulty"][diff]["correct"]
        acc = correct / total if total > 0 else 0.0
        results["by_difficulty"][diff]["accuracy"] = round(acc, 4)
    
    return results


def print_results(results: dict):
    """Print evaluation results in formatted table."""
    print("\n" + "=" * 80)
    print("RETRIEVAL EVALUATION RESULTS")
    print("=" * 80)
    
    # Overall stats
    overall = results["overall"]
    print(f"\nOverall Accuracy: {overall['correct']}/{overall['total']} ({overall['accuracy']*100:.1f}%)")
    print(f"Configuration: k={results['config']['k']}, min_similarity={results['config']['min_similarity']}")
    
    # By category
    print("\n" + "-" * 80)
    print("ACCURACY BY CATEGORY:")
    print("-" * 80)
    print(f"{'Category':<25} {'Correct':<10} {'Total':<10} {'Accuracy':<10}")
    print("-" * 80)
    
    for cat, stats in sorted(results["by_category"].items()):
        acc_pct = stats["accuracy"] * 100
        print(f"{cat:<25} {stats['correct']:<10} {stats['total']:<10} {acc_pct:>6.1f}%")
    
    # By difficulty
    print("\n" + "-" * 80)
    print("ACCURACY BY DIFFICULTY:")
    print("-" * 80)
    print(f"{'Difficulty':<25} {'Correct':<10} {'Total':<10} {'Accuracy':<10}")
    print("-" * 80)
    
    for diff, stats in sorted(results["by_difficulty"].items()):
        acc_pct = stats["accuracy"] * 100
        print(f"{diff:<25} {stats['correct']:<10} {stats['total']:<10} {acc_pct:>6.1f}%")
    
    # Failed queries
    print("\n" + "-" * 80)
    print("FAILED QUERIES (Expected service not in top-k):")
    print("-" * 80)
    
    failed = [q for q in results["queries"] if not q["found"]]
    if not failed:
        print("All queries passed! ✓")
    else:
        for q in failed:
            print(f"\nQ{q['id']}: {q['query']}")
            print(f"  Expected: {q['expected_service']}")
            print(f"  Got: {[r['service_name'] for r in q['all_results'][:3]]}")
    
    print("\n" + "=" * 80 + "\n")


def save_results_markdown(results: dict, output_file: Path):
    """Save results as markdown table."""
    lines = [
        "# Retrieval Evaluation Results\n",
        f"**Date:** {Path('evaluation/retrieval_eval.json').stat().st_mtime}\n",
        f"**Configuration:** k={results['config']['k']}, min_similarity={results['config']['min_similarity']}\n\n",
        "## Summary\n",
        f"- **Overall Accuracy:** {results['overall']['correct']}/{results['overall']['total']} ({results['overall']['accuracy']*100:.1f}%)\n",
        f"- **Queries Evaluated:** {results['overall']['total']}\n",
        f"- **Correct Results:** {results['overall']['correct']}\n\n",
        "## Accuracy by Category\n",
        "| Category | Correct | Total | Accuracy |\n",
        "|----------|---------|-------|----------|\n",
    ]
    
    for cat, stats in sorted(results["by_category"].items()):
        acc_pct = stats["accuracy"] * 100
        lines.append(f"| {cat} | {stats['correct']} | {stats['total']} | {acc_pct:.1f}% |\n")
    
    lines.append("\n## Accuracy by Difficulty\n")
    lines.append("| Difficulty | Correct | Total | Accuracy |\n")
    lines.append("|-----------|---------|-------|----------|\n")
    
    for diff, stats in sorted(results["by_difficulty"].items()):
        acc_pct = stats["accuracy"] * 100
        lines.append(f"| {diff} | {stats['correct']} | {stats['total']} | {acc_pct:.1f}% |\n")
    
    # Failed queries
    failed = [q for q in results["queries"] if not q["found"]]
    if failed:
        lines.append("\n## Failed Queries\n")
        for q in failed:
            top_results = ", ".join(r["service_name"] for r in q["all_results"][:3])
            lines.append(f"- Q{q['id']}: '{q['query']}' → Expected: {q['expected_service']}, Got: [{top_results}]\n")
    
    with open(output_file, "w") as f:
        f.writelines(lines)


async def main(
    k: int = typer.Option(5, help="Top-k results to retrieve"),
    min_similarity: float = typer.Option(0.5, help="Minimum similarity threshold"),
    verbose: bool = typer.Option(False, help="Verbose output"),
    output: Optional[Path] = typer.Option(None, help="Save results to file (markdown)"),
):
    """
    Run retrieval evaluation.
    
    Example:
        python scripts/eval_retrieval.py --k 5 --min_similarity 0.5 --output results.md --verbose
    """
    # Load evaluation set
    eval_file = Path(__file__).parent.parent / "evaluation" / "retrieval_eval.json"
    if not eval_file.exists():
        print(f"Error: Evaluation file not found: {eval_file}")
        raise typer.Exit(1)
    
    eval_set = load_evaluation_set(eval_file)
    print(f"Loaded {len(eval_set['evaluation_queries'])} evaluation queries")
    
    # Initialize database
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    
    with Session(engine) as db:
        # Run evaluation
        print("Running evaluation...")
        results = await run_evaluation(eval_set, db, k=k, min_similarity=min_similarity, verbose=verbose)
    
    # Print results
    print_results(results)
    
    # Save to file if requested
    if output:
        save_results_markdown(results, output)
        print(f"Results saved to {output}")


if __name__ == "__main__":
    typer.run(main)
