# Price-factor study, October 2026

Experiment `20261008-141112-price-factors-2013-2026` (`pnpm factor-study --daily-stability 120`).
673 weekly cross-sections, March 2013 to October 2026, 201 stocks, 114,461 stock-dates. No
fundamentals exist yet, so Quality, Growth and Valuation could not be tested; the composite is
effectively the price-only score. The generated tables follow this summary.

## The caveat that dominates everything
The universe is today's NIFTY 200 applied back to 2013. A stock that was small and illiquid in 2013
is in this list *because* it later became one of India's 200 largest companies. That shows up most
clearly in the **Liquidity** factor: low-liquidity stocks beat high-liquidity ones in every period
(rank IC −0.10 at 60 days, t = −8, negative on 81% of sample dates and in all four periods). That is almost
certainly survivorship, not a real "buy illiquid stocks" effect. The same bias makes **Risk** look
backwards at long horizons, and makes every factor look better in the low-liquidity tercile. Until the
universe is point-in-time, treat absolute numbers as flattering and focus on comparisons and stability.

## What the data says
| Finding | Evidence | Confidence |
|---|---|---|
| **Momentum and technical trend carry real signal, mainly at 2 to 6 months** | Rank IC +0.044 / +0.046 at 60D (t ≈ 3), +0.070 / +0.065 at 120D (t 3.4–4.0); positive in 2013–16, 2017–19 and 2020–22 | Moderate. Consistent with decades of momentum research; magnitudes inflated by survivorship |
| **It has faded recently** | 2023–2026: momentum +0.002, trend +0.015, composite −0.010 at 60D | Matches the earlier backtest (no edge in 2024–26). Could be a temporary momentum drawdown or a changed market; four years is too short to tell |
| **It fails in bear markets** | In BEARISH regimes, composite −0.053 (20D) / −0.046 (60D); momentum and trend also negative | Consistent with "momentum crashes" at market turns. The regime label arrives late, so it did not help as a cash rule either |
| **The composite is weaker than its best parts** | Composite 60D +0.030 (t 1.8) vs momentum +0.044 and trend +0.046 | Liquidity (5 points, rewards high liquidity) and Risk pull the other way in this universe |
| **Score buckets separate only at the bottom** | 60D periods: deciles 1–6 earn +6.1% to +6.9% each; deciles 7 and 10 lag (+4.4%, +5.0%, worst fall −63% for decile 10). Monotonicity +0.79 | The score is better at flagging stocks to avoid than at ranking the top |
| **Concentration does not help** | Top 5 vs Top 20 (60D): same mean return, volatility 49% vs 28%, net CAGR 22% vs 27% | Holding 15–20 names is better than 5 for this signal |
| **Rankings churn fast** | Top 10 still in top 10 after 20 sessions: 30%; after 60 sessions: 16% | A monthly rebalance replaces ~70% of a top 10, so costs and rank buffers matter |
| **Missing-data variants made no difference yet** | Engine rule, per-metric neutral shrinkage and a 1-year-history filter all give the same IC | Expected with fundamentals absent for every stock. The question must be re-run once fundamentals cover some stocks |
| **Flagged price jumps do not drive the results** | Excluding the 14 flagged stocks changes composite IC by ≤ 0.006 | Robust |
| **Sectors** | Momentum/trend IC positive in Banking, Financial Services, Healthcare, Capital Goods; about zero in FMCG and IT; negative in Metal | Sector sizes are small (10–32 stocks); suggestive only |

## What this means for decisions
- There is a **weak, real-looking price signal**, but not yet a demonstrated edge: it is inflated by
  survivorship, near zero in the last four years, and harmful in bear markets.
- Nothing here justifies machine learning yet. The next gains come from data: a survivorship-free
  universe and point-in-time fundamentals.
- Candidates for later review (not changed now): the Liquidity component's role (use as an eligibility
  filter rather than a scored factor?); holding more names; slower rebalancing.

## Next research steps
1. **Point-in-time universe**: reconstruct historical NIFTY 200 membership, and add stocks that were
   members but have since dropped out and still trade (Kite has them). Truly delisted stocks remain a gap.
2. **Fundamentals with exact publication dates** (see the route below).
3. Re-run this study; then test the missing-data policy, factor weights and portfolio construction.

## Generated tables

### 1. Rank IC by factor and horizon
Mean rank IC (Newey-West t-stat). Constant factors (no data) show —.

| Factor | 5D | 20D | 60D | 120D | 252D |
|---|---:|---:|---:|---:|---:|
| Quality | — | — | — | — | — |
| Growth | — | — | — | — | — |
| Momentum | +0.011 (+1.7) | +0.025 (+2.4) | +0.044 (+3.0) | +0.070 (+4.0) | +0.075 (+3.4) |
| Technical trend | +0.015 (+2.5) | +0.029 (+2.8) | +0.046 (+3.0) | +0.065 (+3.4) | +0.061 (+2.8) |
| Valuation | — | — | — | — | — |
| Liquidity | -0.010 (-2.2) | -0.045 (-6.0) | -0.097 (-8.0) | -0.147 (-9.1) | -0.218 (-8.3) |
| Sector strength | +0.023 (+3.6) | +0.031 (+2.9) | +0.041 (+2.9) | +0.055 (+4.1) | +0.057 (+3.3) |
| Risk (less is better) | +0.018 (+2.7) | +0.006 (+0.5) | -0.013 (-0.6) | -0.036 (-1.2) | -0.065 (-1.8) |
| Composite score | +0.017 (+2.5) | +0.023 (+2.1) | +0.030 (+1.8) | +0.040 (+2.1) | +0.027 (+1.2) |
| Composite, missing→neutral per metric | +0.017 (+2.5) | +0.023 (+2.0) | +0.029 (+1.8) | +0.040 (+2.1) | +0.027 (+1.2) |
| Price-only composite | +0.017 (+2.5) | +0.023 (+2.1) | +0.030 (+1.8) | +0.040 (+2.1) | +0.027 (+1.2) |

### 2. Detail for the composite and price factors

| Factor | Horizon | Rank IC mean | median | std | ICIR | hit rate | t (NW) | Pearson IC | dates | stock-dates |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Composite score | 5D | +0.0165 | +0.0288 | 0.1721 | +0.10 | 55% | +2.48 | +0.0167 | 667 | 113482 |
| Composite score | 20D | +0.0233 | +0.0279 | 0.1761 | +0.13 | 56% | +2.10 | +0.0270 | 664 | 112873 |
| Composite score | 60D | +0.0295 | +0.0315 | 0.1677 | +0.18 | 58% | +1.84 | +0.0345 | 656 | 111257 |
| Composite score | 120D | +0.0405 | +0.0399 | 0.1510 | +0.27 | 59% | +2.13 | +0.0401 | 644 | 108842 |
| Composite score | 252D | +0.0269 | +0.0416 | 0.1589 | +0.17 | 61% | +1.25 | +0.0165 | 618 | 103638 |
| Price-only composite | 5D | +0.0165 | +0.0297 | 0.1721 | +0.10 | 55% | +2.48 | +0.0167 | 667 | 113482 |
| Price-only composite | 20D | +0.0233 | +0.0276 | 0.1761 | +0.13 | 56% | +2.10 | +0.0270 | 664 | 112873 |
| Price-only composite | 60D | +0.0295 | +0.0315 | 0.1677 | +0.18 | 58% | +1.84 | +0.0345 | 656 | 111257 |
| Price-only composite | 120D | +0.0404 | +0.0397 | 0.1510 | +0.27 | 59% | +2.13 | +0.0401 | 644 | 108842 |
| Price-only composite | 252D | +0.0269 | +0.0415 | 0.1588 | +0.17 | 62% | +1.25 | +0.0165 | 618 | 103638 |
| Momentum | 5D | +0.0112 | +0.0237 | 0.1669 | +0.07 | 55% | +1.74 | +0.0197 | 667 | 113482 |
| Momentum | 20D | +0.0247 | +0.0214 | 0.1658 | +0.15 | 55% | +2.38 | +0.0372 | 664 | 112873 |
| Momentum | 60D | +0.0444 | +0.0454 | 0.1544 | +0.29 | 61% | +3.01 | +0.0572 | 656 | 111257 |
| Momentum | 120D | +0.0701 | +0.0663 | 0.1385 | +0.51 | 68% | +4.00 | +0.0784 | 644 | 108842 |
| Momentum | 252D | +0.0750 | +0.0910 | 0.1570 | +0.48 | 73% | +3.45 | +0.0767 | 618 | 103638 |
| Technical trend | 5D | +0.0154 | +0.0274 | 0.1619 | +0.09 | 57% | +2.45 | +0.0199 | 667 | 113482 |
| Technical trend | 20D | +0.0292 | +0.0377 | 0.1652 | +0.18 | 58% | +2.83 | +0.0356 | 664 | 112873 |
| Technical trend | 60D | +0.0463 | +0.0501 | 0.1565 | +0.30 | 62% | +3.04 | +0.0529 | 656 | 111257 |
| Technical trend | 120D | +0.0647 | +0.0714 | 0.1424 | +0.45 | 67% | +3.36 | +0.0665 | 644 | 108842 |
| Technical trend | 252D | +0.0609 | +0.0731 | 0.1474 | +0.41 | 69% | +2.75 | +0.0541 | 618 | 103638 |
| Liquidity | 5D | -0.0104 | -0.0107 | 0.1194 | -0.09 | 46% | -2.25 | -0.0328 | 667 | 113482 |
| Liquidity | 20D | -0.0446 | -0.0461 | 0.1203 | -0.37 | 33% | -5.98 | -0.0672 | 664 | 112873 |
| Liquidity | 60D | -0.0969 | -0.1040 | 0.1142 | -0.85 | 19% | -7.95 | -0.1215 | 656 | 111257 |
| Liquidity | 120D | -0.1466 | -0.1518 | 0.1066 | -1.38 | 8% | -9.06 | -0.1728 | 644 | 108842 |
| Liquidity | 252D | -0.2176 | -0.2225 | 0.1126 | -1.93 | 3% | -8.30 | -0.2532 | 618 | 103638 |
| Sector strength | 5D | +0.0231 | +0.0177 | 0.1657 | +0.14 | 55% | +3.60 | +0.0290 | 667 | 113482 |
| Sector strength | 20D | +0.0311 | +0.0297 | 0.1739 | +0.18 | 57% | +2.90 | +0.0385 | 664 | 112873 |
| Sector strength | 60D | +0.0408 | +0.0508 | 0.1713 | +0.24 | 62% | +2.90 | +0.0494 | 656 | 111257 |
| Sector strength | 120D | +0.0550 | +0.0686 | 0.1635 | +0.34 | 65% | +4.12 | +0.0596 | 644 | 108842 |
| Sector strength | 252D | +0.0575 | +0.0614 | 0.1710 | +0.34 | 62% | +3.32 | +0.0610 | 618 | 103638 |
| Risk (less is better) | 5D | +0.0179 | +0.0259 | 0.1724 | +0.10 | 55% | +2.69 | -0.0085 | 667 | 113482 |
| Risk (less is better) | 20D | +0.0057 | +0.0099 | 0.1871 | +0.03 | 52% | +0.47 | -0.0286 | 664 | 112873 |
| Risk (less is better) | 60D | -0.0131 | -0.0232 | 0.1989 | -0.07 | 46% | -0.61 | -0.0577 | 656 | 111257 |
| Risk (less is better) | 120D | -0.0358 | -0.0293 | 0.1958 | -0.18 | 45% | -1.20 | -0.1003 | 644 | 108842 |
| Risk (less is better) | 252D | -0.0649 | -0.0683 | 0.1778 | -0.37 | 38% | -1.76 | -0.1517 | 618 | 103638 |

### 3. By market regime
Mean rank IC at 20D / 60D (dates).

| Factor | BEARISH | BULLISH | CAUTIOUS | NEUTRAL |
|---|---:|---:|---:|---:|
| Composite score | -0.053 / -0.046 (110) | +0.038 / +0.047 (366) | +0.064 / +0.032 (76) | +0.023 / +0.046 (104) |
| Price-only composite | -0.053 / -0.046 (110) | +0.038 / +0.047 (366) | +0.064 / +0.032 (76) | +0.023 / +0.045 (104) |
| Momentum | -0.057 / -0.034 (110) | +0.043 / +0.067 (366) | +0.061 / +0.038 (76) | +0.021 / +0.052 (104) |
| Technical trend | -0.053 / -0.029 (110) | +0.049 / +0.069 (366) | +0.060 / +0.035 (76) | +0.026 / +0.053 (104) |
| Liquidity | -0.021 / -0.074 (110) | -0.060 / -0.117 (366) | -0.012 / -0.056 (76) | -0.039 / -0.079 (104) |
| Sector strength | -0.030 / -0.046 (110) | +0.048 / +0.065 (366) | +0.049 / +0.025 (76) | +0.024 / +0.059 (104) |
| Risk (less is better) | -0.034 / -0.061 (110) | +0.005 / -0.013 (366) | +0.034 / +0.007 (76) | +0.030 / +0.024 (104) |

### 4. By period
Mean rank IC at 20D / 60D (dates).

| Factor | 2013-2016 | 2017-2019 | 2020-2022 | 2023-2026 |
|---|---:|---:|---:|---:|
| Composite score | +0.030 / +0.030 (184) | +0.036 / +0.091 (148) | +0.023 / +0.013 (150) | +0.007 / -0.010 (174) |
| Price-only composite | +0.030 / +0.030 (184) | +0.036 / +0.091 (148) | +0.023 / +0.013 (150) | +0.007 / -0.010 (174) |
| Momentum | +0.039 / +0.059 (184) | +0.025 / +0.085 (148) | +0.025 / +0.035 (150) | +0.010 / +0.002 (174) |
| Technical trend | +0.034 / +0.055 (184) | +0.044 / +0.109 (148) | +0.021 / +0.010 (150) | +0.019 / +0.015 (174) |
| Liquidity | -0.050 / -0.116 (184) | -0.027 / -0.059 (148) | -0.050 / -0.104 (150) | -0.049 / -0.103 (174) |
| Sector strength | +0.061 / +0.066 (184) | +0.024 / +0.059 (148) | +0.040 / +0.051 (150) | -0.001 / -0.011 (174) |
| Risk (less is better) | +0.002 / -0.035 (184) | +0.035 / +0.053 (148) | +0.002 / -0.029 (150) | -0.011 / -0.033 (174) |

### 5. By liquidity tercile (size proxy)
Mean rank IC at 20D / 60D (dates).

| Factor | high liquidity | low liquidity | mid liquidity |
|---|---:|---:|---:|
| Composite score | +0.018 / +0.015 (656) | +0.047 / +0.079 (656) | +0.043 / +0.065 (656) |
| Price-only composite | +0.018 / +0.015 (656) | +0.047 / +0.079 (656) | +0.043 / +0.065 (656) |
| Momentum | +0.010 / +0.009 (656) | +0.042 / +0.083 (656) | +0.037 / +0.060 (656) |
| Technical trend | +0.016 / +0.017 (656) | +0.044 / +0.081 (656) | +0.040 / +0.059 (656) |
| Liquidity | +0.004 / -0.004 (442) | -0.033 / -0.070 (656) | -0.007 / -0.020 (646) |
| Sector strength | +0.011 / -0.004 (656) | +0.050 / +0.079 (656) | +0.038 / +0.055 (656) |
| Risk (less is better) | +0.018 / +0.019 (656) | +0.011 / -0.024 (656) | +0.004 / +0.003 (656) |

### 6. By sector (sectors with 10+ stocks)
Mean rank IC at 60D within each sector (dates).

| Sector | Composite | Momentum | Technical trend |
|---|---:|---:|---:|
| Auto | -0.006 (656) | +0.029 (656) | +0.025 (656) |
| Banking | +0.059 (656) | +0.038 (656) | +0.067 (656) |
| Capital Goods | -0.007 (656) | +0.041 (656) | +0.051 (656) |
| Consumer Services | +0.106 (77) | +0.086 (77) | +0.086 (77) |
| FMCG | -0.028 (656) | -0.002 (656) | -0.006 (656) |
| Financial Services | +0.054 (656) | +0.073 (656) | +0.059 (656) |
| Healthcare | +0.020 (656) | +0.044 (656) | +0.045 (656) |
| IT | -0.017 (492) | +0.021 (492) | +0.009 (492) |
| Metal | -0.019 (656) | -0.059 (656) | -0.027 (656) |

### 7. Composite score as a portfolio, 20-session holding periods
Non-overlapping periods; equal weight; net = after round-trip costs on turnover. Monotonicity (deciles 1→10 vs return, Spearman): +0.75.

| Bucket | Periods | Mean return | Excess vs NIFTY | Hit rate vs NIFTY | Volatility | Worst fall | Turnover | Net CAGR | Sharpe | Sortino |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Top 5 | 165 | +1.86% | +0.95% | 56% | +25.8% | -33.8% | +0.81 | +18.7% | +0.79 | +0.88 |
| Top 10 | 165 | +1.96% | +1.05% | 59% | +22.2% | -27.5% | +0.70 | +21.7% | +1.00 | +1.01 |
| Top 20 | 165 | +1.97% | +1.06% | 62% | +20.8% | -28.0% | +0.58 | +22.6% | +1.10 | +1.03 |
| Top decile | 165 | +2.08% | +1.17% | 64% | +21.2% | -28.9% | +0.60 | +24.2% | +1.13 | +1.08 |
| Bottom decile | 165 | +1.13% | +0.22% | 52% | +26.3% | -55.9% | +0.54 | +9.2% | +0.47 | +0.45 |
| Decile 1 | 165 | +2.08% | +1.17% | 64% | +21.2% | -28.9% | +0.60 | +24.2% | +1.13 | +1.08 |
| Decile 2 | 165 | +1.93% | +1.02% | 62% | +21.0% | -26.3% | +0.77 | +21.1% | +1.03 | +1.02 |
| Decile 3 | 165 | +1.99% | +1.08% | 66% | +21.4% | -37.3% | +0.83 | +21.6% | +1.03 | +1.01 |
| Decile 4 | 165 | +1.99% | +1.08% | 62% | +20.5% | -32.2% | +0.85 | +21.8% | +1.07 | +1.02 |
| Decile 5 | 165 | +2.07% | +1.16% | 65% | +19.5% | -30.3% | +0.85 | +23.2% | +1.18 | +1.16 |
| Decile 6 | 165 | +1.79% | +0.88% | 64% | +21.0% | -46.0% | +0.86 | +18.7% | +0.93 | +0.86 |
| Decile 7 | 165 | +1.52% | +0.60% | 56% | +20.8% | -48.1% | +0.84 | +14.7% | +0.77 | +0.72 |
| Decile 8 | 165 | +1.95% | +1.04% | 61% | +23.3% | -41.3% | +0.84 | +20.6% | +0.93 | +0.95 |
| Decile 9 | 165 | +1.54% | +0.63% | 52% | +23.8% | -49.6% | +0.77 | +14.6% | +0.70 | +0.65 |
| Decile 10 | 165 | +1.13% | +0.22% | 52% | +26.3% | -55.9% | +0.54 | +9.2% | +0.47 | +0.45 |

### 7. Composite score as a portfolio, 60-session holding periods
Non-overlapping periods; equal weight; net = after round-trip costs on turnover. Monotonicity (deciles 1→10 vs return, Spearman): +0.79.

| Bucket | Periods | Mean return | Excess vs NIFTY | Hit rate vs NIFTY | Volatility | Worst fall | Turnover | Net CAGR | Sharpe | Sortino |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Top 5 | 55 | +6.90% | +3.95% | 62% | +48.8% | -39.0% | +0.90 | +22.4% | +0.57 | +1.31 |
| Top 10 | 55 | +6.74% | +3.79% | 64% | +33.4% | -36.0% | +0.84 | +25.1% | +0.82 | +1.46 |
| Top 20 | 55 | +6.88% | +3.94% | 64% | +28.0% | -33.9% | +0.73 | +27.1% | +1.00 | +1.39 |
| Top decile | 55 | +6.92% | +3.97% | 60% | +29.3% | -37.6% | +0.75 | +26.9% | +0.96 | +1.40 |
| Bottom decile | 55 | +4.99% | +2.04% | 55% | +36.6% | -62.9% | +0.69 | +14.9% | +0.55 | +0.69 |
| Decile 1 | 55 | +6.92% | +3.97% | 60% | +29.3% | -37.6% | +0.75 | +26.9% | +0.96 | +1.40 |
| Decile 2 | 55 | +6.47% | +3.52% | 71% | +22.5% | -30.1% | +0.84 | +26.0% | +1.16 | +1.37 |
| Decile 3 | 55 | +6.24% | +3.29% | 69% | +24.8% | -31.7% | +0.88 | +24.2% | +1.01 | +1.09 |
| Decile 4 | 55 | +6.11% | +3.16% | 65% | +23.9% | -32.4% | +0.88 | +23.8% | +1.03 | +1.27 |
| Decile 5 | 55 | +6.46% | +3.51% | 69% | +25.3% | -42.9% | +0.90 | +25.0% | +1.03 | +1.08 |
| Decile 6 | 55 | +6.18% | +3.23% | 64% | +28.4% | -42.7% | +0.89 | +22.8% | +0.88 | +1.07 |
| Decile 7 | 55 | +4.44% | +1.49% | 62% | +23.5% | -34.1% | +0.89 | +15.7% | +0.75 | +0.81 |
| Decile 8 | 55 | +5.66% | +2.71% | 56% | +27.0% | -36.6% | +0.88 | +20.7% | +0.84 | +1.01 |
| Decile 9 | 55 | +6.11% | +3.16% | 58% | +29.6% | -39.9% | +0.84 | +22.3% | +0.83 | +1.06 |
| Decile 10 | 55 | +4.99% | +2.04% | 55% | +36.6% | -62.9% | +0.69 | +14.9% | +0.55 | +0.69 |

### 8. Missing data and eligibility variants
Mean rank IC (t).

| Variant | 5D | 20D | 60D | 120D | 252D |
|---|---:|---:|---:|---:|---:|
| Composite (as engine) | +0.017 (+2.5) | +0.023 (+2.1) | +0.030 (+1.8) | +0.040 (+2.1) | +0.027 (+1.2) |
| Composite, missing→neutral per metric | +0.017 (+2.5) | +0.023 (+2.0) | +0.029 (+1.8) | +0.040 (+2.1) | +0.027 (+1.2) |
| Composite, only stocks with 1y+ history | +0.016 (+2.4) | +0.022 (+1.9) | +0.029 (+1.8) | +0.041 (+2.1) | +0.028 (+1.3) |
| Price-only composite | +0.017 (+2.5) | +0.023 (+2.1) | +0.030 (+1.8) | +0.040 (+2.1) | +0.027 (+1.2) |
| Composite, excluding flagged stocks | +0.014 (+2.2) | +0.021 (+1.9) | +0.028 (+1.7) | +0.036 (+1.9) | +0.021 (+1.0) |
| Momentum, excluding flagged stocks | +0.009 (+1.5) | +0.023 (+2.2) | +0.044 (+3.0) | +0.066 (+3.6) | +0.070 (+3.2) |

Stocks flagged for >35% one-day moves (excluded in the sensitivity row): 360ONE, ADANIENT, CANBK, CGPOWER, HINDPETRO, IDEA, INDUSINDBK, MFSL, NMDC, PNB, POLICYBZR, SBICARD, UNIONBANK, YESBANK.

### 9. Ranking stability

| Gap | Rank correlation | Top 10 still in top 10 | Pairs |
|---|---:|---:|---:|
| 1 sessions | +0.98 | +0.80 | 119 |
| 5 sessions | +0.90 | +0.62 | 672 |
| 20 sessions | +0.69 | +0.30 | 669 |
| 60 sessions | +0.42 | +0.16 | 661 |
