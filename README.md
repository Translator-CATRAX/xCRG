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

## Deployment And Maturity

xCRG does not determine deployment maturity itself. The package is deliberately
deployment-agnostic: callers choose the Retriever endpoint, database paths, and
runtime options, then pass them in through `XCRGConfig`.

For ARAX, this selection happens in `ARAX_connect.py`, not inside this package.
The ARAX integration reads `RTXConfiguration().maturity`, maps that maturity to
the matching Retriever deployment, and passes the resolved URL to xCRG:

| ARAX maturity | Retriever URL |
| --- | --- |
| `staging` | `https://retriever.ci.transltr.io/query` |
| `testing` | `https://retriever.test.transltr.io/query` |
| `production` | `https://retriever.transltr.io/query` |
| `development` | `https://retriever.ci.transltr.io/query` |

In ARAX, the effective flow is:

```text
RTXConfiguration().maturity
-> ARAX_connect.get_xcrg_retriever_url(...)
-> XCRGConfig(retriever_url=...)
-> run_xcrg(...)
```

ARAX also passes its existing NGD resources into the package:

```text
get_curie_ngd_path()       -> XCRGConfig.ngd_db_path
get_curie_to_pmids_path()  -> XCRGConfig.curie_to_pmids_db_path
```

The optional ARAX environment variables `ARAX_XCRG_RETRIEVER_URL`,
`ARAX_XCRG_TIMEOUT`, and `ARAX_XCRG_TF_BATCH_SIZE` are local/debug overrides for
the ARAX integration. They are not required for normal deployed ARAX behavior.
If production deployment values need to become operator-managed settings, they
should be promoted into ARAX/RTX configuration rather than hardcoded in xCRG.

Other callers, such as Shepherd or local smoke tests, can use their own
deployment logic as long as they provide the selected endpoint and database paths
through `XCRGConfig`.

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
- If a user-pinned query endpoint is referenced by evidence but Retriever omits
  its KG node, xCRG uses only the explicit category metadata supplied in the
  query graph for that endpoint.
