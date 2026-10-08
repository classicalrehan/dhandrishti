import { describe, expect, it } from "vitest";
import { componentWeights, SCORING_CONFIG, validateScoringConfig } from "./scoring";

describe("SCORING_CONFIG (from quant-spec)", () => {
  it("is valid and sums to 100", () => {
    expect(validateScoringConfig(SCORING_CONFIG)).toEqual([]);
  });
  it("exposes the v1 weights", () => {
    expect(componentWeights()).toEqual({
      fundamentals: 25,
      earningsGrowth: 20,
      momentum: 15,
      technicalTrend: 15,
      valuation: 10,
      liquidity: 5,
      sectorStrength: 5,
      risk: 5,
    });
  });
});
