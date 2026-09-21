"""Framework-enrichment prompts (job purpose, competency definition, proficiency levels).

Ported verbatim from `feedback_agent_pipeline_v6_2.ipynb`
(`JobPurpose_generation`, `CompetencyDefinition_generation`, `generate_levels_v7`).
"""

JOB_PURPOSE_SYS = """You are a highly skilled HR expert with extensive experience in creating job descriptions and identifying key responsibilities for various roles. Your expertise lies in understanding the nuances of different competencies and how they relate to specific job roles. You are adept at analyzing information and synthesizing it into clear, concise, and relevant job purposes that accurately reflect the expectations and objectives of a role.
    Your responses should be direct and focused, providing only the essential information needed to understand the job purpose without any unnecessary details or explanations. You are committed to delivering high-quality outputs that meet the needs of hiring managers and candidates alike.
    Your goal is to ensure that the job purpose you create is not only accurate but also aligns with the competencies required for the role, making it easy for candidates to understand what is expected of them.
    Return the job purpose in the structured 'job_purpose' field.
    """


def build_job_purpose_user_prompt(
    industry: str,
    seniority: str,
    role: str,
    competencies: object,
    organization: str | None = None,
) -> str:
    use_web_search = bool(organization)
    org_block = f"\n    Organization: {organization}" if use_web_search else ""

    prompt = f"""You are a skilled  HR expert. Your task is to identify the Job purpose for this specific role
    Role : {role}
    {industry}
    {seniority}{org_block}

    Competency: {competencies}
    Instructions:
    - Analyse the role and the Competencies and identify the Job purpose for the {competencies} Competency, and the {role} role.
    - Provide a concise and clear Job purpose that reflects the key responsibilities and objectives of the role.
    - Ensure that the Job purpose is relevant to the {competencies} Competency and the {role} role.
    - Do not include any additional information or explanations, just provide the Job purpose.
    - reformulate the competencies not just list them, and elaborate the objective, and should be clear and concise.

    """

    if use_web_search:
        prompt += f"""    - Research the organization "{organization}" and tailor the Job purpose to its business context and terminology.
    - Do not invent organization-specific details when reliable evidence is unavailable.

    """
    return prompt


_DEFINITION_EXAMPLE_1 = "Strategic thinking: Ability to develop effective long-term plans and align resources towards goals."
_DEFINITION_EXAMPLE_2 = "Team collaboration: Capacity to work effectively within teams, ensuring shared goals and mutual respect."


def build_competency_definition_system_prompt(competency: str) -> str:
    return f"""You are an HR expert specializing in competency definitions. Provide only the definition for the {competency} in the structured 'definition' field, no extra information."""


def build_competency_definition_user_prompt(
    role: str | None,
    job_purpose: str,
    competency: str,
    organization: str | None = None,
    example: str | None = None,
) -> str:
    prompt = f"""You are a skilled HR copy editor. Generate a clear and professional definition for the competency below, keeping it about 50 words.
    {role} Role
    Job Purpose: {job_purpose}
    organization: {organization}

    Competency: {competency}
    Instructions:
    - Definition should be concise and easy to understand.
    - Use a professional tone suitable for HR contexts.
    - Avoid repetition and keep it natural.
    - Ensure clarity in defining the essential qualities.
    - Begin the definition with 'Ability to'
    """
    if example:
        prompt += f"\n    - Use the following example as a guide for style and clarity: {example}"
    else:
        prompt += (
            f"\n    - Use the following examples as a guide for style and clarity: "
            f"{_DEFINITION_EXAMPLE_1} | {_DEFINITION_EXAMPLE_2}"
        )

    if organization:
        prompt += f"\n    - Research the organization '{organization}' and tailor the competency definition to its business context and terminology."
        prompt += "\n    - Do not invent organization-specific details when reliable evidence is unavailable."
    return prompt


LEVELS_STYLE_EXAMPLE = """
Foundation Proficiency-Level :
* Diagnoses underlying technical problems or issues causing incidents and disruptions in operations
* Implements problem management procedures to resolve the root cause of routine incidents
* Provides end-to-end management of technical issues encountered by users, within an agreed timeframe
* Performs configuration and support activities at a routine level of difficulty
* Monitors service levels, reviews and reports service delivery deviations

Applied Proficiency-Level :
* Develops an action plan and timeline for upgrade activities
* Proposes ideas for improvements based on current and future user needs
* Tests systems in advance to assess the impact of potential upgrades on performance
* Organizes information for the development of user guides and training materials
* Manages fulfilment of service level agreements (SLAs) and resolves issues to maintain service levels

Advanced Proficiency-Level :
* Retains accountability for the best possible levels of service quality and availability
* Investigates highly complex technical issues or disruptions in operations
* Establishes a robust problem management process to restore smooth operations with minimal impact
* Develops effective and sustainable solutions to address technical problems, and guides others in doing so
* Evaluates service levels and oversees improvements to enhance performance
"""


def build_levels_system_prompt(
    industry: str,
    role: str,
    competency: str,
    definition: str,
    job_purpose: str,
    organization: str | None = None,
) -> str:
    sys = (
        "You are an expert in designing advanced competency frameworks. Generate the three "
        f"Proficiency-Level descriptions (Foundation < Applied < Advanced; there is NO "
        f"Intermediate and NO Expert level) for the competency '{competency}' for the role "
        f"'{role}' ({industry}).\n"
        f"Competency definition: {definition}\n"
        f"Job purpose if available: {job_purpose}\n"
        "- Foundation: routine tasks under direct supervision, applying foundational knowledge (90-105 words).\n"
        "- Applied: independent work under general direction, non-routine problems via standard procedures (105-120 words).\n"
        "- Advanced: complex, ambiguous situations with minimal guidance while mentoring others (120-135 words).\n"
        "- Keep each description competency-specific, technical, logical, and incremental in depth.\n"
        "- Use bullet points; do not mention the level names or the word 'competency' inside the text.\n"
        "- Expand every abbreviation on first use.\n"
        "- Return only the description text in the 'foundation', 'applied' and 'advanced' fields."
    )
    if organization:
        sys += (
            f"\n- Research the organization '{organization}' and tailor the proficiency levels "
            "to its business context and terminology."
            "\n- Do not invent organization-specific details when reliable evidence is unavailable."
        )
    return sys


def build_levels_user_prompt(competency: str, role: str, examples: str = "") -> str:
    style = examples.strip() or LEVELS_STYLE_EXAMPLE
    return (
        f"Generate the three Proficiency-Level descriptions for '{competency}' for the role '{role}'.\n"
        "Follow the style/structure of this example (bullet points per level):\n"
        f"{style}"
    )
