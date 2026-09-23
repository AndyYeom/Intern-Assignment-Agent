"""Both model attempts must include the canonical skill vocabulary."""

from src.profile_agent.profile_prompts import (
    CANONICAL_SKILL_TAXONOMY,
    build_correction_prompt,
    build_profile_prompt,
)


def test_initial_and_correction_prompts_include_canonical_taxonomy() -> None:
    initial = build_profile_prompt("demo", "Python project", "", "{}")
    correction = build_correction_prompt(
        "demo", "Python project", "", "invalid", "Invalid JSON", "{}"
    )
    for prompt in (initial, correction):
        assert CANONICAL_SKILL_TAXONOMY in prompt
        assert "{canonical_skill_taxonomy}" not in prompt
