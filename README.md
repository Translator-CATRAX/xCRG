# xCRG

Reusable xCRG package for MVP2 gene activity/abundance inferred TRAPI queries.

This package contains the xCRG core logic only. Callers such as ARAX or Shepherd
provide runtime configuration for Retriever, NGD, timeouts, and data tiers.

## Scope

- Detect MVP2 xCRG query shape.
- Build direct and TF-mediated Retriever queries.
- Filter, merge, rank, and format xCRG results.
- Return a TRAPI response with support graphs and NGD analysis support.
- Preserve Retriever-provided KG node metadata verbatim in final evidence graphs.
- Limit final answer pairs to the configured top result count.
- Keep Shepherd/ARAX service plumbing outside the package.

Out of scope:

- Choosing deployment maturity.
- Starting an HTTP service.
- Managing ARAX database files.
- Repairing or enriching Retriever-returned node/edge metadata.

## Installation

For local development:

```bash
python -m pip install -e .
```

For ARAX integration, RTX currently pins this package by Git commit in
`requirements.txt`. Once a versioned PyPI release is available, that pin should
be replaced with a normal version pin such as `catrax-xcrg==<version>`.

## Public API

```python
from xcrg import XCRGConfig, async_run_xcrg, is_xcrg_mvp2_query, run_xcrg
```

- `XCRGConfig`: runtime configuration supplied by the caller.
- `is_xcrg_mvp2_query(message)`: detects the supported MVP2 xCRG query shape.
- `run_xcrg(query, config=..., logger=...)`: synchronous entry point.
- `async_run_xcrg(query, config=..., logger=...)`: asynchronous entry point.

## Supported Query Shape

The package supports the MVP2 inferred ChemicalEntity-Gene activity/abundance
query shape used by xCRG. The query graph is expected to contain:

- one `biolink:ChemicalEntity` query node,
- one pinned `biolink:Gene` query node,
- one inferred `biolink:affects` query edge, and
- qualifier constraints for `biolink:object_aspect_qualifier` and
  `biolink:object_direction_qualifier`.

The current target aspect is `activity_or_abundance`; supported directions are
the MVP2 activity directions such as `increased` and `decreased`.

## Basic Usage

```python
from xcrg import XCRGConfig, run_xcrg

config = XCRGConfig(
    retriever_url="https://example-retriever/query",
    ngd_db_path="/path/to/curie_ngd.sqlite",
    curie_to_pmids_db_path="/path/to/curie_to_pmids.sqlite",
    tf_path=None,  # uses bundled transcription factor list
    timeout=210,
    tiers=[0],
    tf_batch_size=200,
    max_results=500,
)

response = run_xcrg(query, config=config)
```

Async callers can use:

```python
from xcrg import async_run_xcrg

response = await async_run_xcrg(query, config=config)
```

## Configuration

`XCRGConfig` is the complete package configuration contract.

| Field | Purpose |
| --- | --- |
| `retriever_url` | Required Retriever TRAPI `/query` URL selected by the caller. |
| `ngd_db_path` | Optional ARAX NGD SQLite path used for NGD scoring/support edges. |
| `curie_to_pmids_db_path` | Optional CURIE-to-PMID SQLite path used to attach NGD publication support. |
| `tf_path` | Optional transcription-factor JSON path; defaults to the bundled TF list. |
| `timeout` | Retriever HTTP timeout in seconds. |
| `tiers` | Retriever data tiers passed in TRAPI `parameters.tiers`; defaults to `[0]`. |
| `tf_batch_size` | Number of TF IDs per batched Retriever request. |
| `resource_id` | Resource ID used for xCRG-created edges and attributes, normally `infores:arax`. |
| `scoring_method` | Result analysis scoring method label. |
| `max_results` | Maximum number of final ranked answer pairs; defaults to `500`. |
| `trapi_schema_version` | Response schema version supplied by the caller. |
| `biolink_version` | Response Biolink version supplied by the caller. |
| `debug_dir` | Optional directory for saving Retriever request/response debug artifacts. |

## Output Contract

`run_xcrg` returns a TRAPI-style response dictionary. The final response is
already resultified for the supported xCRG query shape.

Output behavior:

- Final results are ranked and limited by `max_results`.
- Result analyses use `resource_id` and `scoring_method` from `XCRGConfig`.
- Retriever-provided KG nodes and edges are deep-copied into final evidence
  graphs instead of being reconstructed by xCRG.
- Retriever edge-level `biolink:support_graphs` references are preserved when
  the referenced auxiliary graphs are available.
- Dangling support-graph references are removed rather than leaving invalid
  auxiliary graph IDs in the output.
- xCRG-created NGD support edges include NGD score metadata.
- xCRG-created NGD support edges include `biolink:publications` only when the
  configured CURIE-to-PMID source contains a non-empty PMID intersection.

Metadata policy:

- xCRG does not infer, repair, or enrich Retriever node categories/names.
- Retriever evidence nodes and edges are passed through as returned.
- If Retriever returns incomplete metadata, xCRG preserves that behavior rather
  than silently masking it.

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

## Logging And Debugging

Pass a standard Python logger to `run_xcrg` or `async_run_xcrg` to receive
Retriever diagnostics. The package logs Retriever request URL, HTTP status,
TRAPI status/description, result/node/edge counts, and Retriever logs for failed
or zero-result responses.

Set `XCRGConfig.debug_dir` to save request/response debug artifacts for local
inspection. Do not enable debug artifact output in long-running production
deployments unless the caller has storage/retention controls in place.

## Local Tests

```bash
# Run unit tests
pytest

# Run integration tests
#
# These may be ran locally, but are slow and depend heavily on external
# resources like servers, database files, etc.
#
# There are several CLI args that may be provided. These are documented in tests/conftest.py.
# You can also view them by running `pytest --help` and examining "Custom options"
pytest -m integration

# Run all tests
pytest -m all
```

Recommended validation before updating an integration pin:

```bash
pytest
ruff check
ty check
git diff --check
```

## Notes

- Do not commit NGD SQLite databases.
- Do not add Shepherd-specific imports such as `shepherd_utils`.
- Retriever URL and NGD path are caller-provided config so deployment changes do
  not require republishing the package.
- Keep package code free of ARAX Flask, Shepherd service, or deployment-specific
  imports. Integrations should adapt their service config to `XCRGConfig`.
