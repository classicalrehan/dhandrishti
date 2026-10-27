"""Which scored stocks count as recommendations (docs/recommendation-tracking.md).

Policy 2026.10-top5-v1: a candidate is any stock ranked within the top 5 of the whole run; it is
RECOMMENDED only if it also passes the eligibility rules of paper portfolio #1 (risk level at most MEDIUM,
no confidence floor). A candidate that fails is recorded as EXCLUDED_CANDIDATE with its reasons; ranks 6+
are never promoted to fill the gap. Eligibility is recorded for every scored stock, so other definitions
(e.g. "top 5 eligible", as the paper portfolios buy) can be derived later from the same records.
"""

import psycopg
from psycopg.types.json import Jsonb

from .manifest import sha

RISK_ORDER = ("LOW", "MEDIUM", "HIGH", "VERY_HIGH")
CONFIDENCE_ORDER = ("LOW", "MEDIUM", "HIGH")

POLICY_V1 = {
    "version": "2026.10-top5-v1",
    "top_n": 5,
    "max_risk": "MEDIUM",
    "min_confidence": None,
    "min_history_bars": None,
}
POLICY_V1_DESCRIPTION = (
    "Candidates: overall rank <= 5. Recommended if risk level <= MEDIUM; no confidence floor (every score is LOW "
    "confidence while fundamentals are missing, matching paper portfolio #1 which also has none). Excluded "
    "candidates are recorded with reasons and not replaced by lower ranks.")


def exclusion_reasons(stock: dict, policy: dict) -> list[str]:
    reasons = []
    if RISK_ORDER.index(stock["risk_level"]) > RISK_ORDER.index(policy["max_risk"]):
        reasons.append(f"RISK_{stock['risk_level']}_ABOVE_{policy['max_risk']}")
    if policy["min_confidence"] and \
            CONFIDENCE_ORDER.index(stock["confidence"]) < CONFIDENCE_ORDER.index(policy["min_confidence"]):
        reasons.append(f"CONFIDENCE_{stock['confidence']}_BELOW_{policy['min_confidence']}")
    if policy["min_history_bars"] and stock["technicals"].get("bars", 0) < policy["min_history_bars"]:
        reasons.append(f"HISTORY_BELOW_{policy['min_history_bars']}_BARS")
    return reasons


def select(stock: dict, policy: dict) -> tuple[bool, list[str], str]:
    """(eligible, exclusion reasons, selection) for one finalized stock result."""
    reasons = exclusion_reasons(stock, policy)
    if stock["rank"] > policy["top_n"]:
        return not reasons, reasons, "NOT_CANDIDATE"
    return not reasons, reasons, "RECOMMENDED" if not reasons else "EXCLUDED_CANDIDATE"


def register(conn: psycopg.Connection, policy: dict = POLICY_V1, description: str = POLICY_V1_DESCRIPTION) -> str:
    """Store the policy under its version; the same version with different rules is an error."""
    digest = sha(policy)
    conn.execute("""INSERT INTO recommendation_policies (version, params, params_sha256, description)
                    VALUES (%s, %s, %s, %s) ON CONFLICT (version) DO NOTHING""",
                 (policy["version"], Jsonb(policy), digest, description))
    stored = conn.execute("SELECT params_sha256 FROM recommendation_policies WHERE version = %s",
                          (policy["version"],)).fetchone()[0]
    if stored != digest:
        raise RuntimeError(f"recommendation policy {policy['version']} differs from the stored copy; bump its version")
    return policy["version"]
