"""
Merges A's self-reported levels with C's GitHub-verified levels into one
final level per skill.

This is code, not a prompt. The same inputs must always produce the same
assignment — if this were an LLM call, the demo would not be reproducible.

Levels: 1=Entry, 2=Intermediate, 3=Advanced. A skill absent from the profile
stays absent; it never becomes a level.
"""

VALID_STATUS = {"verified", "partially_verified", "not_observed", "conflicting"}


def resolve_skill(claimed, observed, status):
    """returns (final_level, flag_or_None)"""
    if status not in VALID_STATUS:
        raise ValueError(f"unknown verification status: {status!r}")

    if status == "verified":
        return observed, None

    if status == "conflicting":
        # evidence directly contradicts the claim -> trust the lower
        return min(claimed, observed), "conflicting"

    if status == "partially_verified":
        # evidence supports some of it; allow at most one level above observed
        return min(claimed, observed + 1), None

    # not_observed: absence of GitHub evidence is NOT disconfirming.
    # Keep the claim, but mark it so scoring can discount confidence.
    return claimed, "unverified"


def resolve_profile(profile, verification):
    """
    profile      : ApplicantProfile from the Profile agent
    verification : output of the Evidence agent

    returns ResolvedProfile — the only input the Scoring agent reads.
    """
    checks = {v["canonical_skill"]: v for v in verification.get("skill_verification", [])}

    skills, flags = {}, {}
    for s in profile.get("skills", []):
        name = s["canonical_skill"]
        claimed = s["claimed_level"]
        v = checks.get(name)

        if v is None:
            # Evidence agent never looked at it — same as not_observed
            final, flag = claimed, "unverified"
        else:
            final, flag = resolve_skill(claimed, v["github_observed_level"], v["verification_status"])

        skills[name] = final
        if flag:
            flags[name] = flag

    return {
        "schema_version": "0.1",
        "applicant_id": profile["applicant_id"],
        "skills": skills,                      # {skill: 1|2|3}
        "flags": flags,                        # {skill: "unverified"|"conflicting"}
        "interests": profile.get("interests", []),
        "domains": profile.get("domains", []),
        "unverified_ratio": round(
            sum(1 for f in flags.values() if f == "unverified") / max(len(skills), 1), 2
        ),
    }


if __name__ == "__main__":
    prof = {
        "applicant_id": "app_01",
        "skills": [
            {"canonical_skill": "python", "claimed_level": 3},
            {"canonical_skill": "react", "claimed_level": 2},
            {"canonical_skill": "docker", "claimed_level": 2},
            {"canonical_skill": "aws", "claimed_level": 2},
        ],
        "interests": ["Machine Learning"],
    }
    ver = {"skill_verification": [
        {"canonical_skill": "python", "github_observed_level": 2, "verification_status": "conflicting"},
        {"canonical_skill": "react", "github_observed_level": 2, "verification_status": "verified"},
        {"canonical_skill": "docker", "github_observed_level": 1, "verification_status": "partially_verified"},
        {"canonical_skill": "aws", "github_observed_level": 1, "verification_status": "not_observed"},
    ]}
    import json
    print(json.dumps(resolve_profile(prof, ver), indent=2))
