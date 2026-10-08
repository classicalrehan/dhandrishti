"""Scoring-run persistence: config versions, runs, scores, technicals, sectors, regime."""

import hashlib
import json
import math

import psycopg
from psycopg.types.json import Jsonb

from ..config import Config
from ..models import MarketInput
from ..technicals import SERIES_COLUMNS, indicator_series

TECH_COLUMNS = (
    "close", "change_pct", "sma20", "sma50", "sma100", "sma200", "ema20", "rsi14", "macd", "macd_signal",
    "macd_hist", "adx14", "plus_di", "minus_di", "atr14", "atr_pct", "bb_upper", "bb_lower", "high_52w",
    "low_52w", "dist_from_52w_high", "dist_from_sma50", "dist_from_sma200", "sma200_slope_20d",
    "relative_volume", "avg_traded_value_cr", "ret_1d", "ret_1w", "ret_1m", "ret_3m", "ret_6m", "ret_1y",
    "rs_nifty_1m", "rs_nifty_3m", "rs_nifty_6m", "volatility_60d", "max_drawdown_1y", "gap_moves_60d", "trend",
)


def config_sha256(cfg: Config) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def register_config(conn: psycopg.Connection, cfg: Config) -> str:
    """Store the config under its version. Changing a config without bumping its version is an error."""
    digest = config_sha256(cfg)
    conn.execute("""
        INSERT INTO scoring_config_versions (version, config, config_sha256) VALUES (%s, %s, %s)
        ON CONFLICT (version) DO NOTHING""", (cfg["version"], Jsonb(cfg), digest))
    stored = conn.execute("SELECT config_sha256 FROM scoring_config_versions WHERE version = %s",
                          (cfg["version"],)).fetchone()[0]
    if stored != digest:
        raise RuntimeError(
            f"scoring config {cfg['version']} differs from the stored copy; bump `version` in scoring-config.json")
    return cfg["version"]


def start_run(conn: psycopg.Connection, as_of: str, config_version: str, provenance: str) -> int:
    return conn.execute("""
        INSERT INTO scoring_runs (as_of, config_version, provenance, status)
        VALUES (%s, %s, %s, 'RUNNING') RETURNING id""", (as_of, config_version, provenance)).fetchone()[0]


def finish_run(conn: psycopg.Connection, run_id: int, *, stock_count: int | None = None,
               error: str | None = None) -> None:
    conn.execute("""
        UPDATE scoring_runs SET status = %s, stock_count = %s, error = %s, finished_at = now()
        WHERE id = %s""", ("FAILED" if error else "SUCCEEDED", stock_count, error, run_id))


def save_results(conn: psycopg.Connection, run_id: int, result: dict) -> None:
    as_of, version, prov = result["as_of"], result["config_version"], result["data_provenance"]
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO score_history (symbol, as_of, config_version, run_id, total_score, rank, confidence,
              data_coverage, risk_level, risk_points, key_reason, component_scores, result, provenance)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, as_of, config_version) DO UPDATE SET
              run_id = EXCLUDED.run_id, total_score = EXCLUDED.total_score, rank = EXCLUDED.rank,
              confidence = EXCLUDED.confidence, data_coverage = EXCLUDED.data_coverage,
              risk_level = EXCLUDED.risk_level, risk_points = EXCLUDED.risk_points,
              key_reason = EXCLUDED.key_reason, component_scores = EXCLUDED.component_scores,
              result = EXCLUDED.result, provenance = EXCLUDED.provenance""",
            [(s["symbol"], as_of, version, run_id, s["total_score"], s["rank"], s["confidence"],
              s["data_coverage"], s["risk_level"], s["risk_points"], s["key_reason"],
              Jsonb({k: c["score"] for k, c in s["components"].items()}), Jsonb(s), prov)
             for s in result["stocks"]])

        cols = ", ".join(TECH_COLUMNS)
        ph = ", ".join(["%s"] * (len(TECH_COLUMNS) + 4))
        upd = ", ".join(f"{c} = EXCLUDED.{c}" for c in TECH_COLUMNS)
        cur.executemany(f"""
            INSERT INTO technical_indicators (symbol, as_of, {cols}, detail, provenance)
            VALUES ({ph})
            ON CONFLICT (symbol, as_of) DO UPDATE SET {upd}, detail = EXCLUDED.detail,
              provenance = EXCLUDED.provenance""",
            [(s["symbol"], as_of, *[s["technicals"][c] for c in TECH_COLUMNS], Jsonb(s["technicals"]), prov)
             for s in result["stocks"]])

        cur.executemany("""
            INSERT INTO sector_strength_history (as_of, sector, config_version, run_id, score, rank,
              momentum, breadth, detail, provenance)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (as_of, sector, config_version) DO UPDATE SET
              run_id = EXCLUDED.run_id, score = EXCLUDED.score, rank = EXCLUDED.rank,
              momentum = EXCLUDED.momentum, breadth = EXCLUDED.breadth, detail = EXCLUDED.detail,
              provenance = EXCLUDED.provenance""",
            [(as_of, s["sector"], version, run_id, s["score"], s["rank"], s["momentum"], s["breadth"],
              Jsonb(s), prov) for s in result["sectors"]])

    r = result["regime"]
    conn.execute("""
        INSERT INTO market_regime_history (as_of, config_version, run_id, regime, composite, confidence,
          factors, reason, breadth, provenance)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (as_of, config_version) DO UPDATE SET
          run_id = EXCLUDED.run_id, regime = EXCLUDED.regime, composite = EXCLUDED.composite,
          confidence = EXCLUDED.confidence, factors = EXCLUDED.factors, reason = EXCLUDED.reason,
          breadth = EXCLUDED.breadth, provenance = EXCLUDED.provenance""",
        (as_of, version, run_id, r["regime"], r["composite"], r["confidence"], Jsonb(r["factors"]),
         r["reason"], Jsonb(result["breadth"]), prov))


def save_indicator_series(conn: psycopg.Connection, market: MarketInput) -> int:
    """Upsert chart indicator series for every loaded bar of every stock."""
    def clean(v: float) -> float | None:
        return None if math.isnan(v) else round(float(v), 4)

    cols = ", ".join(SERIES_COLUMNS)
    ph = ", ".join(["%s"] * (len(SERIES_COLUMNS) + 3))
    upd = ", ".join(f"{c} = EXCLUDED.{c}" for c in SERIES_COLUMNS)
    rows = []
    for s in market.stocks:
        series = indicator_series(s.bars)
        for i, d in enumerate(s.bars.dates):
            rows.append((s.security.symbol, d, *[clean(series[c][i]) for c in SERIES_COLUMNS],
                         market.provenance))
    with conn.cursor() as cur:
        cur.executemany(f"""
            INSERT INTO indicator_series (symbol, trade_date, {cols}, provenance) VALUES ({ph})
            ON CONFLICT (symbol, trade_date) DO UPDATE SET {upd}, provenance = EXCLUDED.provenance""", rows)
    return len(rows)
