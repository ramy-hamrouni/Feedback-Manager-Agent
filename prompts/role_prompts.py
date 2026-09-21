"""Role-generation prompts.

Ported verbatim from `feedback_agent_pipeline_v6_2.ipynb` (`role_generation`).
"""

ROLE_GENERATION_SYS = """
            You are a role generation assistant.

            Your task is to identify the most suitable SINGLE job role based on:
            1. The provided competencies and their descriptions.
            2. The assessment each set of competencies was measured in.
            3. The organization in which the role exists.

            The competencies may be grouped under the assessment they belong to (for example a
            leadership, behavioural, or technical assessment). Treat every assessment as a
            different facet of the SAME employee and infer ONE unifying role that fits the whole
            set of competencies across all assessments — never a separate role per assessment.

            When web search is available:
            - Research the organization to understand its business context and terminology.
            - Identify how the organization typically names roles similar to the inferred role.
            - Use this organizational context to select the most appropriate role title.
            - Do not invent an organization-specific title when reliable evidence is unavailable.

            The final role should:
            - Fit the provided competencies across all assessments.
            - Be appropriate for the organization's context.
            - Use a professional and realistic job title.
        """


def format_role_competencies(competencies) -> str:
    """Render competencies for the role prompt. Accepts either a flat list (of names or
    {Competency, Competency Description} dicts) or a dict mapping each assessment name to its
    own competency set, so the model can see which competencies belong to which assessment."""

    def _one(item) -> str:
        if isinstance(item, dict):
            name = str(item.get("Competency", "")).strip()
            desc = str(item.get("Competency Description", "")).strip()
            return f"  - {name}: {desc}" if desc else f"  - {name}"
        return f"  - {item}"

    if isinstance(competencies, dict):
        blocks = []
        for aname, comps in competencies.items():
            lines = "\n".join(_one(c) for c in comps) or "  - (none)"
            blocks.append(f"Assessment: {aname}\n{lines}")
        return "\n\n".join(blocks)
    return "\n".join(_one(c) for c in competencies)


def build_role_generation_user_prompt(
    competencies,
    organization: str | None = None,
    examples: str | None = None,
) -> str:
    competencies_block = format_role_competencies(competencies)
    grouped = isinstance(competencies, dict)
    comp_header = "Competencies by assessment:" if grouped else "Competencies:"

    user_prompt = f"""
        Generate the most suitable single role based on the competencies below{', which are grouped by the assessment they belong to' if grouped else ''}.

        Organization:
        {organization}

        {comp_header}
        {competencies_block}

        Consider all assessments together and use the organization's context and terminology when
        determining the one unifying role title.
        """
    if examples:
        user_prompt += f"\nExamples: {examples}"
    return user_prompt
