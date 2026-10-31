"""Canonical repository paths for offline evaluation tools."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVALUATION_ROOT = PROJECT_ROOT / "evaluation"


def evaluation_path(*parts: str) -> Path:
    """Return a path below the private, repository-level evaluation workspace."""

    return EVALUATION_ROOT.joinpath(*parts)
