"""Feedback-generation prompts.

Ported verbatim from `feedback_agent_pipeline_v6_2.ipynb` (section: v7 Phase 4 nodes).
Do not paraphrase these strings - the wording is the product contract.
"""

from typing import Any

# ── Assessment scoring strategies (notebook: STRATEGY_* ) ──────────────────

STRATEGY_BENCHMARKED = (
    "This assessment HAS benchmarks.\n"
    "Strength = meets or exceeds benchmark (gap >= 0).\n"
    "Development area = below benchmark (gap < 0).\n"
    "Anchor each 'benchmark_position' on the benchmark level. For score 0, start from a Foundation baseline."
)

STRATEGY_UNBENCHMARKED = (
    "This assessment has NO benchmarks.\n"
    "Strength = Advanced level (score >= 67%).\n"
    "Development area = Foundation level (score < 34%).\n"
    "Applied level = acknowledge as transition state.\n"
    "Anchor each 'benchmark_position' on the achieved level within the 3-level scale (Foundation < Applied < Advanced; there is no Expert level), "
    "For score 0, start from a Foundation baseline."
)

STRATEGY_MIXED = (
    "This assessment has SOME benchmarked and SOME non-benchmarked competencies.\n"
    "For benchmarked: strength = meets/exceeds benchmark, development area = below.\n"
    "For non-benchmarked: strength = Advanced, development area = Foundation.\n"
    "Make clear in each 'benchmark_position' whether that competency has a benchmark."
)

STRATEGY_INSTRUCTIONS = {
    "benchmarked": STRATEGY_BENCHMARKED,
    "unbenchmarked": STRATEGY_UNBENCHMARKED,
    "mixed": STRATEGY_MIXED,
}


def strategy_instruction(strategy: str) -> str:
    return STRATEGY_INSTRUCTIONS.get(str(strategy).strip().lower(), STRATEGY_MIXED)


# ── Few-shot worked examples (style reference for the interpretation narrative) ──
# Gold-standard interpretations. The model imitates their STRUCTURE and tone, never their content.
FEW_SHOT_EXAMPLES = [
    {
        "name": "Passion",
        "definition": "Ability to demonstrate genuine enthusiasm, commitment, and proactive pursuit of meaningful work.",
        "achieved_level": "Foundation",
        "score_percent": 33,
        "benchmark_position": "Achieved Foundation, one level below the Applied benchmark",
        "interpretation": "In the competency of Passion, the candidate has reached a Foundation level of proficiency, positioning them one level below the expected benchmark. The candidate shows a genuine connection to their work and can identify aspects of their professional role that they find personally meaningful. At this level, motivation is present but tends to be individually focused and activated within familiar or well-suited conditions, rather than consistently self-generated across situations. This reflects an emerging stage of engagement, where enthusiasm exists but has not yet extended toward a wider commitment to collective goals or organizational purpose.",
    },
    {
        "name": "Digital Mindset",
        "definition": "Ability to embrace technology, innovation, and continuous learning to improve outcomes and enable future organizational success.",
        "achieved_level": "Foundation",
        "score_percent": 66,
        "benchmark_position": "Achieved Foundation, one level below the Applied benchmark",
        "interpretation": "In the competency of Digital Mindset, the candidate has reached a Foundation level of proficiency, positioning them one level below the expected benchmark. The candidate demonstrates curiosity about emerging technologies and an awareness of their potential to enhance work processes. Engagement with digital tools remains primarily exploratory and individually focused - characteristic of an active learning phase centered on adopting and becoming familiar with tools, rather than applying technology in a collaborative, team-wide, or organizationally impactful manner.",
    },
    {
        "name": "Customer Centricity",
        "definition": "Ability to understand customer and stakeholder needs and translate those insights into meaningful actions that create value.",
        "achieved_level": "Advanced",
        "score_percent": 100,
        "benchmark_position": "Achieved Advanced, meeting the Advanced benchmark",
        "interpretation": "In the competency of Customer Centricity, the candidate has attained an Advanced level of proficiency, reflecting a sophisticated and forward-thinking approach to customer engagement. Rather than responding only to expressed needs, the candidate takes a proactive stance - anticipating evolving customer expectations and shaping solutions that deliver lasting value over the long term. At this level, the candidate balances competing priorities across customers, stakeholders, and the organization, delivering outcomes that are mutually beneficial and strategically aligned. Customer-centric thinking is connected to tangible business outcomes, operating not merely as a service orientation but as a strategic driver of continuous improvement and broader organizational performance.",
    },
]


def format_few_shot_examples(examples: list[dict[str, Any]] = FEW_SHOT_EXAMPLES) -> str:
    """Render the worked examples as a plain-text block for the system prompt."""
    blocks = []
    for ex in examples:
        blocks.append(
            f"Competency: {ex['name']}\n"
            f"Definition: {ex['definition']}\n"
            f"Result: achieved {ex['achieved_level']} ({ex['score_percent']:.0f}%)\n"
            f"benchmark_position: {ex['benchmark_position']}\n"
            f"interpretation: {ex['interpretation']}"
        )
    return "\n\n---\n\n".join(blocks)


V7_FEWSHOT_BLOCK = format_few_shot_examples()


# ── Prompts ────────────────────────────────────────────────────────────────
V7_FEEDBACK_SYS = (
    "You are writing one competency interpretation for a report that is delivered TO the "
    "employee's manager and is ABOUT the employee. Always refer to the assessed person as "
    "'the employee' — never 'the person', 'the candidate', 'you', or a name.\n"
    "Work ONLY from the facts provided (the assessment result and the competency framework). "
    "Do not invent a job role, seniority, or organisation-specific facts. You may name the "
    "employing organisation given in the context where the framework facts support it.\n"
    "Follow occupational-assessment best practice: be behaviourally specific and evidence-based, "
    "describe observable capability rather than personality, stay balanced and non-judgemental, "
    "and frame the interpretation constructively and developmentally (what the employee "
    "demonstrates at this proficiency and what it enables), without blaming or labelling.\n"
    "Preserve the concrete, specific details that appear in the framework level descriptions "
    "(named entities, priorities, outcome terms) instead of generalising them into vague "
    "phrases such as 'related teams where appropriate'.\n"
    "Narrative style — match the WORKED EXAMPLES below:\n"
    "  • Open the interpretation with: 'In the competency of <competency>, the employee has "
    "reached/attained a <achieved band> level of proficiency, positioning them <relationship to "
    "the benchmark>.' Use 'reached … one level below the … benchmark' when below, and 'attained "
    "… meeting the … benchmark' when the benchmark is met (omit the benchmark clause when there "
    "is no benchmark).\n"
    "  • Then, in a few flowing sentences, describe what the employee demonstrably does at this "
    "proficiency: the observable behaviours, where the capability is currently focused (e.g. "
    "individually focused, exploratory, proactive/strategic), and — for below-benchmark results — "
    "what has not yet extended or developed, framed as an emerging or active-learning stage "
    "rather than a deficit.\n"
    "  • Keep the tone constructive and developmental; imitate the examples' STRUCTURE and tone, "
    "but NEVER copy their wording or content — write from the given competency's own facts.\n"
    "  • The worked examples say 'the candidate'; in YOUR output always write 'the employee' "
    "instead.\n\n"
    "WORKED EXAMPLES (imitate the structure; never reuse the content):\n"
    + V7_FEWSHOT_BLOCK
)

V7_COMP_USER = (
    "Organization: {organization}\n"
    "Competency: {competency}\n"
    "Assessment result: {result_line}\n\n"
    "Framework facts:\n{facts}\n\n"
    "Scoring context: {strategy_instruction}\n\n"
    "Produce the structured competency report. 'benchmark_position' = ONE short sentence in the "
    "style of the worked examples (e.g. 'Achieved Foundation, one level below the Applied "
    "benchmark' / 'Achieved Advanced, meeting the Advanced benchmark'). "
    "'interpretation' = a full, constructive narrative in the SAME STYLE as the worked examples: "
    "open with 'In the competency of {competency}, the employee has reached/attained a <band> "
    "level of proficiency, positioning them <relationship to the benchmark>', then describe in "
    "flowing sentences what the employee's achieved proficiency means for THIS competency, using "
    "only the given facts. Refer to 'the employee' throughout. Frame it as balanced, developmental "
    "feedback for the manager — behaviourally specific and evidence-based, no personality "
    "judgements, no prescriptive advice or action plan (those are handled elsewhere). Cover it as "
    "fully as the framework detail warrants — do not truncate or artificially shorten. Retain the "
    "specific, concrete details from the framework (named entities, priorities, outcome terms) "
    "instead of abstracting them away."
)

V7_EXEC_SYS = (
    "You write the executive summary of a competency assessment report that is delivered TO the "
    "employee's manager and is ABOUT the employee. Write for a busy manager who wants to know, at "
    "a glance, where the employee is strong and where to focus next. Refer to the assessed person "
    "as 'the employee'.\n"
    "Use ONLY the factual results table (levels, scores, benchmark relationships, counts) — never "
    "invent evidence, causes, or a job role. You may name the employing organisation given in the "
    "context.\n"
    "Structure the summary for a manager:\n"
    "1. Open with a one-line headline takeaway (e.g. how many areas are strong out of the total "
    "assessed).\n"
    "2. Group the competencies by what the manager should DO with them: clear strengths first, "
    "then areas that are developing well, then the priorities for development.\n"
    "3. Call out the single most urgent development area so the manager has an obvious starting "
    "point.\n"
    "4. If (and only if) benchmarks are present, note overall benchmark alignment briefly at the "
    "end; if there are no benchmarks, do not mention them.\n"
    "Keep the tone constructive and forward-looking. Prefer plain language over raw percentages in "
    "the prose, and describe a 0% result as 'not yet demonstrated' rather than as a bare number. "
    "Follow occupational-assessment best practice: balanced, evidence-based, and non-judgemental, "
    "with no inferred causes and no prescriptive action plan (that is handled elsewhere)."
)

V7_EXEC_USER = (
    "Organization: {organization}\n"
    "Assessment: {assessment_name}\n"
    "Scoring context: {strategy_instruction}\n\n"
    "Results table:\n{competency_table}\n\n"
    "Write the 90-140 word manager-friendly executive summary, referring to 'the employee'. "
    "Lead with a one-line headline takeaway, then group the competencies into: clear strengths, "
    "areas developing well, and priorities for development — flagging the single most urgent gap. "
    "Describe any 0% result as 'not yet demonstrated'. Mention benchmark alignment only if "
    "benchmarks are present in the table; otherwise omit it entirely."
)

# ── Addition (not in the notebook) ─────────────────────────────────────────
# The notebook prompt says "Structure the summary" and lists four numbered points,
# which models read as a literal section layout ("Headline: …\n\nClear strength: …").
# The grouping is meant to be the ORDER OF IDEAS inside one paragraph, so state the
# output format explicitly. Remove this block to go back to the notebook text exactly.
EXEC_FORMAT_CONSTRAINT = (
    "\n\nOUTPUT FORMAT: return ONE continuous paragraph of flowing prose. The grouping above is "
    "the order the ideas appear in that paragraph, NOT a layout. Do not use headings, section "
    "labels (such as 'Headline:', 'Clear strength:', 'Priorities for development:'), bullet "
    "points, numbering, markdown, or blank lines. Do not start with a label of any kind — open "
    "directly with the headline sentence, then continue in the same paragraph with sentences "
    "connecting the strengths, the areas developing well, and the development priorities."
)

V7_EXEC_USER = V7_EXEC_USER + EXEC_FORMAT_CONSTRAINT


def facts_to_text(result_line: str, definition: str, level_descriptions: dict[str, str]) -> str:
    """Notebook `_facts_to_text`: render the role-free facts as plain prompt text."""
    lines = [f"Result: {result_line}"]
    if definition:
        lines.append(f"Definition: {definition}")
    for level, description in level_descriptions.items():
        lines.append(f"{level} level: {description}")
    return "\n".join(lines)
