"""Sequential JSON artifact persistence for matching outputs."""

import json
import re
from pathlib import Path

from .schemas import MatchingOutput

DEFAULT_ARTIFACT_DIRECTORY = Path(__file__).resolve().parent / "artifacts"

_NUMERIC_JSON_PATTERN = re.compile(r"^\d+\.json$")
_MAX_SAVE_ATTEMPTS = 100


def get_next_artifact_index(
    artifact_directory: str | Path = DEFAULT_ARTIFACT_DIRECTORY,
) -> int:
    directory = Path(artifact_directory)
    if not directory.exists():
        return 1

    indexes = [
        int(path.stem)
        for path in directory.iterdir()
        if path.is_file() and _NUMERIC_JSON_PATTERN.fullmatch(path.name)
    ]
    return max(indexes, default=0) + 1


def format_artifact_filename(index: int) -> str:
    if index <= 0:
        raise ValueError("artifact index must be greater than 0")
    return f"{index:02d}.json"


def save_matching_output(
    output: MatchingOutput,
    artifact_directory: str | Path = DEFAULT_ARTIFACT_DIRECTORY,
) -> Path:
    directory = Path(artifact_directory)
    directory.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        output.model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
    ) + "\n"
    next_index = get_next_artifact_index(directory)

    for _ in range(_MAX_SAVE_ATTEMPTS):
        target_path = directory / format_artifact_filename(next_index)
        try:
            with target_path.open("x", encoding="utf-8") as artifact_file:
                artifact_file.write(serialized)
        except FileExistsError:
            next_index = max(
                next_index + 1,
                get_next_artifact_index(directory),
            )
            continue
        return target_path

    raise RuntimeError(
        f"Could not create a new matching artifact in {directory} after "
        f"{_MAX_SAVE_ATTEMPTS} attempts"
    )
