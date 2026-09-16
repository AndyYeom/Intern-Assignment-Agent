"""Data generator for agent C (evidence).

Two pipelines, one entry point.

`github` (alias `gh`) — build the verified corpus:

    python -m generator gh status              progress per stratum, and what to run next
    python -m generator gh doctor              check token and rate budget
    python -m generator gh sample --target 40  select the corpus via search
    python -m generator gh collect             fetch raw payloads (slow, resumable)
    python -m generator gh build               raw -> profiles (free, re-runnable)
    python -m generator gh stats               coverage and signal report

`resume` (alias `re`) - MIT Template A resumes, each paired with a GitHub profile:

    python -m generator re infoprompt --appids APPID...  LLM prompt that returns a gen command
    python -m generator re gen --appids APPID... --info JSON|@file...
                                                       see `re gen -h` for the info format
    python -m generator re remove APPID...             delete resume pairs; profile kept
    python -m generator re manifest                    list pairs, and who is still waiting


`collect` is the only expensive stage. Everything it fetches is cached on disk,
so it resumes where it stopped and `build` costs nothing to re-run.
"""
from __future__ import annotations

import argparse
import sys

from generator import config
from generator.github import commands as github_cmd
from generator.resume import commands as resume_cmd
from generator.resume import generate as resume_generate


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
    p.add_argument("--windows", type=int, default=6,
                   help="most date windows to search per stratum; stops early once enough")
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

    p = sub.add_parser(
        "infoprompt", help="LLM prompt: applicants' evidence in, a finished `re gen` command out",
        description=("Print a fixed prompt followed by each applicant's GitHub evidence, "
                     "without real logins or links. Give it to ChatGPT or a subagent; it "
                     "returns one ready-to-run `re gen` command."))
    p.add_argument("--appids", nargs="*", metavar="APPID",
                   help="default: every placed applicant without a resume yet")
    p.set_defaults(func=resume_cmd.cmd_infoprompt)

    p = sub.add_parser(
        "gen", help="generate resume PDFs, each paired with its GitHub profile in applicants.csv",
        description=("Generate resumes in MIT Resume Template A. Every PDF is recorded in "
                     "data/applicants.csv with the GitHub profile it pairs with."),
        epilog=resume_generate.FORMAT, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--appids", nargs="+", required=True, metavar="APPID",
                   help="applicant IDs, e.g. applicant0046 (see data/githubs/corpus.json)")
    p.add_argument("--info", nargs="+", required=True, metavar="INFO",
                   help="one resume per appid, same order: a JSON object, or @file.json")
    p.set_defaults(func=resume_cmd.cmd_gen)

    p = sub.add_parser("remove", help="delete resume pairs (spec, PDF, CSV row); profile kept")
    p.add_argument("appids", nargs="+", metavar="APPID")
    p.add_argument("--keep-spec", action="store_true",
                   help="keep the spec JSON; delete only the PDF and CSV row")
    p.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")
    p.set_defaults(func=resume_cmd.cmd_remove)

    p = sub.add_parser("manifest", help="list resume pairs, and placed applicants still waiting")
    p.add_argument("--rebuild", action="store_true",
                   help="regenerate applicants.csv from the spec files on disk")
    p.set_defaults(func=resume_cmd.cmd_manifest)


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
