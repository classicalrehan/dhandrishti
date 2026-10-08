# Rule study, October 2026

Run on 2026-10-08 with `pnpm rule-study` (real Kite prices, NIFTY 200 universe). Generated tables
below; this summary was written after reading them.

## Question
Can simple trading rules on top of the DhanDrishti score improve return or reduce the worst fall,
in a way that holds up on data the rules were not chosen on?

## Method
- Every rule replays the **live paper engine** (whole shares, Zerodha charges, next-open fills) from ₹1 lakh.
- Two windows, fixed in advance: **train** Dec 2023 to Mar 2025 and **validation** Apr 2025 to Oct 2026.
  A rule counts only if it helps in both.
- Yardsticks: the baseline rules (paper portfolio #1), NIFTY 50, and an equal-weight portfolio of
  every scored stock. Survivorship bias (today's NIFTY 200 applied to the past) inflates every row,
  including the equal-weight one, so compare rows with each other, not with NIFTY.

## Findings
| Rule | Verdict | Why |
|---|---|---|
| Cash (or 2 holdings) in bear markets | **Rejected** | Slightly worse in train, clearly worse in validation (−1.6% vs +4.5% even with the kill switch off). The regime signal turns bearish after the fall and sells before the rebound. |
| Weekly rebalance + bear cash | Rejected | Worst in train (+15.6%), best in validation (+32.8%): a flip like that is noise, and charges double. |
| Fixed 10% stop-loss (current default) | **Weakest stop setting** | 15% or no stop did better in both windows: 10% sells on normal swings. |
| 15% stop / no stop | Better in both | Train +47.9% / +61.2% vs +44.7%; validation +12.5% / +14.1% vs +4.5%; similar worst fall. |
| Keep while in the top 20 | Better in both, fewer trades | Train +49.4%, validation +6.1%; 20% fewer trades. |
| Require 1 year of history | Better in both, small | Train +48.0%, validation +6.7%; avoids recent listings with short, noisy histories. |
| Quarterly (portfolio #2) | Mixed | Better in train, worse in validation; low charges. |
| Top 10 instead of 5 | Mixed | Worse in train, better in validation. |

**Combined (15% stop + keep top 20 + 1 year of history)**, checked afterwards and therefore weaker
evidence: train +59.3% (baseline +44.7%), validation **+18.0%** (baseline +4.5%, equal-weight +15.4%,
NIFTY −4.0%), worst fall about −17% in both. Added as paper portfolio #3 on 2026-10-08.

## What this does *not* show
- **No proven stock-picking skill.** Across the whole universe the score barely predicts next-month
  returns (IC ≈ 0.01). The baseline lost to simply owning all 200 stocks in validation; the refined
  rules beat it by 2.6 points, which one 18-month window cannot separate from luck.
- **The windows are short** (16 and 18 months) and share one market cycle.
- **Survivorship bias** affects everything here; live paper trading has none.

## Next
- Let portfolios #1, #2 and #3 run side by side for at least 3 to 6 months.
- Real fundamentals (55 of the 100 score points are neutral today) are the largest remaining gap.


Each rule replays the live paper engine from ₹1,00,000 in each window: whole shares, Zerodha delivery charges, signals at the close, fills at the next open. Universe: today's NIFTY 200 (survivorship bias inflates every row, including the equal-weight benchmark).

Base rules (portfolio #1): capital=100000.0, top_n=5, rebalance=monthly, max_risk=MEDIUM, min_confidence=None, stop_loss_pct=10.0, rank_buffer=10, kill_switch_pct=18.0, lookback_bars=300, regime_slots=None, min_history_bars=None, trailing_stop_pct=None

### Train (2023-12-01 to 2025-03-28)

| Rule | Return | CAGR | Worst fall | Sharpe | Charges | Trades | Stop-loss sells | Invested | Kill switch |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Baseline (portfolio #1) | +44.7% | +32.2% | -17.9% | 1.26 | ₹4,699 | 125 | 12 | 89% | — |
| Quarterly, keep top 15 (portfolio #2) | +53.1% | +38.0% | -20.6% | 1.43 | ₹2,013 | 52 | 2 | 77% | 2025-01-13 |
| Cash in bear markets | +42.6% | +30.8% | -16.6% | 1.26 | ₹4,397 | 116 | 11 | 78% | — |
| 2 holdings in bear markets | +38.5% | +27.9% | -18.3% | 1.16 | ₹4,627 | 122 | 12 | 82% | 2025-03-13 |
| No stop-loss | +61.2% | +43.5% | -19.9% | 1.55 | ₹4,860 | 116 | 0 | 83% | 2025-01-21 |
| Stop-loss 15% | +47.9% | +34.4% | -18.7% | 1.34 | ₹4,601 | 116 | 4 | 81% | 2025-01-21 |
| Trailing stop 15% | +39.4% | +28.6% | -18.4% | 1.19 | ₹4,435 | 116 | 9 | 78% | 2025-01-16 |
| Keep while top 20 | +49.4% | +35.5% | -18.7% | 1.42 | ₹3,956 | 100 | 8 | 81% | 2025-01-28 |
| Min 1 year of history | +48.0% | +34.5% | -16.0% | 1.33 | ₹4,707 | 125 | 11 | 90% | — |
| Top 10, keep top 20 | +25.3% | +18.6% | -18.2% | 0.93 | ₹4,822 | 222 | 22 | 83% | 2025-02-28 |
| Weekly, cash in bear markets | +15.6% | +11.6% | -17.1% | 0.64 | ₹9,543 | 279 | 5 | 79% | — |
| Combined: bear cash + 1y history + keep top 20 | +57.0% | +40.7% | -16.8% | 1.54 | ₹3,860 | 98 | 7 | 82% | — |
| *NIFTY 50* | +16.0% | +11.9% | -15.8% | 0.90 | ₹0 | — | — | — | — |
| *Equal-weight universe* | +33.9% | +24.7% | -20.2% | 1.31 | ₹347 | — | — | — | — |

### Validation (2025-04-01 to 2026-10-08)

| Rule | Return | CAGR | Worst fall | Sharpe | Charges | Trades | Stop-loss sells | Invested | Kill switch |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Baseline (portfolio #1) | +4.5% | +3.0% | -16.7% | 0.25 | ₹3,139 | 113 | 8 | 91% | — |
| Quarterly, keep top 15 (portfolio #2) | +0.3% | +0.2% | -18.5% | 0.10 | ₹1,018 | 36 | 9 | 44% | 2026-03-23 |
| Cash in bear markets | -13.5% | -9.1% | -19.7% | -0.52 | ₹2,390 | 86 | 8 | 61% | 2026-05-12 |
| 2 holdings in bear markets | -12.3% | -8.3% | -18.5% | -0.46 | ₹2,503 | 90 | 8 | 63% | 2026-05-12 |
| No stop-loss | +14.1% | +9.1% | -17.0% | 0.54 | ₹3,325 | 113 | 0 | 95% | — |
| Stop-loss 15% | +12.5% | +8.0% | -17.0% | 0.49 | ₹3,275 | 113 | 1 | 94% | — |
| Trailing stop 15% | +11.8% | +7.6% | -15.0% | 0.49 | ₹3,210 | 113 | 8 | 92% | — |
| Keep while top 20 | +6.1% | +4.0% | -17.9% | 0.30 | ₹2,559 | 93 | 5 | 94% | — |
| Min 1 year of history | +6.7% | +4.4% | -16.7% | 0.32 | ₹3,124 | 111 | 8 | 91% | — |
| Top 10, keep top 20 | +14.0% | +9.0% | -14.9% | 0.58 | ₹3,468 | 188 | 11 | 90% | — |
| Weekly, cash in bear markets | +32.8% | +20.5% | -9.2% | 1.20 | ₹6,173 | 194 | 1 | 75% | — |
| Combined: bear cash + 1y history + keep top 20 | -9.3% | -6.2% | -18.4% | -0.31 | ₹2,051 | 74 | 5 | 61% | 2026-05-11 |
| *NIFTY 50* | -4.0% | -2.7% | -15.6% | -0.14 | ₹0 | — | — | — | — |
| *Equal-weight universe* | +15.4% | +9.9% | -12.8% | 0.68 | ₹329 | — | — | — | — |
