"""Locations of shared, language-neutral resources in the monorepo."""

import os
from pathlib import Path

REPO_ROOT = Path(os.environ.get("DD_REPO_ROOT", Path(__file__).resolve().parents[4]))
QUANT_SPEC_DIR = REPO_ROOT / "packages" / "quant-spec"
SCORING_CONFIG_PATH = Path(os.environ.get("DD_SCORING_CONFIG", QUANT_SPEC_DIR / "scoring-config.json"))
FIXTURES_DIR = QUANT_SPEC_DIR / "fixtures"
NSE_HOLIDAYS_PATH = REPO_ROOT / "packages" / "shared" / "src" / "nse-holidays.json"
MIGRATIONS_DIR = REPO_ROOT / "packages" / "database" / "migrations"
STAGED_MIGRATIONS_DIR = REPO_ROOT / "packages" / "database" / "migrations-staged"
UNIVERSE_DIR = QUANT_SPEC_DIR / "universe"
