"""
FactorDecompositionAgent — PCA + Random Matrix Theory diversification check.

Extracts eigenportfolios via PCA on a portfolio's return correlation matrix
and uses the Marchenko-Pastur law to separate genuine market/sector factors
from sampling noise (Laloux, Cizeau, Bouchaud, Potters, "Noise Dressing of
Financial Correlation Matrices", 1999; Avellaneda & Lee, "Statistical
Arbitrage in the US Equities Market", 2010). Reports what share of portfolio
variance loads on the top ("market") factor — a portfolio where most of the
variance comes from one factor isn't diversified no matter how many names it
holds. See docs/Stocks/designStock_FactorDecompositionRMT.md for the design
rationale and docs/Stocks/researchStockSolutions.md for context.

Pure numeric agent, no LLM call — same philosophy as PortfolioOptimizerAgent.
"""

import numpy as np

from schemas.portfolio import FactorExposure

CONCENTRATION_THRESHOLD = 0.8  # top factor explaining >80% of variance = not diversified
TOP_FACTORS_REPORTED = 5


class FactorDecompositionAgent:
    def analyze(self, return_matrix: np.ndarray) -> FactorExposure:
        """return_matrix: rows=observations (days), columns=tickers, raw (non-annualized) returns."""
        n_obs, n_tickers = return_matrix.shape
        if n_tickers < 2 or n_obs < 2:
            raise ValueError("Need at least 2 tickers and 2 observations for factor decomposition.")

        corr = np.corrcoef(return_matrix, rowvar=False)
        eigenvalues = np.linalg.eigvalsh(corr)[::-1]  # descending; sums to n_tickers

        q = n_obs / n_tickers
        mp_upper_edge = (1 + np.sqrt(1 / q)) ** 2
        n_significant = max(int(np.sum(eigenvalues > mp_upper_edge)), 1)

        variance_explained = eigenvalues / n_tickers
        top_share = float(variance_explained[0])

        return FactorExposure(
            n_tickers=n_tickers,
            n_observations=n_obs,
            mp_noise_threshold=round(float(mp_upper_edge), 4),
            n_significant_factors=n_significant,
            variance_explained_by_factor=[round(float(v), 4) for v in variance_explained[:TOP_FACTORS_REPORTED]],
            top_factor_variance_share=round(top_share, 4),
            concentration_warning=top_share > CONCENTRATION_THRESHOLD,
        )
