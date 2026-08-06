"""The built distribution carries its data.

Every rule chart is a data file, so a packaging mistake does not break the import — it breaks
the library at the point where someone asks for a language, with a missing-file error that looks
like corruption rather than a build problem. That is worth a test, because the pyproject setting
responsible has already been wrong twice in opposite directions:

  - declaring the data twice (`packages` plus a `force-include`) made hatchling refuse to build
    any wheel at all, since it will not put two files at one archive path;
  - removing the force-include is only correct because hatchling includes everything under a
    `packages` directory. Under setuptools the same pyproject would ship no data whatsoever.

So this test asserts the data is reachable *through the installed package*, not that a particular
build backend setting is present.
"""
from __future__ import annotations

import json
from pathlib import Path

import africa_g2p


def _pkg_dir() -> Path:
    return Path(africa_g2p.__file__).parent


def test_registry_ships() -> None:
    registry = _pkg_dir() / "data" / "registry.json"
    assert registry.is_file(), f"data/registry.json missing from {_pkg_dir()}"
    assert json.loads(registry.read_text(encoding="utf-8")), "registry is empty"


def test_language_charts_ship() -> None:
    charts = sorted((_pkg_dir() / "languages").glob("*.json"))
    # 400 at the time of writing. The floor guards against shipping a token few, which a
    # partial include would do while still passing a "does the directory exist" check.
    assert len(charts) > 350, f"only {len(charts)} language charts found in {_pkg_dir()}"


def test_a_chart_loads_and_converts() -> None:
    """End to end through the public API, so the data is verified usable and not merely present."""
    from africa_g2p import G2P

    out = G2P("fat").convert("akwaaba")     # Fante: the chart stable-twi-tts depends on
    assert out and isinstance(out, str), f"expected phonemes, got {out!r}"
