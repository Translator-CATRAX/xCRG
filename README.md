# xCRG

Reusable xCRG package for gene activity/abundance [TRAPI](https://github.com/NCATSTranslator/ReasonerAPI) 2.0+ queries.

This package contains the xCRG core logic only. Callers such as ARAX or Shepherd provide runtime configuration for
[Retriever](https://github.com/BioPack-team/retriever), Normalized-Google-Distance (NGD), timeouts, data tiers, etc.

The xCRG package is maintained by the [CATRAX](https://github.com/Translator-CATRAX/) team as part of the greater
[Biomedical Data Translator](https://ncats.nih.gov/research/research-activities/translator) project, funded by the
National Center for Advancing Translational Sciences (NCATS). More technical information about Translator can be found
[here](https://ncatstranslator.github.io/TranslatorTechnicalDocumentation).

### Scope

- Detect valid MVP2 xCRG query shape.
- Build and send direct (lookup) and TF-mediated (inferred) queries to Retriever.
- Filter, merge, rank, sort, format, and limit TRAPI Results from Retriever.
- Return TRAPI Response with xCRG support graph, NGD analysis support, etc.
- Preserve Retriever-provided Knowledge Graph (KG) node metadata verbatim in final evidence graphs.
- Keep ARAX/Shepherd service plumbing outside the package.

### Out of scope

- Choosing deployment maturity.
- Starting an HTTP service.
- Managing external database files.
- Repairing or enriching Retriever-returned node/edge metadata.

## Installation + usage

### Install with uv (recommended)

```bash
uv add catrax-xcrg
```

### Install with pip

```bash
pip install -e catrax-xcrg
```

### Example code

```python
"""A basic example to show how to integrate xCRG in your application."""
import xcrg


# The query ought to be valid TRAPI 2.0 JSON as string or dictionary
def my_xcrg_method(query):
    if not xcrg.is_valid_query(query):
        return None

    config = xcrg.Config(
        retriever_url = "https://fake.retriever.org/query"
        # You can configure more options here like caching, debugging, etc.
    )

    # Default reporter just logs, but you can do more with a custom xcrg.Reporter
    class My_Reporter(xcrg.Reporter):
        def handle_message(self, message: xcrg.Message) -> None:
            ...  # do logging, show progress, etc.

    # Use xcrg.async_run_query for async support
    return xcrg.run_query(query, config, My_Reporter())


response = my_xcrg_method('{ "message": { "query_graph": ... }, ... }')
```

## Local development

It is highly recommend to use [uv](https://docs.astral.sh/uv/) for project management.

```bash
# All examples are assumed to be ran from the project root directory

# Install the xCRG package for local development
uv venv
source .venv/bin/activate
uv sync

# The development environment is now configured...

# Try running some xCRG queries from the command-line
scripts/run_xcrg -p find_chemicals decreasing ptgs1
scripts/run_xcrg -p --maturity production find_genes_affected_by increasing aspirin

# You can also run the local unit tests
scripts/run_tests unit
# Integration tests make actual calls to Retriever
# The results are cached to improve performance in later invocations
scripts/run_tests integration
# Run unit + integration tests
scripts/run_tests all

# Run checks on all source files (linting, type-checking, etc.)
scripts/run_checks
```

### Scripts
There are a number of useful scripts available in the `scripts` directory.

All scripts can be invoked with `-h` or `--help` for more information.

| Filename              | Description                                                        |
|-----------------------|--------------------------------------------------------------------|
| `build_artifacts`     | Build project artifacts and (optionally) publish to PyPI.          |
| `compare_results`     | Print an analysis comparing result datasets from ARAX, NCATS, etc. |
| `generate_arax_tests` | Generate ARAX compliance pytest modules.                           |
| `run_checks`          | Run linter + type checks on the codebase.                          |
| `run_optimizer`       | Run Optuna study to optimize the scoring weights for xCRG ranker.  |
| `run_tests`           | Run test suites via pytest.                                        |
| `run_xcrg`            | Run a simple xCRG query and return the TRAPI response.             |

## API

### Supported Query Shape

This package supports the MVP2 inferred ChemicalEntity-Gene activity/abundance query shape used by xCRG.

The query graph must currently adhere to the following expectations:

- one `biolink:ChemicalEntity` query node,
- one `biolink:Gene` query node,
- where the `biolink:ChemicalEntity` node and/or `biolink:Gene` node is pinned,
- one `biolink:affects` query edge,
- where the `knowledge_type` is either `direct` or `inferred`, and
- qualifier constraints for `biolink:object_aspect_qualifier` and `biolink:object_direction_qualifier`.

The current target aspect is `activity_or_abundance`; supported directions are the MVP2 activity
directions such as `increased` and `decreased`.

An example of an inferred TRAPI 2.0+ Query as JSON follows:

```json5
{
    "message": {
        // This query asks the question: "What chemicals increase the activity or abundance of CYP3A4?"
        // In effect, the query graph looks like: (Chemicals?) -> increase -> (CYP3A4)
        "query_graph": {
            "nodes": {
                // The subject node is open; the results for this query represent an answer for this node
                "sn": { "categories": ["biolink:ChemicalEntity"] },
                // The object node is "pinned"; the results influence this node
                "on": { "categories": ["biolink:Gene"], "ids": ["NCBIGene:1576"] }
            },
            "edges": {
                "t_edge": {
                    // Inferred (i.e. creative) queries will find associations using transcription factors
                    "knowledge_type": "inferred",
                    "subject": "sn",
                    "predicates": ["biolink:affects"],
                    "object": "on",
                    "constraints": {
                        "qualifiers": [
                            {
                                "biolink:object_aspect_qualifier": "activity_or_abundance",
                                "biolink:object_direction_qualifier": "increased"
                            }
                        ]
                    }
                }
            }
        }
    }
}
```

### Run Configuration

The `xcrg.Config` class is the primary method by which the xCRG query runs are customized.

| Name                   | Description                                                                                             |
|------------------------|---------------------------------------------------------------------------------------------------------|
| retriever_url          | URL to Retriever instance that handles TRAPI 2.0+ queries. **Required**.                                |
| curie_ngd_db_file      | Path to ARAX NGD SQLite database used for NGD scoring/support edges. Optional. Default: `None`          |
| curie_to_pmids_db_file | Path to CURIE-to-PMID SQLite database used to attach NGD publication support. Optional. Default: `None` |
| timeout                | HTTP timeout. Optional. Default: `timedelta(seconds=210)`                                               |
| tiers                  | Data tiers passed in TRAPI parameters.tiers. Optional. Default: `[0]`                                   |
| tf_file                | Path to transcription tactor JSON file; defaults to the bundled list. Optional. Default: `None`         |
| tf_batch_size          | Number of transcription factors included in each batched request to Retriever. Optional. Default: `50`  |
| resource_id            | ID used for xCRG-created edges and attributes. Optional. Default: `"infores:arax"`                      |
| scoring_method         | Analysis scoring method label. Optional. Default: `"xcrg-result-filtering-v2"`                          |
| max_results            | Number of final ranked answers. Optional. Default: `500`                                                |
| trapi_schema_version   | Schema version supplied by the caller. Optional. Default: `"2.0.0"`                                     |
| biolink_version        | Biolink version supplied by the caller. Optional. Default: `"4.3.2"`                                    |
| cache_dir              | Path to a directory where Retriever TRAPI Responses are cached. Optional. Default: `None`               |
| cache_ttl              | Time-To-Live (TTL) for entries in the cache. Optional. Default: `None`                                  |
| cache_clear_on_start   | Is the cache is cleared on first invocation of the runner. Optional. Default: `True`                    |
| debug_dir              | Path to a directory where debug data will be emitted. Optional. Default: `None`                         |
| debug_run_name         | Unique name for the debug data. Optional. Default: `None`                                               |
| debug_level            | Amount of data that will be captured during a debug run. Optional. Default: `Debug_Level.BASIC`         |

### Output Contract

#### Return type

The type of response returned by `xcrg.run_query` depends on the type of query provided:

* If query is `str` (Query-shaped JSON), then response is `str` (Response-shaped JSON)
* If query is `dict` (Query-shaped dictionary), then response is `dict` (Response-shaped dictionary)
* If query is `Query` (as part of `translator_tom` library), then response is `Response` (also part of `translator_tom`)

#### Output behavior

- The final response is already resultified for the supported xCRG query shape.
- Final results are ranked and limited by `max_results`.
- Result analyses use `resource_id` and `scoring_method` from `xcrg.Config`.
- Retriever-provided KG nodes and edges are deep-copied into final evidence
  graphs instead of being reconstructed by xCRG.
- Retriever edge-level `biolink:support_graphs` references are preserved when
  the referenced auxiliary graphs are available.
- Dangling support-graph references are removed rather than leaving invalid
  auxiliary graph IDs in the output.
- xCRG-created NGD support edges include NGD score metadata.
- xCRG-created NGD support edges include `biolink:publications` only when the
  configured CURIE-to-PMID source contains a non-empty PMID intersection.

#### Metadata policy

- xCRG does not infer, repair, or enrich Retriever node categories/names.
- Retriever evidence nodes and edges are passed through as returned.
- If Retriever returns incomplete metadata, xCRG preserves that behavior rather
  than silently masking it.

## Deployment + Maturity

xCRG does not determine deployment maturity itself. The package is deliberately
deployment-agnostic: callers choose the Retriever endpoint, database paths, and
runtime options, etc. then pass them in through `xcrg.Config`.

## Logging + Debugging

```python
import logging
import xcrg

# By default, xCRG wraps the default logger to report messages.
# You can also do this explicitly:
my_logger = logging.getLogger()
reporter = xcrg.Log_Reporter(my_logger)


# Plausible example application method
def append_to_log_queue(level: int, message: str):
    ...


# Plausible example application method
def update_progress_bar(pct_done: float):
    ...


# You can subclass xcrg.Reporter yourself to operate on messages yourself.
class My_Reporter(xcrg.Reporter):
    # Care is required because Reporter callbacks currently execute synchronously.
    # Expensive operations in handle_message could degrade runner performance.
    def handle_message(self, message: xcrg.Message) -> None:
        match message:
            case xcrg.Log_Message(level, msg, _, _):
                append_to_log_queue(level, msg)
            case xcrg.Progress_Message(pct_done):
                update_progress_bar(pct_done)


# In addition to reporting, you configure debugging options in xcrg.Config for additional
# diagnostics and analysis. These can generate a lot of additional data so test accordingly.
config = xcrg.Config(
    retriever_url = "...",
    debug_dir = "path/to/debug_data",
    debug_level = xcrg.Debug_Level.ALL,
    debug_run_name = "my_debug_run"
)

response = xcrg.run_query('{ "message": ... }', config, My_Reporter())
```

## Development Considerations

- It is highly recommended to execute `scripts/run_tests` and `scripts/run_checks` and fix any associated
  issues before pushing changes
- Publishing to PyPI requires API keys that are configured properly. Run `scripts/build_artifacts --help`
  for additional information.
- Do not commit NGD SQLite databases
- Do not add Shepherd-specific imports such as `shepherd_utils`
- Retriever URL and NGD path are caller-provided config so deployment changes do
  not require republishing the package
- Keep package code free of ARAX Flask, Shepherd service, or deployment-specific
  imports. Integrations should adapt their service config to `xcrg.Config`
