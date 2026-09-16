"""Data generator for agent C (evidence).

Two pipelines, one entry point.

`github` (alias `gh`) — build the verified corpus:

    python -m generator gh status              progress per stratum, and what to run next
    python -m generator gh doctor              check token and rate budget
    python -m generator gh sample --target 40  select the corpus via search
    python -m generator gh collect             fetch raw payloads (slow, resumable)
    python -m generator gh build               raw -> profiles (free, re-runnable)
    python -m generator gh stats               coverage and signal report

`resume` (alias `re`) — turn profiles into MIT-format resumes:

    python -m generator re plan --batches 5    exclusive split of the corpus
    python -m generator re brief --batch 1     authoring packet for one agent
    python -m generator re draft --batch 1     honest first-pass specs
    python -m generator re verify              no profile used twice
    python -m generator re render              specs -> HTML + PDF
    python -m generator re manifest            the applicant index (data/applicants.csv)

`collect` is the only expensive stage. Everything it fetches is cached on disk,
so it resumes where it stopped and `build` costs nothing to re-run.
"""
from __future__ import annotations

import argparse
import sys

from generator import config
from generator.github import commands as github_cmd
from generator.resume import commands as resume_cmd


def _add_github_commands(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="github_command", required=True)

    p = sub.add_parser("status", help="progress per stratum, and what to run next")
    p.add_argument("--target", type=int, default=config.TARGET_PROFILE_COUNT)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=github_cmd.cmd_status)

    sub.add_parser("doctor", help="check token and rate budget").set_defaults(
        func=github_cmd.cmd_doctor)

    p = sub.add_parser("sample", help="select the corpus via the search API")
    p.add_argument("--target", type=int, default=config.TARGET_PROFILE_COUNT,
                   help="how many eligible profiles to select")
    p.add_argument("--per-stratum", type=int, default=12,
                   help="search results to examine per query")
    p.add_argument("--windows", type=int, default=2,
                   help="fresh date windows to consume per stratum this run")
    p.set_defaults(func=github_cmd.cmd_sample)

    p = sub.add_parser("collect", help="fetch raw payloads (slow, resumable)")
    p.add_argument("logins", nargs="*", help="override the candidate list")
    p.add_argument("--max-repos", type=int, default=config.MAX_REPOS_PER_USER)
    p.add_argument("--refresh", action="store_true", help="re-fetch already-collected users")
    p.add_argument("--target", type=int, default=config.TARGET_PROFILE_COUNT)
    p.add_argument("--all", action="store_true",
                   help="collect every selected candidate, not just the planned quota")
    p.set_defaults(func=github_cmd.cmd_collect)

    p = sub.add_parser("build", help="normalise raw payloads into profiles (free)")
    p.add_argument("logins", nargs="*")
    p.set_defaults(func=github_cmd.cmd_build)

    sub.add_parser("stats", help="taxonomy coverage and signal report").set_defaults(
        func=github_cmd.cmd_stats)


def _add_resume_commands(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="resume_command", required=True)

    p = sub.add_parser("plan", help="split the corpus into exclusive batches")
    p.add_argument("--batches", type=int, default=5)
    p.set_defaults(func=resume_cmd.cmd_plan)

    p = sub.add_parser("brief", help="write the authoring packet for one batch")
    p.add_argument("--batch", type=int, required=True)
    p.set_defaults(func=resume_cmd.cmd_brief)

    p = sub.add_parser("draft", help="honest first-pass specs drawn from GitHub")
    p.add_argument("--batch", type=int, default=None)
    p.set_defaults(func=resume_cmd.cmd_draft)

    sub.add_parser("verify", help="check no profile is used twice").set_defaults(
        func=resume_cmd.cmd_verify)

    p = sub.add_parser("manifest", help="show or rebuild the applicant index")
    p.add_argument("--rebuild", action="store_true",
                   help="regenerate from the spec and rendered files on disk")
    p.set_defaults(func=resume_cmd.cmd_manifest)

    p = sub.add_parser("render", help="specs -> HTML and PDF")
    p.add_argument("specs", nargs="*", help="specific spec files; default is all")
    p.add_argument("--no-pdf", action="store_true")
    p.add_argument("--include-drafts", action="store_true")
    p.set_defaults(func=resume_cmd.cmd_render)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generator",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--offline", action="store_true",
                        help="never hit the network; serve from cache only")
    sub = parser.add_subparsers(dest="pipeline", required=True)

    _add_github_commands(sub.add_parser(
        "github", aliases=["gh"],
        help="collect and verify public GitHub profiles",
        formatter_class=argparse.RawDescriptionHelpFormatter))
    _add_resume_commands(sub.add_parser(
        "resume", aliases=["re"],
        help="generate MIT-format resumes from collected profiles",
        formatter_class=argparse.RawDescriptionHelpFormatter))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
