# xCRG

Reusable xCRG package for MVP2 gene activity/abundance inferred TRAPI queries.

This package contains the xCRG core logic only. Callers such as ARAX or Shepherd
provide runtime configuration for Retriever, NGD, timeouts, and data tiers.

## Current Scope

- Detect MVP2 xCRG query shape.
- Build direct and TF-mediated Retriever queries.
- Filter, merge, rank, and format xCRG results.
- Return a TRAPI response with support graphs and NGD analysis support.
- Preserve Retriever-provided KG node metadata verbatim in final evidence graphs.
- Limit final answer pairs to the configured top result count.
- Keep Shepherd/ARAX service plumbing outside the package.

## Usage

```python
from xcrg import XCRGConfig, run_xcrg

config = XCRGConfig(
    retriever_url="https://example-retriever/query",
    ngd_db_path="/path/to/curie_ngd.sqlite",
    tf_path=None,  # uses bundled transcription factor list
    timeout=210,
    tiers=[0],
    max_results=500,
)

response = run_xcrg(query, config=config)
```

Async callers can use:

```python
from xcrg import async_run_xcrg

response = await async_run_xcrg(query, config=config)
```

## Local Tests

```bash
PYTHONPATH=src python -m pytest tests
```

## Notes

- Do not commit NGD SQLite databases.
- Do not add Shepherd-specific imports such as `shepherd_utils`.
- Retriever URL and NGD path are caller-provided config so deployment changes do
  not require republishing the package.
- xCRG does not infer or repair Retriever node categories/names; Retriever node
  objects used as evidence are passed through as returned.
