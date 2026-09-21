# Minimal API Template

## Structure

- `main.py`: FastAPI app entrypoint.
- `routers/health.py`: Health endpoint.
- `routers/narrative_feedback.py`: Narrative feedback async endpoints.
- `core/settings.py`: Environment-driven runtime configuration.
- `llm/client.py`: LLM client abstraction and provider factory.
- `prompts/narrative_feedback_prompts.py`: Prompt templates and render helpers.
- `services/repositories/storage_repository.py`: Shared cloud object storage helper.
- `services/run_service.py`: In-memory run service with optional cloud persistence under `runs/`.
- `services/narrative_artifacts_service.py`: Index/artifact service and in-memory lookup service.
- `requirements.txt`: Minimal API dependencies.

## Environment Variables

The app accepts both styles:

- API-prefixed variables (for example `MANAGER_AGENT_LLM_PROVIDER`)
- Notebook-style variables (for example `PROVIDER`, `OPENAI_MODEL`)

- `MANAGER_AGENT_LLM_PROVIDER`: `openai` (default), `mock`, or `anthropic`
- `PROVIDER`: notebook alias for provider selection
- `MANAGER_AGENT_LLM_MODEL`: generic fallback model name, default `gpt-5.4`
- `OPENAI_MODEL`: notebook alias for OpenAI primary model
- `SMALL_OPENAI_MODEL`: notebook small-model alias used for summary, interpretation, and IDP micro-generations
- `ANTHROPIC_MODEL`: notebook alias for Anthropic primary model
- `MANAGER_AGENT_LLM_TEMPERATURE`: float, default `0.3`
- `TEMPERATURE`: notebook alias for base temperature
- `MANAGER_AGENT_LLM_MAX_TOKENS_SUMMARY`: int, default `400`
- `MANAGER_AGENT_LLM_MAX_TOKENS_INTERPRETATION`: int, default `2000`
- `MANAGER_AGENT_LLM_TIMEOUT_SECONDS`: float, default `20`
- `MANAGER_AGENT_LLM_FALLBACK_TO_RULES`: `true`/`false`, default `true`
- `MANAGER_AGENT_LLM_WEB_SEARCH_SUMMARY`: `true`/`false`, default `false`
- `MANAGER_AGENT_LLM_WEB_SEARCH_INTERPRETATION`: `true`/`false`, default `false`
- `MANAGER_AGENT_LLM_WEB_SEARCH_ROLE_GENERATION`: `true`/`false`, default `true`
- `MANAGER_AGENT_LLM_WEB_SEARCH_JOB_PURPOSE`: `true`/`false`, default `true` (used only when organization is provided)
- `MANAGER_AGENT_LLM_WEB_SEARCH_COMPETENCY_DEFINITION`: `true`/`false`, default `true` (used only when organization is provided)
- `MANAGER_AGENT_LLM_WEB_SEARCH_FRAMEWORK_LEVELS`: `true`/`false`, default `true` (used only when organization is provided)
- `MANAGER_AGENT_OPENAI_API_KEY`: optional; falls back to `OPENAI_API_KEY`
- `MANAGER_AGENT_ANTHROPIC_API_KEY`: optional; falls back to `ANTHROPIC_API_KEY`
- `MANAGER_AGENT_FRAMEWORK_JOBPURPOSE_MODEL` / `FRAMEWORK_JOBPURPOSE_MODEL`: model for job purpose generation
- `MANAGER_AGENT_FRAMEWORK_DEFINITION_MODEL` / `FRAMEWORK_DEFINITION_MODEL`: model for competency definition generation
- `MANAGER_AGENT_FRAMEWORK_PROFICIENCY_MODEL` / `FRAMEWORK_PROFICIENCY_MODEL`: model for framework-level generation
- `MANAGER_AGENT_ENRICH_WITH_FRAMEWORK` / `ENRICH_WITH_FRAMEWORK`: enables/disables framework enrichment phase
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`: notebook-compatible telemetry env vars loaded by settings
- `MANAGER_AGENT_ARTIFACT_BUCKET_URI` / `TARGET_BUCKET_URI`: optional cloud prefix (for example `az://manager-agent/feedback-artifacts`)
- `MANAGER_AGENT_ARTIFACT_RELEASE_VERSION` / `RELEASE_VERSION`: optional fixed release version (if omitted, `latest.json` is used)
- `MANAGER_AGENT_ARTIFACT_LOCAL_CACHE_DIR`: local cache for downloaded artifacts, default `.cache/manager_agent_artifacts`
- `MANAGER_AGENT_AZURE_STORAGE_CONNECTION_STRING` / `AZURE_CONNECTION_STRING`: Azure connection string for blob access
- `AZURE_STORAGE_CONNECTION_STRING` / `JD_STORAGE_AZURELINK`: additional accepted aliases for Azure connection string
- `MANAGER_AGENT_RUN_STORAGE_PREFIX` / `RUN_STORAGE_PREFIX`: cloud prefix used for persisted run snapshots, default `runs`
- `MANAGER_AGENT_PERSIST_RUNS_TO_STORAGE` / `PERSIST_RUNS_TO_STORAGE`: `true`/`false`, default `true`

## Pipeline (Notebook-Aligned)

The `narrative-feedback` run processor now follows a detailed, phase-based pipeline inspired by
`feedback_agent_pipeline_v6_2.ipynb`.

Data sources are resolved notebook-style from published artifacts:

- `framework/framework_rows.jsonl` for framework retrieval
- `competency/competencies_clean.xlsx` for competency description lookup
- `idp/Validated IDP.xlsx` and `idp/training_recommendations_with_competency_type___ 4 sep.xlsx`
	for education recommendations

Resolution order:

1. Storage account release (`latest.json` or explicit release version)
2. Local cache (`MANAGER_AGENT_ARTIFACT_LOCAL_CACHE_DIR`)
3. Workspace fallback files (existing local files)

At API startup:

1. Artifact objects are loaded from storage to local cache and then into in-memory maps.
2. Existing run snapshots are loaded from `runs/` (or configured run prefix) into the in-memory run repository.
3. New/updated run states are persisted back to storage under the configured run prefix.

### Phases

1. `detect_strategy`
2. `retrieve_descriptions`
3. `generate_descriptions`
4. `generate_role`
5. `generate_job_purpose`
6. `build_framework`
7. `prepare_feedback_context`
8. `generate_executive_summary`
9. `generate_competency_feedback`
10. `parse_output`
11. `verify_groundedness`
12. `detect_idp_gaps`
13. `build_three_es`
14. `build_roadmap`

### Web Search Parity

Web search routing now follows notebook behavior:

1. Role generation: web search enabled (provider support required).
2. Job purpose generation: web search enabled only when organization exists.
3. Competency definition generation: web search enabled only when organization exists.
4. Framework levels generation: web search enabled only when organization exists.
5. Executive summary and competency interpretation: web search disabled (notebook parity in this API path).

Note: Web search is currently supported only on the OpenAI provider path.

### Core Parameters

- `min_competencies_per_assessment`: `3`
- `idp_score_range`: `[0.0, 70.0)`
- score-to-level mapping:
	- `0` -> `No Proficiency Demonstrated`
	- `1-33` -> `Foundation`
	- `34-66` -> `Applied`
	- `67-100` -> `Advanced`
- benchmark normalization:
	- `Foundation -> Foundation`
	- `Intermediate -> Applied`
	- `Applied -> Applied`
	- `Advanced -> Advanced`
	- `Expert -> Advanced`
- roadmap scheduling:
	- type priority: `technical`, `behavioral`, `leadership`
	- active block months: `2`
	- pause months: `1`
	- duration-by-gap: `{1:1, 2:2, 3:3}`

### Run Result Metadata

Completed run results include `meta` with:

- `pipeline_version`
- `parameters` (full pipeline parameter block)
- `steps` (per-step duration trace)
- `framework_rows_loaded`
- `competency_descriptions_loaded`
- `validated_training_competencies`
- `fallback_training_competencies`
- `artifact_source` (bucket/release/cache/errors)
- `web_search_sources` (step-level collected citations when available)
- `generated_at`

## Run

From this `api` folder:

```powershell
pip install -r requirements.txt
uvicorn main:app --reload
```

Or from workspace root:

```powershell
pip install -r api/requirements.txt
uvicorn api.main:app --reload
```
