"""Evidence agent: verify resume skill claims against public GitHub evidence.

    python -m src.evidence_agent verify [--appids ...] [--claims DIR]
    python -m src.evidence_agent eval       planted exaggerations caught
    python -m src.evidence_agent rules      rewrite RULES.md from the code

Claims come from the profile agent's JSON in --claims DIR (<applicant_id>.json)
when present, otherwise from the resume spec (see claims.py).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from generator.config import DATA, PROFILES_DIR
from generator.resume.generate import spec_path
from generator.schemas import GitHubProfile

from .claims import from_profile_agent, from_spec
from .verify import verify

EVIDENCE_DIR = DATA / "evidence"
ANSWER_KEY = DATA / "eval" / "planted_exaggerations.json"


def _applicants() -> list[str]:
    with (DATA / "applicants.csv").open(encoding="utf-8") as f:
        return [row["applicant_id"] for row in csv.DictReader(f)]


def cmd_verify(args: argparse.Namespace) -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    totals: Counter[str] = Counter()
    for applicant_id in args.appids or _applicants():
        github = GitHubProfile.model_validate_json(
            (PROFILES_DIR / f"{applicant_id}.json").read_text(encoding="utf-8"))
        agent_file = Path(args.claims) / f"{applicant_id}.json" if args.claims else None
        claims = (from_profile_agent(agent_file) if agent_file and agent_file.exists()
                  else from_spec(spec_path(applicant_id)))
        report = verify(claims, github)
        (EVIDENCE_DIR / f"{applicant_id}.json").write_text(
            report.model_dump_json(indent=2) + "\n", encoding="utf-8")
        totals.update(report.status_counts)
        print(f"  {applicant_id}  {report.status_counts}")
    print(f"[verify] {sum(totals.values())} claims: {dict(sorted(totals.items()))}")
    return 0


def cmd_eval(_: argparse.Namespace) -> int:
    key = json.loads(ANSWER_KEY.read_text(encoding="utf-8"))
    planted = {(p["applicant_id"], p["skill_id"]) for p in key}
    below = {"partially_verified", "conflicting"}
    caught_evidence = caught_any = 0
    false_flags = honest = 0
    for path in sorted(EVIDENCE_DIR.glob("applicant*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        for skill in report["skills"]:
            pair = (report["applicant_id"], skill["skill_id"])
            if pair in planted:
                hit = skill["status"] != "verified"
                caught_evidence += skill["status"] in below
                caught_any += hit
                print(f"  planted {pair[0]} {pair[1]:<16} -> {skill['status']}"
                      f" (observed {skill['observed_level']})")
            else:
                honest += 1
                false_flags += skill["status"] in below
    summary = {
        "planted": len(key),
        "caught": caught_any,
        "caught_with_contrary_evidence": caught_evidence,
        "caught_as_not_observed": caught_any - caught_evidence,
        "unplanted_claims": honest,
        "unplanted_flagged_below_claim": false_flags,
    }
    (DATA / "eval" / "summary.json").write_text(json.dumps(summary, indent=2) + "\n",
                                                encoding="utf-8")
    print(f"[eval] caught {caught_any}/{len(key)} planted exaggerations "
          f"({caught_evidence} with contrary evidence, {caught_any - caught_evidence} "
          f"not observed); {false_flags}/{honest} unplanted claims flagged below claim")
    return 0


def cmd_plant(_: argparse.Namespace) -> int:
    from generator.resume.plant import plant

    for row in plant(_applicants()):
        print(f"  {row['applicant_id']}  {row['kind']:<11} {row['resume_text']}")
    return 0


def cmd_rules(_: argparse.Namespace) -> int:
    from .rules import RULES_PATH, sync_rules_doc

    print(f"[rules] {RULES_PATH} {'rewritten' if sync_rules_doc() else 'already up to date'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    from .rules import sync_rules_doc

    sync_rules_doc()
    parser = argparse.ArgumentParser(prog="evidence_agent", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("verify", help="write data/evidence/<applicant_id>.json")
    p.add_argument("--appids", nargs="*")
    p.add_argument("--claims", help="directory of profile-agent JSON, one per applicant")
    p.set_defaults(func=cmd_verify)
    sub.add_parser("rules", help="rewrite RULES.md from the code").set_defaults(func=cmd_rules)
    sub.add_parser("plant", help="plant 10 exaggerations (idempotent)").set_defaults(func=cmd_plant)
    sub.add_parser("eval", help="how many planted exaggerations were caught").set_defaults(
        func=cmd_eval)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
