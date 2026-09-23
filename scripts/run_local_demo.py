"""Run the existing offline component demos with visible progress and saved logs.

This does not call an LLM or perform real applicant placement. Each component
uses its own checked-in fixture; this is not a connected live-agent pipeline.
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--test", action="store_true", help="Also run the full test suite"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "data/runs/local-check"
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    steps = [
        ("catalog", ["scripts/manual_test_workflow.py", "--case", "0"]),
        (
            "evidence",
            [
                "-m",
                "src.evidence_agent.evidence_graph",
                "applicant0004",
                "--profile",
                "output/applicant0004_profile.json",
                "--rules-only",
            ],
        ),
        ("matching", ["scripts/run_matching_flow.py", "--seed", "42"]),
    ]
    if args.test:
        steps.append(("tests", ["-m", "pytest", "--tb=short"]))
    print(
        "OFFLINE COMPONENT CHECKS — sample data, no model calls, draft results only",
        flush=True,
    )
    for index, (name, command) in enumerate(steps, start=1):
        print(f"\n[{index}/{len(steps)}] {name.upper()}", flush=True)
        with (
            (output_dir / f"{name}.log").open("w", encoding="utf-8") as log,
            subprocess.Popen(
                [sys.executable, "-u", *command],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
            ) as process,
        ):
            assert process.stdout is not None
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
                log.flush()
            code = process.wait()
        if code:
            print(f"FAILED: {name} (exit {code}); logs: {output_dir}", flush=True)
            return code
    print(f"\nAll requested checks passed. Logs: {output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
