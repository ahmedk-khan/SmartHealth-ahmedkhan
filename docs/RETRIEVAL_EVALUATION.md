# Phase 3.2 Retrieval Evaluation

## Evaluation Dataset

**File:** `evaluation/retrieval_eval.json`  
**Size:** 20 query/expected-service pairs  
**Coverage:**
- **Categories:** Primary Care (5), Specialty (8), Surgery (2), Mental Health (1), Women's Health (1), Dental (1)
- **Difficulty Levels:** Direct queries (11), Moderate/complex queries (9)

## Running Evaluation

```bash
# Run evaluation with default settings (k=5, min_similarity=0.5)
python scripts/eval_retrieval_enhanced.py --verbose --output results.md

# Run with custom parameters
python scripts/eval_retrieval_enhanced.py --k 10 --min_similarity 0.3 --output results.md

# CLI Options
# --k: Number of top results to return (default: 5, max: 20)
# --min_similarity: Minimum similarity score (0.0-1.0, default: 0.5)
# --verbose: Print detailed results for each query
# --output: Write results to markdown file (optional)
```

## Evaluation Metrics

Results table reports:
- **Overall Accuracy:** Percentage of queries where expected service appears in top-k results
- **By Category:** Accuracy per service category (Primary Care, Specialty, etc.)
- **By Difficulty:** Accuracy for direct vs. complex queries

Example output:

| Category | Accuracy | Queries |
|----------|----------|---------|
| Primary Care | 100% | 5/5 |
| Specialty | 87% | 7/8 |
| Surgery | 100% | 2/2 |
| Mental Health | 100% | 1/1 |
| Women's Health | 100% | 1/1 |
| Dental | 100% | 1/1 |
| **Overall** | **95%** | **19/20** |

## Accuracy by Difficulty

| Difficulty | Accuracy | Queries |
|------------|----------|---------|
| Direct | 100% | 11/11 |
| Moderate | 89% | 8/9 |
| **Overall** | **95%** | **19/20** |

## Filtering & Reranking

Results are automatically:
- Filtered to published, offered services only
- Scored by cosine similarity (pgvector)
- Ranked by similarity score (highest first)
- Filtered by configurable `min_similarity` threshold
- Scoped to patient's PHI context (cross-patient data isolation enforced)
