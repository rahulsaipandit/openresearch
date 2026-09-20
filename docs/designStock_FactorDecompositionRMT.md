# Factor Decomposition (PCA + Random Matrix Theory) — Design Note

## Source

A pasted article (no URL given, so it isn't linkable/citable as a primary source) walking through PCA-based "eigenportfolios" and Marchenko-Pastur random matrix theory (RMT) for equity covariance matrices, in the style of statistical arbitrage. It cites three real, well-known papers as further reading:

- Laloux, Cizeau, Bouchaud, Potters, *"Noise Dressing of Financial Correlation Matrices"* (1999)
- Avellaneda & Lee, *"Statistical Arbitrage in the US Equities Market"* (2010)
- Grinold & Kahn, *"Active Portfolio Management"*

## Accuracy review

The article is substantively accurate and matches the published literature. Checked claims:

| Claim | Verdict |
|---|---|
| A 500-stock covariance matrix has 500·501/2 = 125,250 distinct entries | Correct arithmetic (n(n+1)/2, including variances on the diagonal) |
| ~2y of daily data ≈ 500 observations | Correct (≈252 trading days/year × 2) |
| PCA on the covariance matrix = eigenvectors/eigenvalues; each eigenvector is an "eigenportfolio" | Correct, standard terminology from Avellaneda & Lee |
| First eigenportfolio has ~all-positive loadings and is "the market" | Well-documented empirical result (Laloux et al., Plerou et al.) |
| Marchenko-Pastur noise-band upper edge ≈ 4 for N=500, T=500 (Q=T/N=1) | Correct — MP upper edge = σ²(1+1/√Q)²; with Q=1, σ²=1 that's exactly 4 |
| Market eigenvalue is "tens of times larger" than the noise band | Consistent with published figures (Laloux et al. report the top eigenvalue tens of times the MP edge) |
| Only a handful of eigenvalues clear the band; the rest are noise | Matches RMT literature's typical finding of O(5–20) significant factors out of hundreds |
| CAPM = 1-factor version, Fama-French = named multi-factor version | Accurate framing; standard in the factor-investing literature |

Where it oversimplifies (worth knowing, doesn't undermine the core claims): correlations are non-stationary, so a covariance matrix estimated over one 2-year window doesn't hold in the next; the MP law strictly assumes i.i.d. returns, which equity returns aren't (fat tails, volatility clustering) — in practice this pushes the *true* noise threshold a bit higher than the clean MP formula suggests, so naively trusting "everything above 4" slightly overstates how many factors are real. None of this changes the article's conclusions, it's a caveat for implementation.

## How this could fit OpenResearch

This is a different shape of idea than the arxiv trading-signals paper ([designStock_TechnicalSignalsAndBacktesting.md](designStock_TechnicalSignalsAndBacktesting.md)) — it's about **portfolio-level risk decomposition**, not single-ticker signal generation. The natural home is next to [`PortfolioOptimizerAgent`](../agents/stock/portfolio_optimizer.py), which already builds a covariance matrix (`_expected_return_and_cov`) from multi-ticker return histories via cvxpy — the exact input PCA needs.

**In scope — a diversification check.** The article's most actionable point (Step 3, "your diversified book is probably one bet in a costume") is directly implementable: given a portfolio's holdings, decompose the covariance matrix, keep only the eigenvalues that clear the Marchenko-Pastur band, and report what fraction of total portfolio variance the top (market) factor alone explains. A portfolio where >80-90% of variance loads on factor 1 is not diversified no matter how many names it holds — that's a genuinely useful, cheap, deterministic thing to surface next to the existing optimization output.

Proposed: `agents/stock/factor_decomposition.py` — `FactorDecompositionAgent`, pure numeric (numpy `eigh` on the covariance matrix already computed in `portfolio_optimizer.py`), no LLM, same philosophy as every other numeric agent in this repo. Output: a `FactorExposure` schema (variance % explained by factor 1, 2, 3…, number of factors surviving the MP threshold, a `concentration_warning: bool`). Attach as an optional field on `PortfolioOptimizationResult`, same pattern used for Equibles/signals additions elsewhere.

**Out of scope — statistical arbitrage.** The article's actual trading idea (strip out factor exposure, trade the mean-reverting residual) is a live, continuously-monitored trading strategy — it needs real-time execution, position management, and risk controls that don't exist in this codebase and aren't what OpenResearch is (a research-brief generator, not an autonomous trader). Building the diversification check doesn't commit us to building the trading strategy on top of it; they're separable, and the trading half would be a much larger scope decision to make deliberately, not a byproduct of adding factor exposure reporting.

## Bottom line

Adopt the diversification-check piece (cheap, deterministic, fits the existing portfolio optimizer's data flow). Do not adopt the residual stat-arb trading strategy — different scope of product, not something to back into via a design note. Not implementing either yet; this is scoping only, same as the technical-signals note was before implementation was requested separately.
