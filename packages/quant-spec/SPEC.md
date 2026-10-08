# DhanDrishti Quantitative Specification

**Status:** v1 (`2026.10-v1`). This document plus [`scoring-config.json`](./scoring-config.json) is the
source of truth for every calculation. The reference implementation is the Python worker
(`apps/worker`). Any other implementation must reproduce the golden fixtures in
[`fixtures/`](./fixtures) exactly (see §11).

The numbers (weights, thresholds, ramps) live **only** in `scoring-config.json`. This file
defines what those numbers mean. If the two disagree, fix the code, not the fixture.

---

## 1. Principles

1. **Deterministic.** The same input gives the same output, with no wall-clock reads, unseeded
   randomness or network calls inside the engine. The "as of" date is an input.
2. **Explainable.** Every point awarded traces back to a named metric, its raw value, its
   normalized value and a human-readable reason.
3. **Missing ≠ zero.** Missing data is `null` and is reported as "Data unavailable". It is
   never guessed (§4.3).
4. **The engine owns the score.** No LLM or UI layer may change a score, rank, metric or risk level.

---

## 2. Inputs

### 2.1 Price bars (per security and per index)
Daily OHLCV, ascending by trading date (IST), adjusted for splits/bonuses.

### 2.2 Fundamentals (per security, all nullable)
| Field | Unit | Notes |
|---|---|---|
| `market_cap_cr` | ₹ Cr | |
| `revenue_growth_yoy`, `profit_growth_yoy`, `eps_growth_yoy` | % | latest FY vs prior FY |
| `eps_cagr_3y` | % | |
| `roe`, `roce`, `operating_margin`, `net_margin` | % | |
| `free_cash_flow_cr` | ₹ Cr | |
| `cfo_to_pat` | ratio | cash-flow quality |
| `debt_to_equity`, `interest_coverage` | x | |
| `pe`, `pb`, `peg` | x | |
| `dividend_yield` | % | |
| `promoter_holding`, `promoter_pledge`, `institutional_holding` | % | pledge = % of promoter stake pledged |
| `pe_median_5y` | x | own historical median PE |
| `quarterly_eps` | list | oldest → newest, ideally ≥ 8 quarters |
| `positive_eps_quarters_8` | int 0–8 | quarters among last 8 with YoY EPS growth |

### 2.3 Security metadata
`symbol`, `name`, `sector`, `is_financial` (banks/NBFCs/insurers). For financials the leverage
and cash-flow metrics flagged `non_financial_only` are **not applicable**. They are dropped from
the denominator, which is different from missing (§4.3).

### 2.4 Events
Upcoming earnings / corporate actions with dates (used by the risk engine only).

### 2.5 Benchmarks
`NIFTY 50` (relative strength, regime), `NIFTY BANK`, `INDIA VIX` (regime).

---

## 3. Indicators

All series are aligned with the input; positions without enough history are `null`.
`n` is the period. The last value of each series is used in scoring unless stated otherwise.

| Indicator | Definition |
|---|---|
| SMA(n) | arithmetic mean of last n closes |
| EMA(n) | seed = SMA of first n values; then `ema_t = x_t·k + ema_{t-1}·(1−k)`, `k = 2/(n+1)` |
| RSI(14) | Wilder: seed avg gain/loss = simple mean of first 14 changes; then `avg = (avg·13 + x)/14`. `RSI = 100 − 100/(1+RS)`; RSI = 100 when avg loss = 0 |
| MACD(12,26,9) | `EMA12 − EMA26`; signal = EMA9 of the MACD line (seeded from its first non-null value); histogram = MACD − signal |
| True range | `max(H−L, |H−C_prev|, |L−C_prev|)`; first bar = H−L |
| ATR(14) | Wilder smoothing of TR starting from bar index 1 |
| ADX(14) | +DM/−DM per Wilder; TR, +DM, −DM Wilder-smoothed from index 1; `+DI = 100·+DM_s/TR_s`; `DX = 100·|+DI−−DI|/(+DI+−DI)`; ADX = Wilder smoothing of DX |
| Bollinger(20,2) | SMA20 ± 2·population std of last 20 closes |
| Return(L) | `(C_t / C_{t−L} − 1)·100`; null if fewer than L+1 bars |
| Volatility(60) | sample std (ddof=1) of the last 60 daily simple returns × √252 × 100 |
| Max drawdown 1Y | min over the last 252 closes of `(C / running_peak − 1)·100` |
| 52W high / low | max high / min low of last 252 bars; null if fewer than 200 bars |
| SMA200 slope | `(SMA200_t / SMA200_{t−20} − 1)·100` |
| Relative volume | volume_t / SMA20(volume) |
| Avg traded value | mean of `close·volume/1e7` (₹ Cr) over last 20 bars |
| Gap moves 60D | count over last 60 sessions of `|open_t / close_{t−1} − 1| > 4%` |
| Up/down volume ratio | over last 50 sessions: Σ volume on up-closes / Σ volume on down-closes (null if no down days) |

Lookbacks (trading days): 1D=1, 1W=5, 1M=21, 3M=63, 6M=126, 1Y=252.

**Trend classification**: with `close`, `SMA50`, `SMA200`, `slope` (SMA200 slope),
`ADX`:
- SMA50 or SMA200 null → `SIDEWAYS`
- close > SMA50 > SMA200 → `STRONG_UPTREND` if ADX ≥ 25 and slope > 0, else `UPTREND`
- close < SMA50 < SMA200 → `STRONG_DOWNTREND` if ADX ≥ 25 and slope ≤ 0, else `DOWNTREND`
- otherwise `SIDEWAYS`

---

## 4. Normalization

Every metric becomes a value in **[0, 1]** through one of these functions:

| `fn` | Formula |
|---|---|
| `ramp(lo, hi)` | `clip((x − lo)/(hi − lo), 0, 1)`. If `lo > hi` the ramp is **inverse** (lower is better). |
| `log_ramp(lo, hi)` | `ramp` applied to `log10(x)` between `log10(lo)` and `log10(hi)`; x ≤ 0 → 0 |
| `binary` | `1` if the condition is true, else `0` |
| `band(zero_lo, full_lo, full_hi, zero_hi)` | 0 at or below `zero_lo`; rises linearly to 1 at `full_lo`; 1 through `full_hi`; falls linearly to 0 at `zero_hi` |

### 4.1 Component score
For a component with weight `W` and metrics `m` with sub-weights `w_m` and normalized values `s_m`:

```
applicable  = metrics not excluded by non_financial_only
available   = applicable metrics whose raw value is not null
coverage    = Σ_{available} w_m / Σ_{applicable} w_m
normalized  = Σ_{available} w_m·s_m / Σ_{available} w_m      (if coverage > 0)
            = missing_data_neutral                            (if coverage = 0)
score       = normalized · W
```

### 4.2 Total
`total = round(Σ component.score, 2)`. The UI shows `round(total)`. Component scores are
reported unrounded internally and rounded to 2 dp in output.

### 4.3 Missing data
Missing metrics are excluded from the weighted average. When a whole component is missing, its
normalized value is `missing_data_neutral` (0.5), the reason is
`"<Component>: Data unavailable — neutral score applied"`, and coverage is `0`. This lowers
confidence (§8). The engine never imputes metric values.

---

## 5. Derived metrics

| Metric | Formula |
|---|---|
| `operating_margin_vs_sector` | `operating_margin − median(operating_margin of sector peers)` (pp) |
| `fcf_positive` | `free_cash_flow_cr > 0` |
| `earnings_consistency` | `positive_eps_quarters_8 / 8` |
| `ttm_eps_growth` | needs ≥ 8 quarters: `(Σ last 4 / Σ prior 4 − 1)·100`; null if prior sum ≤ 0 |
| `rs_nifty_3m/6m` | stock return(L) − NIFTY 50 return(L), percentage points |
| `momentum_acceleration` | `ret_1m − ret_3m/3` |
| `directional_adx` | ADX if `+DI > −DI`, else `0` (a strong *down*trend earns nothing) |
| `pe_vs_sector` | `pe / median(pe of sector peers with pe > 0)`; if `pe ≤ 0` (loss-making) the value is `+∞`, so the normalized value is 0 |
| `pe_vs_history` | `pe / pe_median_5y`; `pe ≤ 0` → normalized 0 |
| `peg` | as supplied; `peg ≤ 0` → normalized 0 |
| `pb_vs_sector` | `pb / median(pb of sector peers)`; for financials the sub-weight is `weight_financial` |
| `sector_strength` | sector normalized strength (§6) |
| `risk_points` | total risk penalty points (§7) |

Sector medians are taken over the scored universe on the same as-of date and include the
stock itself.

### 5.1 Value-trap guard (Valuation)
Cheap is not automatically good. If **Fundamental Quality normalized < `min_quality`** or
**`eps_cagr_3y` < `min_eps_cagr_3y`**, then Valuation normalized = `min(normalized, cap)`, with
the reason `"Low valuation not fully rewarded: weak quality or shrinking earnings"`.

---

## 6. Sector engine

For each sector with ≥ 1 member:

| Metric | Definition |
|---|---|
| `median_rs_nifty_3m` | median of members' `rs_nifty_3m` |
| `pct_above_sma50` | share of members with close > SMA50 |
| `median_rs_nifty_1m` | median of members' (ret_1m − NIFTY ret_1m) |
| `median_profit_growth` | median of members' `profit_growth_yoy` (nulls ignored) |

Sector normalized strength = weighted average per §4.1 (config `sector.metrics`); sector score
= `round(normalized·100)`. Sectors are ranked by score descending, ties by name. Momentum label:
`Strong` if median_rs_3m ≥ 3, `Weak` if ≤ −3, else `Neutral`. Breadth label: `Positive` if
pct_above_sma50 ≥ 0.6, `Negative` if ≤ 0.4, else `Mixed`.

---

## 7. Risk engine

Each rule yields **elevated** (1 pt) or **extreme** (2 pts) per `risk_flags.points`.
Informational flags carry 0 points.

| Flag | Elevated | Extreme |
|---|---|---|
| `EXTREME_VOLATILITY` | vol60 > `volatility_60d.elevated` | > `extreme` |
| `LARGE_DRAWDOWN` | mdd1y < `max_drawdown_1y.elevated` | < `extreme` |
| `LOW_LIQUIDITY` | — | avg traded value < `min_avg_traded_value_cr` |
| `EXCESSIVE_VALUATION` | — (1 pt) when `pe_vs_sector` > `pe_vs_sector.extreme` | |
| `DEBT_CONCERN` (non-financial) | D/E > elevated, **or** interest coverage < `interest_coverage.elevated` | D/E > extreme |
| `EARNINGS_DETERIORATION` | — | the last two quarters both have lower EPS than the same quarter a year earlier (needs ≥ 6 quarters) |
| `PROMOTER_PLEDGE` | pledge > elevated | > extreme |
| `UNUSUAL_VOLUME` | relative volume > `relative_volume.elevated` | |
| `LARGE_GAP_MOVES` | gap_moves_60d ≥ `gap_moves_60d.elevated` | |
| `OVEREXTENDED` | distance above SMA200 > `dist_from_sma200.elevated` % | |
| `UPCOMING_EARNINGS` | info (0 pts): earnings event within `event_window_days` calendar days after as-of | |
| `CORPORATE_ACTION` | info (0 pts): dividend/split/bonus within the window | |

`EXCESSIVE_VALUATION` is a single-tier flag worth the *elevated* points. `LOW_LIQUIDITY` and
`EARNINGS_DETERIORATION` are single-tier flags worth the *extreme* points.

**Risk level** = first entry in `risk_levels` whose `max_points ≥ total points`
(`null` = unbounded). Risk component input `risk_points` = total points.

---

## 8. Confidence

Confidence measures how much the **score** can be trusted. It is not a forecast probability.

```
coverage   = Σ_c W_c·coverage_c / Σ_c W_c
dispersion = population std of the 8 component normalized values
base = HIGH   if coverage ≥ high_coverage and bars ≥ min_history_bars
       MEDIUM if coverage ≥ medium_coverage
       LOW    otherwise
if dispersion > dispersion_downgrade: downgrade one level (HIGH→MEDIUM→LOW)
```
Output both `confidence` (level) and `data_coverage` (rounded to 3 dp).

---

## 9. Market regime

Each factor is scored 0–100 using `regime.params`:

| Factor | Score |
|---|---|
| `index_trend` | NIFTY: 25·[close>SMA50] + 25·[close>SMA200] + 25·[SMA50>SMA200] + 25·ramp(ret_3m) |
| `bank_nifty_trend` | same formula on NIFTY BANK |
| `breadth` | 100·(1·ramp(advance_ratio) + 2·ramp(pct_above_sma50) + 1·ramp(pct_above_sma200)) / 4 over the scored universe; `advance_ratio = advances / (advances + declines)` for the last session |
| `volatility` | 100·(2·ramp(vix_level) + 1·ramp(vix_change_1m)) / 3 |
| `sector_participation` | 100·ramp(share of sectors with positive median 1M return) |
| `index_momentum` | 100·(ramp(nifty_ret_1m) + ramp(nifty_ret_6m)) / 2 |

Inside a factor, any unavailable input is dropped and the remaining inputs are re-weighted.
A factor with no available inputs scores `100·missing_data_neutral`. In `index_trend` an
unavailable `ret_3m` contributes `25·missing_data_neutral`.

`composite = Σ w_f·score_f / Σ w_f` (rounded to 1 dp).
Regime: `BULLISH` if composite ≥ bullish; `NEUTRAL` if ≥ neutral; `CAUTIOUS` if ≥ cautious; else
`BEARISH`.
Confidence (%) = `clip(round(100·(1 − mean_f(|score_f − composite|)/50)), lo, hi)` with
`confidence_bounds`. It never reaches 100, because the regime is never certain.

Reason text is templated from the two strongest and the weakest factor, for example *"Index
Trend and Market Breadth are supportive; Volatility (India VIX) is the weakest factor."*

---

## 10. Reasons & explanation

For every available metric:
- `s_m ≥ reason_thresholds.positive` → positive reason
- `s_m ≤ reason_thresholds.negative` → negative reason
- otherwise neutral (not surfaced as a headline)

Reason text is `"<label>: <formatted raw value>"`, for example `"ROE: 18.4%"`. Each reason carries an
**impact** = `W_c · (w_m/Σ_available w) · (s_m − 0.5)`, in score points relative to neutral.
The stock's headline `top_positives` / `top_negatives` are the 5 largest positive and 5 most
negative impacts across all components **except `risk`**, plus every risk flag with points > 0
appended to the negatives. Risk is explained through its flags rather than through the aggregate
`risk_points` metric. Ties are broken by metric key.

Value formatting by `unit`: `%` → `12.3%`, `pp` → `+1.2 pp`, `x` → `1.23x`, `₹ Cr` → `₹1,234 Cr`,
`ratio` → `0.12`, `share` → `75%`, `score100` → `36/100`, `pts` → `2`, binary → `Yes`/`No`,
`+∞` → `not meaningful (loss-making)`.

`key_reason` (one-liner for tables) = the labels of up to `key_reason.max_items` components
from `key_reason.components` with the highest normalized values among those ≥
`key_reason.min_normalized`, joined with " + ", for example `"Earnings Growth + Momentum + Technical Trend"`.
Ties are broken by component key. If no component qualifies, the value is `"No dominant strength"`.
Liquidity and Risk are excluded because they are hygiene factors: they are almost always near full
marks for large caps, so they say little about *why* a stock stands out.

---

## 11. Output contract

```jsonc
{
  "symbol": "HDFCBANK",
  "as_of": "2026-10-05",
  "data_provenance": "MOCK",           // MOCK | EOD | DELAYED | LIVE
  "config_version": "2026.10-v1",
  "total_score": 81.37,                 // 0–100
  "max_score": 100,
  "rank": 3,                            // within the scored universe, by total desc, ties by symbol
  "confidence": "HIGH",                 // HIGH | MEDIUM | LOW
  "data_coverage": 0.962,
  "risk_level": "LOW",                  // LOW | MEDIUM | HIGH | VERY_HIGH
  "risk_points": 1,
  "risk_flags": [{ "code": "UNUSUAL_VOLUME", "severity": "ELEVATED", "points": 1, "message": "..." }],
  "key_reason": "Earnings Growth + Momentum",
  "top_positives": [{ "component": "momentum", "metric": "rs_nifty_6m", "text": "...", "impact": 1.2 }],
  "top_negatives": [...],
  "components": {
    "fundamentals": {
      "label": "Fundamental Quality",
      "score": 21.4, "max": 25, "weight": 25,
      "normalized_score": 0.856,
      "coverage": 1.0,
      "raw_metrics": { "roe": 17.2, "roce": null },
      "metric_scores": { "roe": 0.657 },
      "reasons": [{ "text": "ROE: 17.2%", "impact": "positive", "metric": "roe", "points": 0.9 }],
      "data_timestamp": "2026-10-05"
    }
  }
}
```

Floats are rounded at output: scores 2 dp, normalized values 3 dp, raw metrics 4 dp.

### 11.1 Golden fixtures
`fixtures/` holds deterministic mock inputs (`<symbol>.json`, `universe.json`) and the expected
engine outputs (`expected/*.json`). Any implementation must reproduce them to within 1e-6 on
unrounded values or exactly on rounded output. Regenerate them **only** when this spec version
changes, and record the change in §12.

---

## 12. Changelog
- `2026.10-v1`: initial specification.
