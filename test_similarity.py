"""Checks for embeddings.py. Run: uv run python test_similarity.py

The pure-math checks always run. The live embedding check runs only when
OPENROUTER_API_KEY is present, and is skipped loudly otherwise.
"""

import config
from embeddings import cosine_similarity, embed_texts, load_records, save_records

failures = []

def check(label: str, passed: bool) -> None:
    print(f"{'PASS' if passed else 'FAIL'}  {label}")
    if not passed:
        failures.append(label)

def check_raises(label: str, expected: type, call) -> None:
    try:
        call()
    except expected:
        check(label, True)
    except Exception as error:
        check(f"{label} (got {type(error).__name__})", False)
    else:
        check(f"{label} (nothing raised)", False)

print("-- cosine similarity --")
check("identical vectors score ~1.0", abs(cosine_similarity([0.1, 0.2, 0.3], [0.1, 0.2, 0.3]) - 1.0) < 0.001)
check("orthogonal vectors score 0.0", cosine_similarity([1, 0], [0, 1]) == 0.0)
check("opposite vectors score ~-1.0", abs(cosine_similarity([1, 2], [-1, -2]) + 1.0) < 0.001)
check("zero vector is guarded, no nan", cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0)
check("magnitude ignored, direction is not", abs(cosine_similarity([1, 1], [5, 5]) - 1.0) < 0.001)
check_raises("mismatched lengths raise ValueError", ValueError, lambda: cosine_similarity([1, 2], [1, 2, 3]))

print("-- json round trip --")
records = [
    {"id": "doc-1", "text": "Reset my password", "category": "auth", "embedding": [0.1, -0.2, 0.3]},
    {"id": "doc-2", "text": "Café invoice — €40 overcharge", "category": "billing", "embedding": [0.4, 0.5, -0.6]},
]
path = "output/test_records.json"
save_records(records, path)
check("records round-trip unchanged", load_records(path) == records)

print("-- fail fast --")
saved_key = config.OPENROUTER_API_KEY
try:
    config.OPENROUTER_API_KEY = None
    check_raises("missing OPENROUTER_API_KEY raises before any HTTP call", RuntimeError, lambda: embed_texts(["hello"]))
finally:
    config.OPENROUTER_API_KEY = saved_key

print("-- live embedding smoke --")
if not config.OPENROUTER_API_KEY:
    print("SKIP  no OPENROUTER_API_KEY in .env, live embedding check not run")
else:
    vectors = embed_texts([
        "How do I reset my password?",
        "I forgot my login credentials",
        "The deployment pipeline failed on the build step",
    ])
    check("3 texts return 3 vectors", len(vectors) == 3)
    check("vectors are non-empty and equal length", len({len(v) for v in vectors}) == 1 and len(vectors[0]) > 0)
    same = cosine_similarity(vectors[0], vectors[1])
    cross = cosine_similarity(vectors[0], vectors[2])
    print(f"      same-category  {same:.4f}")
    print(f"      cross-category {cross:.4f}")
    check("same-category scores higher than cross-category", same > cross)

print()
if failures:
    print(f"{len(failures)} check(s) failed:")
    for label in failures:
        print(f"  - {label}")
    raise SystemExit(1)
print("all checks passed")
