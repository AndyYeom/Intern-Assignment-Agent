"""Evidence-agent tests run against a throwaway copy of data/, never the real one.

Modules bind data paths at import time (`from generator.config import
CANDIDATES_PATH`), so patching `config` alone leaves their copies pointing at the
real files - which is how a test once wrote fake candidates into the real
candidates.json. This fixture rewrites every Path attribute, in every generator
module, that points under data/ or the HTTP cache.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

import generator.__main__  # noqa: F401 - import every module so all path copies exist
from generator import config

REAL_DATA = config.DATA
REAL_CACHE = config.CACHE_DIR
# Read-only inputs the code needs; copied, never linked.
READ_ONLY_INPUTS = ["taxonomy.json", "proficiency_levels.md", "static/image.png"]


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


@pytest.fixture(autouse=True)
def isolated_data(request: pytest.FixtureRequest, tmp_path: Path,
                  monkeypatch: pytest.MonkeyPatch) -> Path:
    # Only the tests that read data/ are isolated: this conftest covers the whole
    # repository, and other agents' tests assert their tmp_path stays empty.
    if request.path.parent != Path(__file__).parent:
        return REAL_DATA
    # Opt-out for tests that must read the real corpus (and write nothing to data/).
    if request.node.get_closest_marker("real_data"):
        return REAL_DATA
    data = tmp_path / "data"
    cache = tmp_path / "cache"
    for relative in READ_ONLY_INPUTS:
        source = REAL_DATA / relative
        if source.exists():
            (data / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, data / relative)

    for name, module in list(sys.modules.items()):
        if not name.startswith("generator"):
            continue
        for attr, value in list(vars(module).items()):
            if not isinstance(value, Path):
                continue
            if _under(value, REAL_DATA):
                redirected = data / value.resolve().relative_to(REAL_DATA.resolve())
            elif _under(value, REAL_CACHE):
                redirected = cache / value.resolve().relative_to(REAL_CACHE.resolve())
            else:
                continue
            monkeypatch.setattr(module, attr, redirected)
    return data
