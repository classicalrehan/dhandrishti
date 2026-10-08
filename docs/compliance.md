# Compliance assumptions (DRAFT — not legal advice)

_Status: assumptions to be verified by qualified Indian securities counsel before any public launch._

## Current usage (2026-10-06)
**Internal, personal use only. No SaaS launch, and not offered to other people.** Most of the
items below apply only if that changes. Personal use still has to respect each data source's
own terms.

| Area | Internal personal use | If shared with others, free or paid |
|---|---|---|
| SEBI Research Analyst / Investment Adviser registration | Not needed for your own research and decisions | Likely needed. Get legal advice |
| Exchange data (NSE/BSE) | Use under the terms of the source you get it from: currently **Zerodha Kite Connect**, for the account holder's personal use (docs/kite.md); no redistribution | Needs a redistribution licence from the exchange or a licensed vendor |
| Index data (NIFTY indices) | Same as above | NSE Indices licence for display or redistribution |
| Fundamentals | Source's terms (vendor or company filings); scraping sites is often against their terms | Commercial licence |
| Sending data to Claude (AI) | Allowed if the data source's terms don't forbid sending it to third-party services | Same, plus privacy duties for other users' questions |
| TimescaleDB / Caddy / Next.js etc. | Free for internal use (TimescaleDB under the Timescale License, others open source) | Check the Timescale License before offering it as a hosted database service |

## Positioning
DhanDrishti is **equity research and decision-support software**. It is not an automated trading
system, does not place orders, and does not manage client money.

## Assumptions to verify (do not treat as settled)
1. **Investment advice / research analysis.** Publishing stock-level scores, rankings and "why it
   ranks highly" explanations to the public may fall under SEBI regulations governing Research
   Analysts and/or Investment Advisers. Registration requirements, disclosures and permitted
   content must be confirmed. **Unverified.**
2. **Personalised recommendations.** Any feature that tailors output to a user's portfolio, risk
   profile or goals (for example portfolio tracking combined with suggestions or alerts) may
   change the product's regulatory classification. **Flag such features for review before
   building them.**
3. **Market-data licensing.** Redistributing NSE/BSE prices, including delayed or end-of-day data
   and index values (NIFTY indices are licensed separately), generally requires a data licence.
   Each data provider's terms must be reviewed. **Unverified.**
4. **Holiday calendar.** `packages/shared/src/nse-holidays.json` is a placeholder marked
   `verified: false` and must be replaced from the official NSE circular.
5. **AI output.** LLM-generated explanations must stay grounded in engine output and must not
   present scores as recommendations to buy or sell.
6. **Data sent to the AI provider.** The research assistant sends user questions and DhanDrishti
   tool data (scores, prices, fundamentals) to Anthropic's API. With MOCK data this is harmless.
   **Before connecting licensed market data, confirm that the data licence permits sending it to
   a third-party AI service**, and review privacy obligations for user questions (India's DPDP
   Act). **Unverified.**

## Features that could change classification (flag explicitly)
| Feature | Risk |
|---|---|
| Broker integration / order placement | Out of scope for V1; would require separate review |
| Personalised portfolio suggestions | May constitute investment advice |
| Alerts phrased as actions ("buy now") | Must be phrased as data events, not instructions |
| Performance claims from backtests | Must carry hypothetical-performance disclaimers (the /backtest page does) |
| AI assistant answering about a user's own holdings | Personalisation; may constitute investment advice |

## Product guardrails already in place
- Scores come from a deterministic, documented engine (`packages/quant-spec/SPEC.md`); an LLM cannot
  change them.
- Every output carries `data_provenance`; mock data is always labelled `MOCK`.
- Missing data is shown as "Data unavailable" and is never imputed.
- Regime confidence is bounded below 100%.

## Standard disclaimer (draft wording)
> DhanDrishti provides research and analytical information for educational and decision-support
> purposes only. It is not investment advice or a recommendation to buy, sell or hold any
> security. Scores are outputs of a quantitative model and may be wrong. Past performance does
> not guarantee future results. Consult a SEBI-registered adviser before investing.
