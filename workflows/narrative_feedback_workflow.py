import logging
from collections import Counter
from time import perf_counter
from typing import Any, Awaitable, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from core.settings import Settings
from domain.narrative_rules import (
    BAND_MIN,
    DEFAULT_FRAMEWORK_LEVELS,
    MIN_COMPETENCIES,
    ZERO_LEVEL_LABEL,
    BENCHMARK_TO_FRAMEWORK,
    normalize_role,
    role_similarity,
    strategy_from_competencies,
)
from prompts.narrative_feedback_prompts import strategy_instruction as strategy_instruction_for
from services.narrative_llm_service import NarrativeLLMService
from services.narrative_artifacts_service import NarrativeArtifactsService

logger = logging.getLogger(__name__)

# How much of a single value to show in the step I/O logs before truncating.
_LOG_VALUE_CHARS = 300

# State keys each step reads, so the I/O log shows what actually went in
# rather than the whole accumulated state.
STEP_INPUT_KEYS: dict[str, tuple[str, ...]] = {
    "detect_strategy": ("competencies",),
    "retrieve_descriptions": ("competencies",),
    "generate_descriptions": ("competencies", "descriptions", "description_sources", "request_data"),
    "generate_role": ("request_data", "assessment", "competencies", "descriptions"),
    "generate_job_purpose": ("request_data", "resolved_role", "competencies"),
    "build_framework": ("request_data", "competencies", "descriptions", "resolved_role", "job_purpose"),
    "prepare_feedback_context": ("competencies",),
    "generate_executive_summary": (
        "assessment",
        "request_data",
        "strategy",
        "strategy_instruction",
        "competency_table",
        "benchmarked_count",
    ),
    "generate_competency_feedback": (
        "request_data",
        "competencies",
        "framework_context",
        "strategy_instruction",
    ),
    "parse_output": ("feedback_competencies",),
    "verify_groundedness": ("parse_ok",),
}


def _summarize(value: Any) -> str:
    """Compact, log-safe rendering of a state value."""
    if value is None:
        return "None"
    if isinstance(value, str):
        text = value.replace("\n", "\\n")
        return f'"{text[:_LOG_VALUE_CHARS]}…" ({len(value)} chars)' if len(value) > _LOG_VALUE_CHARS else f'"{text}"'
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        keys = list(value.keys())
        shown = ", ".join(str(k) for k in keys[:8])
        more = f" +{len(keys) - 8} more" if len(keys) > 8 else ""
        return f"dict[{len(keys)}]{{{shown}{more}}}"
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        if items and all(isinstance(i, dict) for i in items):
            first = items[0]
            label = first.get("competency") or first.get("name") or ", ".join(list(first.keys())[:4])
            return f"list[{len(items)}] of dict (e.g. {label})"
        preview = ", ".join(str(i) for i in items[:5])
        more = f" +{len(items) - 5} more" if len(items) > 5 else ""
        return f"list[{len(items)}][{preview}{more}]"
    return f"{type(value).__name__}({str(value)[:_LOG_VALUE_CHARS]})"


def _format_payload(payload: dict[str, Any], keys: tuple[str, ...] | None = None) -> str:
    selected = keys if keys is not None else tuple(payload.keys())
    parts = [
        f"{k}={_summarize(payload.get(k))}"
        for k in selected
        if keys is None or k in payload
    ]
    return " | ".join(parts) if parts else "(nothing)"


class FrameworkItemState(TypedDict, total=False):
    request_data: dict[str, Any]
    competency: dict[str, Any]
    resolved_role: str
    descriptions: dict[str, str]
    job_purpose: str
    selected: dict[str, Any]
    framework_route: str
    framework_examples: str
    levels: dict[str, str]
    level_source: str
    step_sources: dict[str, list[str]]


class AssessmentGraphState(TypedDict, total=False):
    request_data: dict[str, Any]
    assessment: dict[str, Any]
    competencies: list[dict[str, Any]]
    pipeline_trace: list[dict[str, Any]]
    step_sources: dict[str, list[str]]
    strategy: str
    benchmarked_count: int
    descriptions: dict[str, str]
    description_sources: dict[str, str]
    resolved_role: str
    job_purpose: str
    framework_context: dict[str, dict[str, Any]]
    levels_sources: dict[str, str]
    competency_table_lines: list[str]
    competency_table: str
    strategy_instruction: str
    executive_summary: str
    feedback_competencies: list[dict[str, Any]]
    parse_ok: bool
    groundedness_score: float
    groundedness_passed: bool


class NarrativeFeedbackWorkflow:
    def __init__(
        self,
        settings: Settings,
        llm_service: NarrativeLLMService,
        artifacts: NarrativeArtifactsService,
    ) -> None:
        self._settings = settings
        self._llm_service = llm_service
        self._artifacts = artifacts
        self._framework_item_graph = self._build_framework_item_graph()
        self._assessment_graph = self._build_assessment_graph()

    def pipeline_parameters(self) -> dict[str, Any]:
        return {
            "pipeline_version": "v7-inspired",
            "phases": [
                "detect_strategy",
                "retrieve_descriptions",
                "generate_descriptions",
                "generate_role",
                "generate_job_purpose",
                "build_framework",
                "prepare_feedback_context",
                "generate_executive_summary",
                "generate_competency_feedback",
                "parse_output",
                "verify_groundedness",
            ],
            "gates": {
                "min_competencies_per_assessment": MIN_COMPETENCIES,
            },
            "mappings": {
                "benchmark_to_framework": BENCHMARK_TO_FRAMEWORK,
                "score_to_level": {
                    "0": ZERO_LEVEL_LABEL,
                    "1-33": "Foundation",
                    "34-66": "Applied",
                    "67-100": "Advanced",
                },
            },
            "models": {
                "provider": self._settings.llm_provider,
                "primary": self._settings.primary_model_name(),
                "small": self._settings.small_model_name(),
                "framework_job_purpose": self._settings.framework_jobpurpose_model_name(),
                "framework_definition": self._settings.framework_definition_model_name(),
                "framework_proficiency": self._settings.framework_proficiency_model_name(),
            },
            "source_files": {
                "framework_rows": "framework/framework_rows.jsonl",
                "competency_descriptions": "competency/competencies_clean.xlsx",
            },
            "feature_flags": {
                "enrich_with_framework": bool(self._settings.enrich_with_framework),
            },
            "web_search_policy": {
                "role_generation": "role_missing_then_openai_web_search",
                "job_purpose": "organization_required",
                "competency_definition": "organization_required",
                "framework_levels": "organization_required",
                "executive_summary": False,
                "competency_interpretation": False,
            },
        }

    async def run_assessment(
        self,
        request_data: dict[str, Any],
        assessment: dict[str, Any],
        competencies: list[dict[str, Any]],
    ) -> AssessmentGraphState:
        initial_state: AssessmentGraphState = {
            "request_data": request_data,
            "assessment": assessment,
            "competencies": competencies,
            "step_sources": {},
            "pipeline_trace": [],
        }
        logger.info(
            "Pipeline start: assessment=%r competencies=%d role=%r org=%r industry=%r enrich_framework=%s",
            assessment.get("assessment_name"),
            len(competencies),
            request_data.get("role") or "<unset>",
            request_data.get("organization") or "<unset>",
            request_data.get("industry") or "<unset>",
            bool(self._settings.enrich_with_framework),
        )
        started = perf_counter()
        try:
            final_state = await self._assessment_graph.ainvoke(initial_state)
        except Exception:
            logger.exception(
                "Pipeline failed after %.0fms", (perf_counter() - started) * 1000
            )
            raise
        elapsed_ms = (perf_counter() - started) * 1000
        logger.info(
            "Pipeline done in %.0fms: steps=%d feedback=%d groundedness=%.2f",
            elapsed_ms,
            len(final_state.get("pipeline_trace") or []),
            len(final_state.get("feedback_competencies") or []),
            float(final_state.get("groundedness_score") or 0.0),
        )
        return final_state

    async def _run_graph_step(
        self,
        state: AssessmentGraphState,
        step_name: str,
        fn: Callable[[AssessmentGraphState], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        started = perf_counter()
        logger.debug(
            "Step %s ->IN  %s",
            step_name,
            _format_payload(dict(state), STEP_INPUT_KEYS.get(step_name)),
        )
        try:
            updates = await fn(state)
        except Exception:
            logger.exception(
                "Step %s: FAILED after %.0fms (inputs: %s)",
                step_name,
                (perf_counter() - started) * 1000,
                _format_payload(dict(state), STEP_INPUT_KEYS.get(step_name)),
            )
            raise
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        logger.debug("Step %s <-OUT %s", step_name, _format_payload(dict(updates)))
        logger.info("Step %s: ok in %.0fms", step_name, elapsed_ms)
        trace = list(state.get("pipeline_trace") or [])
        trace.append({"step": step_name, "duration_ms": elapsed_ms})
        updates = dict(updates)
        updates["pipeline_trace"] = trace
        return updates

    def _node_step(
        self,
        step_name: str,
        fn: Callable[[AssessmentGraphState], Awaitable[dict[str, Any]]],
    ) -> Callable[[AssessmentGraphState], Awaitable[dict[str, Any]]]:
        async def _wrapped(state: AssessmentGraphState) -> dict[str, Any]:
            return await self._run_graph_step(state, step_name, fn)

        return _wrapped

    @staticmethod
    def _route_framework_item(state: FrameworkItemState) -> str:
        if state.get("framework_route") == "take":
            return "take"
        return "generate"

    @staticmethod
    def _route_after_parse(state: AssessmentGraphState) -> str:
        return "ok" if bool(state.get("parse_ok")) else "fail"

    def _build_framework_item_graph(self) -> Any:
        graph = StateGraph(FrameworkItemState)
        graph.add_node("select_best", self._fw_select_best)
        graph.add_node("take", self._fw_take)
        graph.add_node("generate", self._fw_generate)
        graph.add_edge(START, "select_best")
        graph.add_conditional_edges(
            "select_best",
            self._route_framework_item,
            {
                "take": "take",
                "generate": "generate",
            },
        )
        graph.add_edge("take", END)
        graph.add_edge("generate", END)
        return graph.compile()

    def _build_assessment_graph(self) -> Any:
        graph = StateGraph(AssessmentGraphState)
        graph.add_node("detect_strategy", self._node_step("detect_strategy", self._graph_detect_strategy))
        graph.add_node("retrieve_descriptions", self._node_step("retrieve_descriptions", self._graph_retrieve_descriptions))
        graph.add_node("generate_descriptions", self._node_step("generate_descriptions", self._graph_generate_descriptions))
        graph.add_node("generate_role", self._node_step("generate_role", self._graph_generate_role))
        graph.add_node("generate_job_purpose", self._node_step("generate_job_purpose", self._graph_generate_job_purpose))
        graph.add_node("build_framework", self._node_step("build_framework", self._graph_build_framework))
        graph.add_node("prepare_feedback_context", self._node_step("prepare_feedback_context", self._graph_prepare_feedback_context))
        graph.add_node("generate_executive_summary", self._node_step("generate_executive_summary", self._graph_generate_executive_summary))
        graph.add_node("generate_competency_feedback", self._node_step("generate_competency_feedback", self._graph_generate_competency_feedback))
        graph.add_node("parse_output", self._node_step("parse_output", self._graph_parse_output))
        graph.add_node("verify_groundedness", self._node_step("verify_groundedness", self._graph_verify_groundedness))

        graph.add_edge(START, "detect_strategy")
        graph.add_edge("detect_strategy", "retrieve_descriptions")
        graph.add_edge("retrieve_descriptions", "generate_descriptions")
        graph.add_edge("generate_descriptions", "generate_role")
        graph.add_edge("generate_role", "generate_job_purpose")
        graph.add_edge("generate_job_purpose", "build_framework")
        graph.add_edge("build_framework", "prepare_feedback_context")
        graph.add_edge("prepare_feedback_context", "generate_executive_summary")
        graph.add_edge("generate_executive_summary", "generate_competency_feedback")
        graph.add_edge("generate_competency_feedback", "parse_output")
        graph.add_conditional_edges(
            "parse_output",
            self._route_after_parse,
            {
                "ok": "verify_groundedness",
                "fail": END,
            },
        )
        graph.add_edge("verify_groundedness", END)
        return graph.compile()

    async def _fw_select_best(self, state: FrameworkItemState) -> dict[str, Any]:
        competency = state["competency"]
        resolved_role = state.get("resolved_role") or ""
        hits = self._artifacts.lookup_framework_rows(str(competency["competency"]))
        selected: dict[str, Any] = {}
        route = "generate"
        examples = ""

        if hits:
            hits_sorted = sorted(
                hits,
                key=lambda h: role_similarity(resolved_role, h.get("role")),
                reverse=True,
            )
            exact = next(
                (
                    h
                    for h in hits_sorted
                    if normalize_role(h.get("role")) == normalize_role(resolved_role)
                ),
                None,
            )
            selected = exact or hits_sorted[0]
            route = "take" if exact is not None else "generate"
            if selected:
                examples = (
                    f"Foundation: {selected.get('level_foundation') or ''}\n"
                    f"Applied: {selected.get('level_applied') or ''}\n"
                    f"Advanced: {selected.get('level_advanced') or ''}"
                )

        logger.debug(
            "  framework[%s]: %d row(s) matched, route=%s, matched_role=%r (target role=%r)",
            competency["competency"],
            len(hits),
            route,
            selected.get("role") if selected else None,
            resolved_role or "<unset>",
        )
        return {
            "selected": selected,
            "framework_route": route,
            "framework_examples": examples,
        }

    async def _fw_take(self, state: FrameworkItemState) -> dict[str, Any]:
        selected = state.get("selected") or {}
        levels = {
            "Foundation": selected.get("level_foundation") or DEFAULT_FRAMEWORK_LEVELS["Foundation"],
            "Applied": selected.get("level_applied") or DEFAULT_FRAMEWORK_LEVELS["Applied"],
            "Advanced": selected.get("level_advanced") or DEFAULT_FRAMEWORK_LEVELS["Advanced"],
        }
        return {
            "levels": levels,
            "level_source": "framework",
        }

    async def _fw_generate(self, state: FrameworkItemState) -> dict[str, Any]:
        request_data = state["request_data"]
        competency = state["competency"]
        resolved_role = state.get("resolved_role") or "Not specified"
        descriptions = state.get("descriptions") or {}
        job_purpose = state.get("job_purpose") or ""
        examples = state.get("framework_examples") or ""
        step_sources = dict(state.get("step_sources") or {})

        levels, sources = await self._llm_service.generate_framework_levels(
            industry=str(request_data.get("industry") or "Not Provided"),
            role=resolved_role,
            competency=competency["competency"],
            definition=descriptions.get(competency["competency"], ""),
            job_purpose=job_purpose,
            organization=request_data.get("organization"),
            examples=examples,
        )
        if sources:
            step_sources.setdefault("build_framework", []).extend(sources)

        logger.debug(
            "  framework[%s]: levels generated by LLM (%s), web sources=%d",
            competency["competency"],
            "few-shot from framework row" if examples else "no example",
            len(sources or []),
        )
        return {
            "levels": levels,
            "level_source": "generated+fewshot" if examples else "generated",
            "step_sources": step_sources,
        }

    async def _graph_detect_strategy(self, state: AssessmentGraphState) -> dict[str, Any]:
        strategy, benchmarked_count = strategy_from_competencies(state["competencies"])
        logger.info(
            "Strategy=%s (%d of %d competencies benchmarked)",
            strategy,
            benchmarked_count,
            len(state["competencies"]),
        )
        return {
            "strategy": strategy,
            "benchmarked_count": benchmarked_count,
            "strategy_instruction": strategy_instruction_for(strategy),
        }

    async def _graph_retrieve_descriptions(self, state: AssessmentGraphState) -> dict[str, Any]:
        descriptions: dict[str, str] = {}
        description_sources: dict[str, str] = {}
        for comp in state["competencies"]:
            db_desc = str(comp.get("description") or "").strip()
            if db_desc:
                descriptions[comp["competency"]] = db_desc
                description_sources[comp["competency"]] = "db"
                continue
            desc = self._artifacts.lookup_competency_description(comp["competency"])
            if desc:
                descriptions[comp["competency"]] = desc
                description_sources[comp["competency"]] = "retrieved"
            else:
                descriptions[comp["competency"]] = ""
                description_sources[comp["competency"]] = "missing"
        counts = Counter(description_sources.values())
        logger.info(
            "Descriptions resolved: db=%d artifact=%d missing=%d",
            counts.get("db", 0),
            counts.get("retrieved", 0),
            counts.get("missing", 0),
        )
        if counts.get("missing"):
            logger.debug(
                "  no description found for: %s",
                ", ".join(k for k, v in description_sources.items() if v == "missing"),
            )
        return {
            "descriptions": descriptions,
            "description_sources": description_sources,
        }

    async def _graph_generate_descriptions(self, state: AssessmentGraphState) -> dict[str, Any]:
        request_data = state["request_data"]
        descriptions = dict(state.get("descriptions") or {})
        description_sources = dict(state.get("description_sources") or {})
        step_sources = dict(state.get("step_sources") or {})

        for comp in state["competencies"]:
            if description_sources.get(comp["competency"]) == "db":
                continue  # DB-provided description is authoritative; no LLM generation needed
            retrieved_example = descriptions.get(comp["competency"])
            generated_desc, sources = await self._llm_service.generate_competency_definition(
                role=None,
                job_purpose="",
                competency=comp["competency"],
                organization=request_data.get("organization"),
                example=retrieved_example,
            )
            descriptions[comp["competency"]] = generated_desc or descriptions.get(comp["competency"], "")
            description_sources[comp["competency"]] = "generated:example" if retrieved_example else "generated"
            if sources:
                step_sources.setdefault("generate_descriptions", []).extend(sources)

        counts = Counter(description_sources.values())
        logger.info(
            "Descriptions generated by LLM: %d (kept from db: %d)",
            counts.get("generated", 0) + counts.get("generated:example", 0),
            counts.get("db", 0),
        )
        return {
            "descriptions": descriptions,
            "description_sources": description_sources,
            "step_sources": step_sources,
        }

    async def _graph_generate_role(self, state: AssessmentGraphState) -> dict[str, Any]:
        request_data = state["request_data"]
        role_value = request_data.get("role")
        if role_value and str(role_value).strip().lower() != "not specified":
            logger.info("Role taken from request: %r (no LLM call)", str(role_value).strip())
            return {"resolved_role": str(role_value).strip()}
        logger.info("Role missing from request; inferring from competencies via LLM")

        descriptions = state.get("descriptions") or {}
        assessment = state["assessment"]
        payload = {
            assessment["assessment_name"]: [
                {
                    "Competency": comp["competency"],
                    "Competency Description": descriptions.get(comp["competency"], ""),
                }
                for comp in state["competencies"]
            ]
        }
        generated_role, sources = await self._llm_service.generate_role_from_competencies(
            payload,
            request_data.get("organization"),
        )
        step_sources = dict(state.get("step_sources") or {})
        if sources:
            step_sources.setdefault("generate_role", []).extend(sources)
        logger.info("Role inferred: %r (web sources=%d)", generated_role, len(sources or []))
        return {
            "resolved_role": generated_role,
            "step_sources": step_sources,
        }

    async def _graph_generate_job_purpose(self, state: AssessmentGraphState) -> dict[str, Any]:
        request_data = state["request_data"]
        resolved_role = state.get("resolved_role") or "Not specified"
        job_purpose_text, sources = await self._llm_service.generate_job_purpose(
            industry=str(request_data.get("industry") or "Not Provided"),
            seniority=str(request_data.get("seniority") or "Not Provided"),
            role=resolved_role,
            competencies=[c["competency"] for c in state["competencies"]],
            organization=request_data.get("organization"),
        )
        step_sources = dict(state.get("step_sources") or {})
        if sources:
            step_sources.setdefault("generate_job_purpose", []).extend(sources)
        logger.info(
            "Job purpose generated for role=%r: %d chars, web sources=%d",
            resolved_role,
            len(job_purpose_text or ""),
            len(sources or []),
        )
        return {
            "job_purpose": job_purpose_text,
            "step_sources": step_sources,
        }

    async def _graph_build_framework(self, state: AssessmentGraphState) -> dict[str, Any]:
        request_data = state["request_data"]
        descriptions = state.get("descriptions") or {}
        resolved_role = state.get("resolved_role") or "Not specified"
        job_purpose = state.get("job_purpose") or ""
        step_sources = dict(state.get("step_sources") or {})
        framework_context: dict[str, dict[str, Any]] = {}
        levels_sources: dict[str, str] = {}

        if not self._settings.enrich_with_framework:
            for comp in state["competencies"]:
                framework_context[comp["competency"]] = {
                    "definition": descriptions.get(comp["competency"], ""),
                    "levels": dict(DEFAULT_FRAMEWORK_LEVELS),
                    "job_purpose": job_purpose,
                    "framework_role": None,
                }
                levels_sources[comp["competency"]] = "disabled"

            logger.info(
                "Framework enrichment disabled; using default levels for %d competencies",
                len(state["competencies"]),
            )
            return {
                "framework_context": framework_context,
                "levels_sources": levels_sources,
                "step_sources": step_sources,
            }

        for comp in state["competencies"]:
            framework_state: FrameworkItemState = {
                "request_data": request_data,
                "competency": comp,
                "resolved_role": resolved_role,
                "descriptions": descriptions,
                "job_purpose": job_purpose,
                "step_sources": step_sources,
            }
            framework_out = await self._framework_item_graph.ainvoke(framework_state)
            selected = framework_out.get("selected") or {}
            levels = framework_out.get("levels") or dict(DEFAULT_FRAMEWORK_LEVELS)
            levels_sources[comp["competency"]] = str(framework_out.get("level_source") or "generated")
            step_sources = dict(framework_out.get("step_sources") or step_sources)

            framework_context[comp["competency"]] = {
                "definition": descriptions.get(comp["competency"], ""),
                "levels": levels,
                "job_purpose": selected.get("job_purpose") or job_purpose,
                "framework_role": selected.get("role"),
            }

        counts = Counter(levels_sources.values())
        logger.info(
            "Framework built for %d competencies: from_framework=%d generated_fewshot=%d generated=%d",
            len(framework_context),
            counts.get("framework", 0),
            counts.get("generated+fewshot", 0),
            counts.get("generated", 0),
        )
        return {
            "framework_context": framework_context,
            "levels_sources": levels_sources,
            "step_sources": step_sources,
        }

    async def _graph_prepare_feedback_context(self, state: AssessmentGraphState) -> dict[str, Any]:
        competency_table_lines: list[str] = []
        for comp in state["competencies"]:
            comp_name = comp["competency"]
            achieved = comp["achieved_level"]
            score = float(comp["score_percent"])
            benchmark = comp.get("benchmark_level")
            zero_case = achieved.lower() == ZERO_LEVEL_LABEL.lower() or score == 0
            if benchmark:
                benchmark_min = BAND_MIN.get(benchmark, BAND_MIN["Applied"])
                gap_percent = score - float(benchmark_min)
                meets = "MEETS" if score >= benchmark_min else "BELOW"
                if zero_case:
                    competency_table_lines.append(
                        f"{comp_name}: assessed 0% ({ZERO_LEVEL_LABEL}), benchmark {benchmark}, gap {gap_percent:+.0f}%, {meets}"
                    )
                else:
                    competency_table_lines.append(
                        f"{comp_name}: achieved {achieved} ({score:.0f}%), benchmark {benchmark}, gap {gap_percent:+.0f}%, {meets}"
                    )
            else:
                if zero_case:
                    competency_table_lines.append(
                        f"{comp_name}: assessed 0% ({ZERO_LEVEL_LABEL}), no benchmark set"
                    )
                else:
                    competency_table_lines.append(
                        f"{comp_name}: achieved {achieved} ({score:.0f}%), no benchmark set"
                    )

        logger.info("Feedback context: %d competency line(s) prepared", len(competency_table_lines))
        for line in competency_table_lines:
            logger.debug("  %s", line)
        return {
            "competency_table_lines": competency_table_lines,
            "competency_table": "\n".join(f"  {line}" for line in competency_table_lines),
        }

    async def _graph_generate_executive_summary(self, state: AssessmentGraphState) -> dict[str, Any]:
        assessment = state["assessment"]
        request_data = state["request_data"]
        strategy = state.get("strategy") or "mixed"
        benchmarked_count = int(state.get("benchmarked_count") or 0)
        competencies = state["competencies"]

        fallback_summary = (
            f"Assessment '{assessment['assessment_name']}' covers {len(competencies)} competencies with "
            f"{benchmarked_count} benchmarked; strategy is {strategy}."
        )
        try:
            summary = await self._llm_service.generate_executive_summary(
                assessment_name=assessment["assessment_name"],
                strategy_instruction=state.get("strategy_instruction") or "",
                competency_table=state.get("competency_table") or "",
                organization=request_data.get("organization"),
            )
        except Exception as exc:
            if not self._settings.llm_fallback_to_rules:
                logger.exception("Executive summary generation failed and fallback is disabled")
                raise
            logger.warning(
                "Executive summary generation failed (%s: %s); using rule-based fallback",
                type(exc).__name__,
                exc,
            )
            summary = fallback_summary
        else:
            logger.info("Executive summary generated by LLM: %d chars", len(summary or ""))

        return {"executive_summary": summary}

    @staticmethod
    def _result_line(comp: dict[str, Any]) -> str:
        """Notebook `_build_competency_facts['result_line']`."""
        achieved = str(comp.get("achieved_level") or "")
        score = float(comp.get("score_percent", 0.0))
        benchmark = comp.get("benchmark_level")
        if benchmark:
            benchmark_min = BAND_MIN.get(benchmark, BAND_MIN["Applied"])
            gap = score - float(benchmark_min)
            meets = "MEETS" if score >= benchmark_min else "BELOW"
            return f"achieved {achieved} ({score:.0f}%), benchmark {benchmark}, gap {gap:+.0f}%, {meets}"
        return f"achieved {achieved} ({score:.0f}%), no benchmark"

    @staticmethod
    def _level_descriptions_for(comp: dict[str, Any], levels: dict[str, str]) -> dict[str, str]:
        """Only the levels the result actually references (achieved + benchmark), as the
        notebook does - never the whole ladder."""
        wanted = [str(comp.get("achieved_level") or "")]
        benchmark = comp.get("benchmark_level")
        if benchmark:
            wanted.append(BENCHMARK_TO_FRAMEWORK.get(str(benchmark), str(benchmark)))
        selected: dict[str, str] = {}
        seen: set[str] = set()
        for level in wanted:
            if not level or level.lower() in seen:
                continue
            seen.add(level.lower())
            description = levels.get(level) or next(
                (d for k, d in levels.items() if k.lower() == level.lower()), ""
            )
            if description:
                selected[level] = description
        return selected

    async def _graph_generate_competency_feedback(self, state: AssessmentGraphState) -> dict[str, Any]:
        framework_context = state.get("framework_context") or {}
        request_data = state["request_data"]
        organization = request_data.get("organization")
        instruction = state.get("strategy_instruction") or ""
        feedback_competencies: list[dict[str, Any]] = []
        sources_used: list[str] = []

        for comp in state["competencies"]:
            name = comp["competency"]
            score = float(comp.get("score_percent", 0.0))
            achieved_level = str(comp.get("achieved_level") or "")
            benchmark_level = comp.get("benchmark_level")
            context = framework_context.get(name) or {}
            definition = context.get("definition", "")
            result_line = self._result_line(comp)

            if benchmark_level:
                relation = f"Achieved {achieved_level}, benchmark set at {benchmark_level}"
            else:
                relation = f"Achieved {achieved_level}, no benchmark set"

            interpretation = (
                f"In the competency of {name}, the employee has reached "
                f"a {achieved_level} level of proficiency based on this assessment's evidence."
            )
            source = "template"
            if score > 0:
                try:
                    benchmark_position, generated = await self._llm_service.generate_interpretation(
                        competency=name,
                        result_line=result_line,
                        definition=definition,
                        level_descriptions=self._level_descriptions_for(
                            comp, context.get("levels") or {}
                        ),
                        strategy_instruction=instruction,
                        organization=organization,
                    )
                    if generated:
                        interpretation = generated
                        source = "llm"
                    if benchmark_position:
                        relation = benchmark_position
                except Exception as exc:
                    if not self._settings.llm_fallback_to_rules:
                        logger.exception(
                            "Interpretation failed for %r and fallback is disabled", name
                        )
                        raise
                    source = "fallback"
                    logger.warning(
                        "Interpretation failed for %r (%s: %s); using template fallback",
                        name,
                        type(exc).__name__,
                        exc,
                    )

            if score == 0:
                interpretation = (
                    "This competency was assessed and scored 0% in this assessment, "
                    "indicating no proficiency was demonstrated in the observed evidence "
                    "for this competency."
                )
                source = "zero-score"

            feedback_competencies.append(
                {
                    "name": name,
                    "achieved_level": achieved_level,
                    "score_percent": score,
                    "benchmark_position": relation,
                    "interpretation": interpretation,
                    "definition": definition,
                }
            )
            sources_used.append(source)
            logger.debug(
                "  interpretation[%s]: score=%.0f%% achieved=%s benchmark=%s levels_in_prompt=%d source=%s",
                name,
                score,
                achieved_level or "<unset>",
                benchmark_level or "<none>",
                len(self._level_descriptions_for(comp, context.get("levels") or {})),
                source,
            )

        counts = Counter(sources_used)
        logger.info(
            "Competency feedback written for %d competencies: llm=%d fallback=%d zero_score=%d",
            len(feedback_competencies),
            counts.get("llm", 0),
            counts.get("fallback", 0),
            counts.get("zero-score", 0),
        )
        return {"feedback_competencies": feedback_competencies}

    async def _graph_parse_output(self, state: AssessmentGraphState) -> dict[str, Any]:
        feedback_competencies = state.get("feedback_competencies") or []
        parse_ok = bool(feedback_competencies)
        if not parse_ok:
            logger.error("Parse gate FAILED: no competency feedback produced; pipeline will stop here")
        else:
            logger.info("Parse gate passed: %d competency block(s)", len(feedback_competencies))
        return {"parse_ok": parse_ok}

    async def _graph_verify_groundedness(self, state: AssessmentGraphState) -> dict[str, Any]:
        parse_ok = bool(state.get("parse_ok"))
        score = 1.0 if parse_ok else 0.0
        # NOTE: placeholder gate. Claim-level decomposition is not implemented yet, so the
        # score only mirrors parse_ok and is NOT a real groundedness measurement.
        logger.warning(
            "Groundedness check is a placeholder (mirrors parse_ok): score=%.2f passed=%s",
            score,
            parse_ok,
        )
        return {
            "groundedness_score": score,
            "groundedness_passed": parse_ok,
        }
