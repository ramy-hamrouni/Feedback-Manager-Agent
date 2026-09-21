# Manager Agent API

FastAPI service that turns a stored assessment score into manager-facing narrative
feedback. You give it a `(project, assessment, user)` triple; it reads the score
document from MongoDB, enriches each competency with a proficiency framework, generates
an executive summary and a per-competency interpretation with an LLM, and writes the
result back onto the score document.

The pipeline is a LangGraph state machine, ported from
`feedback_agent_pipeline_v6_2.ipynb`, and every run is traced to Langfuse.

---

## Requirements

- **Python 3.10+** (the codebase uses `X | None` union syntax)
- **MongoDB access** — an Atlas/CosmosDB cluster holding the `scores`, `projects` and
  `competencies` collections
- **An LLM API key** — OpenAI or Anthropic (or use the `mock` provider to run without one)
- *Optional:* Langfuse keys for tracing, Azure Blob credentials for framework artifacts

---

## Setup

From the `api/` folder:

```bash
# 1. create and activate a virtual environment
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

# 2. install dependencies
pip install -r requirements.txt

# 3. create your .env (see Configuration below)
cp .env.example .env    # or create .env by hand
```

> **Note:** `langchain` must be installed, not just `langchain-core`. Langfuse's
> LangGraph integration imports it at runtime, and without it the traces still appear
> but **every node span is silently missing**. It is in `requirements.txt`.

---

## Configuration

Settings are read from `.env` (or the real environment) by `core/settings.py`. Every
setting accepts two names: the `MANAGER_AGENT_*` form and a shorter notebook-style
alias. Either works.

### Minimum to start

```ini
# ── LLM ────────────────────────────────────────────────
MANAGER_AGENT_LLM_PROVIDER=openai          # openai | anthropic | mock
MANAGER_AGENT_OPENAI_API_KEY=sk-...
# or, for anthropic:
# MANAGER_AGENT_ANTHROPIC_API_KEY=sk-ant-...

# ── MongoDB ────────────────────────────────────────────
MANAGER_AGENT_MONGO_REGION=DEV             # UAE | KSA | DEV
MANAGER_AGENT_MONGO_DEV_URI=mongodb+srv://...   # DEV only
# for UAE / KSA instead:
# MANAGER_AGENT_MONGO_USERNAME=...
# MANAGER_AGENT_MONGO_PASSWORD=...
```

`MANAGER_AGENT_LLM_PROVIDER=mock` returns canned responses — useful for exercising the
pipeline wiring without spending tokens or holding a key.

### Models

| Variable | Alias | Default |
|---|---|---|
| `MANAGER_AGENT_OPENAI_MODEL` | `OPENAI_MODEL` | `gpt-5.4` |
| `MANAGER_AGENT_SMALL_OPENAI_MODEL` | `SMALL_OPENAI_MODEL` | `gpt-5.4-mini` |
| `MANAGER_AGENT_ANTHROPIC_MODEL` | `ANTHROPIC_MODEL` | `claude-sonnet-4-6` |
| `MANAGER_AGENT_LLM_TEMPERATURE` | `TEMPERATURE` | `0.3` |

The framework-enrichment nodes were tuned on OpenAI models and can be pointed at their
own model regardless of the primary provider:

```ini
MANAGER_AGENT_ENRICH_WITH_FRAMEWORK=true
MANAGER_AGENT_FRAMEWORK_JOBPURPOSE_MODEL=gpt-5.4
MANAGER_AGENT_FRAMEWORK_DEFINITION_MODEL=gpt-5.4
MANAGER_AGENT_FRAMEWORK_PROFICIENCY_MODEL=gpt-5.4
```

Setting `ENRICH_WITH_FRAMEWORK=false` skips framework generation entirely and every
competency falls back to the three generic level descriptions in
`domain/narrative_rules.py` — much cheaper, much less specific output.

### Tracing (optional)

```ini
MANAGER_AGENT_LANGFUSE_PUBLIC_KEY=pk-lf-...
MANAGER_AGENT_LANGFUSE_SECRET_KEY=sk-lf-...
MANAGER_AGENT_LANGFUSE_HOST=https://cloud.langfuse.com
```

Leave them out and the service runs normally with tracing disabled.

### Framework artifacts (optional)

```ini
MANAGER_AGENT_ARTIFACT_BUCKET_URI=az://manager-agent/feedback-artifacts
MANAGER_AGENT_AZURE_STORAGE_CONNECTION_STRING=...
MANAGER_AGENT_ARTIFACT_LOCAL_CACHE_DIR=.cache/manager_agent_artifacts
```

Without these the framework-row lookup finds nothing and every competency's proficiency
levels are LLM-generated instead of taken from the curated set.

### Other

| Variable | Default | Purpose |
|---|---|---|
| `MANAGER_AGENT_LOG_LEVEL` | `INFO` | Root log level |
| `MANAGER_AGENT_LLM_MAX_TOKENS_SUMMARY` | `400` | Executive-summary budget |
| `MANAGER_AGENT_LLM_MAX_TOKENS_INTERPRETATION` | `2000` | Per-competency budget |
| `MANAGER_AGENT_LLM_FALLBACK_TO_RULES` | `true` | Use a template when an LLM call fails instead of failing the run |
| `MANAGER_AGENT_MONGO_SERVER_SELECTION_TIMEOUT_MS` | `8000` | Mongo connect timeout |

---

## Run locally

```bash
uvicorn main:app --reload
```

Or from the workspace root:

```bash
uvicorn api.main:app --reload
```

- API: <http://127.0.0.1:8000>
- Interactive docs: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/api/v1/health>

### Verify the startup

Watch the first few log lines:

```
Langfuse config: host=https://cloud.langfuse.com public_key=pk-lf-…  secret_key=sk-lf-…
Langfuse tracing ON (client and LangGraph callback handler ready)
LangGraph node spans: ENABLED
```

If the last line is missing, node-level tracing is off and the log line says why.

To prove traces actually reach Langfuse without waiting for a full run, start with:

```bash
LANGFUSE_SELFCHECK=1 uvicorn main:app --reload      # PowerShell: $env:LANGFUSE_SELFCHECK=1
```

This pushes a span named `tracing_selfcheck`. If it doesn't show up in the Langfuse UI
within a minute, the keys or host are wrong.

`GET /api/v1/health` reports artifact load counts, the Mongo region and database, and
whether artifact storage is reachable.

---

## API

### `POST /api/v1/scores/run`

Starts a feedback run. Returns **202 Accepted** immediately; the pipeline continues in
the background and writes its output back onto the score document.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/scores/run \
  -H "Content-Type: application/json" \
  -d '{
    "project_id":    "6ab0f4bb532757b6f5f3f3a2",
    "assessment_id": "6a673b3d01c32337d3903ed5",
    "user_id":       "6ab0f4b9532757b6f5f3f3a0",
    "force_rerun":   false
  }'
```

**Response — 202**

```json
{
  "project_id": "...",
  "assessment_id": "...",
  "user_id": "...",
  "status": "accepted",
  "created_at": "2026-09-21T12:00:00+00:00"
}
```

`force_rerun: true` bypasses the "already generated" check and regenerates over an
existing result.

**What the run writes back** onto the score document in `scores`:

- `feedbackGenerationStatus` — `in progress` → `completed` / `failed`
- `executiveSummary`
- `competencyInterpretation` on each entry in `scoreCompetenciesScores`

### Errors

All errors share one envelope:

```json
{ "error": { "code": "...", "message": "...", "details": { } } }
```

| HTTP | Code | Meaning |
|---|---|---|
| 404 | `SCORE_NOT_FOUND` | No score matches that triple |
| 409 | `FEEDBACK_ALREADY_GENERATED` | Already completed — pass `force_rerun: true` |
| 409 | `FEEDBACK_GENERATION_IN_PROGRESS` | A run is already going |
| 422 | `SCORE_DATA_INVALID` | Score found but unusable — see `details` |
| 502 | `MONGO_REPOSITORY_ERROR` | Database unreachable |
| 400 | `INVALID_ID` | An id is not a 24-character hex ObjectId |

`SCORE_DATA_INVALID` carries field-level facts rather than a message blob:

```json
{
  "error": {
    "code": "SCORE_DATA_INVALID",
    "message": "This score document is malformed: scoreCompetenciesScores.0.competencyQuantitativeValue — Input should be less than or equal to 100.",
    "details": {
      "error_count": 1,
      "errors": [{
        "field": "scoreCompetenciesScores.0.competencyQuantitativeValue",
        "rule": "less_than_equal",
        "message": "Input should be less than or equal to 100",
        "received": 101
      }]
    }
  }
}
```

It is also returned when a score has fewer than `MIN_COMPETENCIES` (3) competencies.

---

## How a run works

```
POST /scores/run
  └─ ScoreRetrievalService     read the score, validate it, build the request  (synchronous)
  └─ 202 Accepted
  └─ background task → NarrativeFeedbackWorkflow (LangGraph)
       retrieve_descriptions → generate_descriptions → generate_role
         → generate_job_purpose → build_framework → prepare_feedback_context
         → generate_executive_summary → generate_competency_feedback
         → parse_output ─┬─ ok   → verify_groundedness → END
                         └─ fail → END
  └─ StatusManagementService   write the result back to the score document
```

`build_framework` runs a nested per-competency sub-graph
(`select_best → take | generate`), so each competency appears as its own span.

### Proficiency levels

The scoring system uses a **4-level** scale (Foundation / Applied / Advanced / Expert).
The narrative framework uses **3** levels. Each competency therefore carries two values:

- `achieved_level` — the stored level, e.g. `Expert`. This is what a reader sees.
- `framework_level` — the mapped band, e.g. `Advanced`. A lookup key only, used to
  select which framework level description grounds the narrative. Never rendered.

The mapping lives in `LEVEL_TO_FRAMEWORK_BAND` in `domain/narrative_rules.py`. When no
stored level is present, the level is derived from the score: `0` →
*No Proficiency Demonstrated*, `1-33` → Foundation, `34-66` → Applied, `67-100` →
Advanced.

### Tracing

One Langfuse trace per run, with node spans from the official LangGraph callback
handler. Individual LLM calls deliberately get no observation — instead each model
contributes one usage-rollup generation so Langfuse can price the run. `latency_ms`,
`tokens_total` and `groundedness` go out as numeric scores.

Trace metadata includes `description_sources` and `levels_sources` — per-competency
provenance (`db` / `retrieved` / `generated` / `framework` / `disabled`). A competency
with both marked `generated` had **nothing** from your data behind its narrative, which
is the signal to check before trusting the output.

---

## Project layout

```
main.py                      FastAPI app, middleware, startup/shutdown
routers/
  routes.py                  POST /scores/run
  health.py                  GET /health
core/
  settings.py                Env-driven configuration
  edge_errors.py             Typed errors + the error envelope
  tracing.py                 Langfuse client, handler, per-run telemetry
  logging_config.py          Log format and run-id correlation
domain/
  narrative_rules.py         Level bands, mappings, framework defaults
schemas/schemas.py           Request/response and pipeline models
services/
  score_retrieval_service.py Mongo score → pipeline request (validation lives here)
  score_document_builder_service.py  Normalizes the competency list
  narrative_feedback_service.py      Run orchestration and persistence
  narrative_llm_service.py   Facade over the LLM-backed services
  summary_service.py         Executive summary + interpretation calls
  framework_service.py       Job purpose, definitions, proficiency levels
  role_service.py            Role inference
  narrative_artifacts_service.py     Framework/competency artifact loading
  status_management_service.py       Status + result write-back
workflows/
  narrative_feedback_workflow.py     The LangGraph pipeline
prompts/                     System/user prompt templates
repositories/
  mongo_repository.py        Mongo access
  storage_repository.py      Azure Blob artifact access
llm_gateway/client.py        Provider-agnostic LLM client
```

---

## Troubleshooting

**409 on a score you can see is unscored.** `feedbackGenerationStatus` is not tied to
the score data. If a score is re-scored after feedback was generated, the flag and the
old `executiveSummary` survive the rewrite. Clear them, or pass `force_rerun: true`:

```js
db.scores.updateOne(
  { _id: ObjectId("...") },
  { $unset: { feedbackGenerationStatus: "", executiveSummary: "" } }
)
```

**404 on a score that exists.** The lookup ANDs all three ids, so one mismatch returns
nothing. Check the `scoreProjectId` / `scoreAssessmentId` / `scoreUserId` on the
document against what you sent, and confirm `MANAGER_AGENT_MONGO_REGION` and the
database name in `GET /api/v1/health` match the cluster you are browsing.

**Traces appear but there are no node spans.** `langchain` is not installed. Langfuse's
LangGraph handler needs the package itself, not just `langchain-core`.

**Nothing in Langfuse at all.** The trace only opens once a run starts. A request that
fails with 404 or 409 never reaches the background task, so it produces no trace.

**Generic, interchangeable narratives.** Check `levels_sources` in the trace metadata.
`disabled` means `ENRICH_WITH_FRAMEWORK=false`; `generated` across the board usually
means the framework artifacts are not loading — see `GET /api/v1/health`.
