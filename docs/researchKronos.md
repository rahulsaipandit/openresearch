# Research: Kronos — Foundation Model for Candlestick Forecasting

Source: [shiyu-coder/Kronos](https://github.com/shiyu-coder/Kronos), MIT licensed, associated with an AAAI 2026 paper ([arXiv:2508.02739](https://arxiv.org/abs/2508.02739)).

## What it is

Kronos bills itself as "the first open-source foundation model for financial candlesticks (K-lines)" — a pretrained model for forecasting OHLCV (open/high/low/close/volume) time series, trained on data from 45+ global exchanges. It is **not** a data source or a live-price tracker — it's purely a forecasting/analysis layer that consumes historical OHLCV bars you've already fetched from somewhere else (e.g. yfinance) and predicts future bars.

## Architecture

A two-stage, decoder-only foundation model:

1. **Tokenizer** — quantizes continuous multi-dimensional OHLCV data into hierarchical discrete tokens.
2. **Transformer** — a GPT-style autoregressive Transformer pretrained on those token sequences, treating price bars roughly the way a language model treats word tokens.

Model zoo (4 sizes):

| Model | Params | Tokenizer | Context |
|---|---|---|---|
| Kronos-mini | 4.1M | Kronos-Tokenizer-2k | 2048 |
| Kronos-small | 24.7M | Kronos-Tokenizer-base | 512 |
| Kronos-base | 102.3M | Kronos-Tokenizer-base | 512 |
| Kronos-large | 499.2M | Kronos-Tokenizer-base | 512 (weights not released) |

Output is a full forecast of future open/high/low/close/volume/amount, not just a single price.

## Usage / interface

Python library, no hosted API. Weights are on HuggingFace Hub under the `NeoQuasar` org (e.g. `NeoQuasar/Kronos-small`, `NeoQuasar/Kronos-Tokenizer-base`).

```python
tokenizer = KronosTokenizer.from_pretrained(...)
model = Kronos.from_pretrained(...)
predictor = KronosPredictor(model, tokenizer, max_context=512)
```

- **Input:** a pandas DataFrame with `open, high, low, close` (volume/amount optional), plus `x_timestamp` (historical timestamps) and `y_timestamp` (future timestamps to forecast). The README's example uses 5-minute A-share bars — any bar frequency works, it just needs to be already-fetched historical data.
- **Output:** `predictor.predict(...)` returns a DataFrame of forecasted OHLCV values indexed by the future timestamps. Generation is stochastic (temperature `T`, nucleus `top_p`, `sample_count` to average multiple sampled paths) since it's autoregressive token sampling, not a single deterministic point estimate. `predict_batch` parallelizes across multiple series on GPU.

Repo also ships a `finetune/` pipeline (built on Microsoft's Qlib for A-share data prep) and a `webui/` directory, plus a live demo forecasting BTC/USDT 24h ahead.

## Licensing & requirements

- **License:** MIT — permissive, no unusual restrictions.
- **Dependencies:** `numpy`, `pandas`, `torch>=2.0.0`, `einops`, `huggingface_hub`, `matplotlib`, `tqdm`, `safetensors`. Python 3.10+.
- **Hardware:** no hard GPU requirement for basic inference — Kronos-mini/small are small enough to run on CPU. Batch prediction and finetuning explicitly use GPU / `torchrun` multi-GPU training.

## Relevance to OpenResearch's Stock feature

Kronos is not a live-price-fetching tool, so it doesn't compete with or replace the existing yfinance-based [agents/stock/data_fetcher.py](../agents/stock/data_fetcher.py) or the new [agents/stock/quote_fetcher.py](../agents/stock/quote_fetcher.py) (see [docs/researchStockSolutions.md](researchStockSolutions.md)). It would sit **on top of** that data as a forecasting layer — conceptually the same role as the existing deterministic [agents/stock/signal_agent.py](../agents/stock/signal_agent.py) / `BacktestEngine` (see [docs/designStock_TechnicalSignalsAndBacktesting.md](designStock_TechnicalSignalsAndBacktesting.md)), except ML-forecast-based rather than rule-based candlestick/indicator signals.

Adopting it would mean:
- A new `torch` dependency (currently absent from [pyproject.toml](../pyproject.toml)) and a model-weights download step.
- A design decision about whether probabilistic ML price forecasts belong alongside the project's current deterministic, explainable signal/backtest approach — the existing system deliberately avoids LLM-generated numbers for signals (see `SignalAgent`'s docstring rationale), and Kronos's stochastic sampling raises a similar "can we trust/explain this number" question.

**Recommendation:** not adopted as part of this pass. Worth revisiting as its own scoped decision if/when forecasting (vs. today's rule-based signals + LLM-synthesized research briefs) becomes a stated goal for the Stock feature.
