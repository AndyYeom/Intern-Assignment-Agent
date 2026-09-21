"""Stable prompts for conservative taxonomy selection."""

import json

from project_catalog_agent.catalog.contracts import (
    ExtractedRequirement,
    TaxonomySkill,
)

TAXONOMY_SELECTION_SYSTEM_PROMPT = """ROLE:
Map one extracted raw skill to the shared canonical taxonomy.

AUTHORITY:
- taxonomy.json is the only source of canonical skill identities.
- Select only a supplied taxonomy ID.
- Never create a new ID or canonical skill.
- If no supplied skill is genuinely equivalent, return unmapped.
- Prefer unmapped over a weak nearest-neighbour match.

INPUT CONTEXT:
Use raw_skill, importance, required_level, evidence_text, and decision_basis.
Importance and level are context only. Do not modify or reassess them.

MAPPING RULES:
- Select a skill only when it represents substantially the same capability.
- Related does not mean equivalent.
- A technology within a broader field may map to that field only when the
  supplied taxonomy explicitly groups it through its name or aliases.
- Do not force performance optimization into Monitoring & Logging.
- Do not force LLM response evaluation into LLM Application Development unless
  the taxonomy definition genuinely covers evaluation.
- Do not select a skill merely because it is the closest available option.
- Return needs_review when two or more supplied skills are genuinely plausible.
- Return unmapped when none is a defensible semantic equivalent.

OUTPUT:
Return only TaxonomySelection structured output. Provide a concise, auditable
decision_basis, not hidden chain-of-thought.
"""


def format_taxonomy_context(skills: tuple[TaxonomySkill, ...]) -> str:
    """Render active taxonomy skills in deterministic compact form."""
    active_skills = sorted(
        (skill for skill in skills if skill.active),
        key=lambda skill: skill.skill_id,
    )
    return "\n".join(
        " | ".join(
            (
                skill.skill_id,
                skill.canonical_name,
                skill.category,
                ", ".join(skill.aliases),
            )
        )
        for skill in active_skills
    )


def build_taxonomy_selection_user_prompt(
    requirement: ExtractedRequirement,
    taxonomy_skills: tuple[TaxonomySkill, ...],
) -> str:
    """Build one-requirement input with the complete active taxonomy."""
    requirement_json = json.dumps(
        requirement.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    )
    taxonomy_context = format_taxonomy_context(taxonomy_skills)
    return (
        f"EXTRACTED REQUIREMENT:\n{requirement_json}\n\n"
        f"ACTIVE TAXONOMY (id | name | category | aliases):\n{taxonomy_context}"
    )
