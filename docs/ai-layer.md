# AI Layer: Embeddings and Vector Similarity

An embedding is a numeric representation of text that captures useful aspects of its meaning. An embedding model reads a sentence or document chunk and maps it to a point in a fixed-dimensional vector space. Texts with related meaning tend to be placed near one another, even when they do not share the same words. For example, a query about “heart specialist availability” may be close to a service description that says “cardiology appointments,” while a keyword-only search might miss that relationship.

SmartHealth can use this representation for semantic retrieval over approved service descriptions, clinical guidance, or other indexed content. During ingestion, long documents should be split into reasonably sized, slightly overlapping chunks. Each chunk is sent to the configured embedding model and stored with its vector plus metadata such as source, department, document version, and access scope. At query time, the user’s question is embedded with the same model. The system compares that query vector with stored vectors and returns the highest-scoring matches. The current configuration targets `sentence-transformers/all-MiniLM-L6-v2`, which produces 384-dimensional embeddings, with a target chunk size of 600 tokens and 80-token overlap.

A common comparison is cosine similarity. It measures the angle between two vectors rather than their raw length: vectors pointing in nearly the same direction receive a high score, while unrelated directions receive a lower score. A vector index can use this score to perform nearest-neighbor search. For a small collection, exact comparison is practical; for a large collection, an approximate nearest-neighbor index such as HNSW can return results quickly while accepting that an occasional perfect match may be missed. `RETRIEVAL_TOP_K=5` limits the initial result set, and `RETRIEVAL_MIN_SIMILARITY=0.65` provides a minimum relevance gate. That threshold is a starting point, not a universal measure of correctness, so it should be calibrated against representative queries and reviewed whenever the model or corpus changes.

Embeddings support finding relevant context; they do not prove that two statements are equivalent, current, or clinically safe. Retrieved content should therefore be treated as evidence for a later answer, not as an answer by itself. Results must pass normal authentication and authorization filters before retrieval, and source/version metadata should be retained so responses can be traced back to approved content. Exact identifiers, dates, dosage values, and negations may require keyword or structured filters alongside vector search. In healthcare workflows, a similarity score must never be interpreted as a diagnosis, risk probability, or substitute for professional review.

## Publication and Chunk Contract

Publishing a service runs validation, structuring, chunking, embedding, and persistence stages. The publish-status response keeps the current `status` value and also exposes `stage`, `chunks_total`, and `embeddings_generated`, so clients can show progress while the workflow is running.

Every content chunk deliberately starts with the same labeled context block:

```text
Service: <service name>
Department: <department name>
Specialty: <specialty or Not specified>
Preparation instructions: <instructions or Not specified>
```

The description is then split into 120-character segments and appended to that context. Repeating the context in each chunk prevents retrieval results from losing the service identity or preparation guidance when only one chunk is returned. Chunks are embedded with the configured 384-dimensional model and stored in the `content_chunks.embedding` pgvector column.

Each indexed chunk also stores `service_id`, `department`, `specialty`, `published`, and a SHA-256 `content_hash`. The hash is calculated from the final chunk text, including the labeled context. During publication, the embedding Activity looks up existing rows by service, chunk index, and hash. Unchanged chunks reuse their stored vector; only new or changed chunks are sent to the provider. Provider calls are bounded by `EMBEDDING_BATCH_SIZE` and retried by Temporal using the configured Activity retry policy.

Persistence is handled by `ContentChunkRepository`, not by the embedding provider. Re-indexing replaces all chunks for the service before the service is marked published. The unique `(service_id, chunk_index)` constraint and replacement behavior remove stale chunks and prevent duplicate indexes. Existing rows created before hash support are embedded once on their next publication and then receive a hash.

## Service Search

`POST /search` and `POST /api/v1/search` accept `{"query": "...", "limit": 5}` and require authentication. The endpoint caps the requested limit at `RETRIEVAL_TOP_K`, ranks candidates by cosine similarity, and omits results below `RETRIEVAL_MIN_SIMILARITY`. Only the highest-scoring chunk per service is returned.

Search requires both the stored chunk flag `published=true` and the live service flag `is_published=true`. This prevents stale or unpublished vectors from being returned after catalog changes. Results contain only approved service-catalog fields: `service_id`, `service_name`, `score`, `department`, `specialty`, and chunk content. Patient, appointment, billing, authentication, and other PHI-bearing tables are not joined or returned. Authentication is enforced by the API dependency, while service filtering is enforced in the repository layer.

When `EMBEDDING_API_KEY` is unset, local development uses a deterministic token-based embedding so workflows and tests remain runnable. Production deployments should configure the selected embedding provider and key.

## Retrieval Evaluation

The checked-in evaluation set at `evaluation/retrieval_eval.json` contains 10 query and expected-service pairs. Run it with:

```bash
python scripts/eval_retrieval.py --limit 5
```

The script reports `top_k`, the active similarity `threshold`, total cases, hits, hit rate, and per-case results. A hit means the expected service name or ID appears in the returned top-k results. The result is corpus-dependent: run it after services are published and vectors are indexed, and record the output when changing the model, threshold, chunking, or service corpus.

The evaluation harness is committed and ready, but no reproducible hit-rate number is recorded in this development checkout because its local SQLite database has no indexed `content_chunks` corpus. The honest baseline/current status is:

| Run | Corpus state | Result |
| --- | --- | --- |
| Before retrieval safeguards | Not captured | Not comparable |
| Current implementation | Dataset committed; local corpus unavailable | Run the command above after migration and publication |

Do not treat a missing corpus or an empty result as a zero-quality model. Run the evaluation against the same published corpus before and after any model, threshold, or chunking change.

Further reading:

- [Sentence Transformers: Semantic Search](https://www.sbert.net/examples/sentence_transformer/applications/semantic-search/README.html)
- [Hugging Face Inference Client: Feature Extraction](https://huggingface.co/docs/huggingface_hub/en/package_reference/inference_client#huggingface_hub.InferenceClient.feature_extraction)
