# Research: TensorTrade — Reinforcement-Learning Trading Framework

Source: [tensortrade-org/tensortrade](https://github.com/tensortrade-org/tensortrade), Apache 2.0 licensed.

## What it is

TensorTrade is an open-source Python framework for **building, training, and evaluating reinforcement-learning (RL) agents for algorithmic trading** — not a data source, and not a forecasting model like Kronos ([docs/researchKronos.md](researchKronos.md)). It provides composable building blocks (environments, action schemes, reward schemes, data feeds) that you wire together into a custom `gymnasium`-compatible trading environment, then train an RL agent (typically via Ray RLlib/PPO) against it.

Stack: `numpy`, `pandas`, `gymnasium` (the maintained successor to OpenAI `gym` — the project has migrated off `gym`), `tensorflow`/`keras` for the RL policy networks, `ta` for technical-indicator feature engineering, Ray/RLlib for distributed training ([requirements.txt](https://github.com/tensortrade-org/tensortrade/blob/master/requirements.txt)).

## Architecture

```
Observer ──> Agent ──> ActionScheme ──> Portfolio
(features)  (policy)   (BSH/Orders)     (wallets)
    ^                                       │
    └──────── RewardScheme <────────────────┘
                 (PBR)

DataFeed ──> Exchange ──> Broker ──> Trades
```

| Component | Purpose | Default |
|---|---|---|
| ActionScheme | Converts agent output into orders | BSH (Buy/Sell/Hold) |
| RewardScheme | Computes the RL learning signal | PBR (Position-Based Returns) |
| Observer | Builds the observation vector fed to the agent | Windowed features |
| Portfolio | Tracks wallets/positions | e.g. USD + BTC |
| Exchange | Simulates order execution | Configurable commission |

Package layout: `tensortrade/env` (the RL environment), `tensortrade/feed` (data pipeline — chained `Stream`/`DataFeed` objects, seen in the example code below), `tensortrade/oms` (order management: `Instrument`, `Wallet`, `Portfolio`, `Exchange`, `ExchangeOptions`), `tensortrade/agents`, `tensortrade/data`, `tensortrade/stochastic` (synthetic price-process generators for testing).

## Usage — the example workflow (from the screenshots + README)

1. **Prepare CSVs of historical OHLCV bars.** The workflow shown pulls bars from `yfinance` and enriches them with `pandas_ta` indicators (log return, RSI, MACD) before writing `training.csv` / `evaluation.csv` — i.e. it needs the same kind of already-fetched historical price data that both the existing yfinance-based [agents/stock/data_fetcher.py](../agents/stock/data_fetcher.py) and Kronos rely on. TensorTrade doesn't fetch live/real-time prices itself.
2. **Build a config + environment factory** (`create_env(config)`): reads the CSV, wraps each column as a `Stream`/`DataFeed`, defines an `Instrument`/`Wallet`/`Portfolio`, an `Exchange` with commission settings, a reward scheme (`default.rewards.SimpleProfit` or PBR), an action scheme (`default.actions.BSH`), and assembles it all via `default.create(...)` into a `gymnasium.Env`.
3. **Initialize and run training via Ray.** `ray.init()`, `register_env("MyTrainingEnv", create_env)`, then `tune.run("PPO", config={...})` — the config carries the registered env name, `env_config` (the training-vs-evaluation CSV paths and window/loss settings from step 2), RLlib knobs (`num_workers`, `num_gpus`, `framework: "torch"`, `clip_rewards`), and hyperparameters. Hyperparameters (network size `fcnet_hiddens`, learning rate, minibatch size) are swept with `tune.grid_search([...])` — Ray Tune trains one run per combination and reports back per Optuna/Tune's usual trial-comparison flow, matching the README's own `train_optuna.py` script for hyperparameter search. A separate `evaluation_config` (non-exploratory, held-out `evaluation.csv`) is checked periodically (`evaluation_interval`) during training, not just after.
4. **Evaluate** the trained policy on the held-out `evaluation.csv` window.

**Reward schemes are pluggable and hand-written, not learned.** The default `PBR` (Position-Based Returns) reward, subclassing `TensorTradeRewardScheme`, is a compact illustration of the whole framework's style: it derives a `Stream` for the price delta (`price.diff()`), tracks a `position` state (`-1`/`1`, flipped in `on_action()` based on the agent's discrete action), and multiplies delta × position each step as `get_reward()`'s return value — i.e. the agent is rewarded for being long when price rises and short when it falls, each step, not just on realized trade P&L. This is the RL-specific piece with no analogue in the Stock feature's existing deterministic `SignalAgent`/backtest system: TensorTrade doesn't predict anything (unlike Kronos) or track live prices (unlike the OpenStock-derived watchlist work) — it *learns a policy* by trial and error against whatever reward function you hand-design, and the reward function is exactly the kind of thing the README's own results (see below) say is hard to get right (naive "reward = P&L each step" schemes learn to overtrade, and get eaten by commissions).

## Reported results (from their own README)

| Configuration | Test P&L | vs Buy-and-Hold |
|---|---|---|
| Agent (0% commission) | +$239 | +$594 |
| Agent (0.1% commission) | -$650 | -$295 |
| Buy-and-Hold | -$355 | — |

Notably, the project's own conclusion is that the trained agent shows *directional* predictive skill at zero commission, but realistic trading commissions (0.1%) erase the edge because the learned policy trades too frequently — this is called out explicitly as their top open problem ("Trading frequency reduction" is priority #1 in their own contributing guide).

## Licensing & requirements

- **License:** Apache 2.0 — permissive.
- **Python:** 3.11 or 3.12 required (3.14 explicitly unsupported — TensorFlow doesn't support it yet, per [COMPATIBILITY.md](https://github.com/tensortrade-org/tensortrade/blob/master/COMPATIBILITY.md)).
- **Heavy dependency footprint:** TensorFlow (CUDA optional but recommended for training), Ray/RLlib for distributed training — this is a much heavier install than Kronos's plain-PyTorch inference path, and heavier than anything currently in [pyproject.toml](../pyproject.toml).

## Relevance to OpenResearch's Stock feature

TensorTrade solves a **different problem** than everything researched so far:

- [docs/researchStockSolutions.md](researchStockSolutions.md) (OpenStock) — live price tracking/alerts.
- [docs/researchKronos.md](researchKronos.md) (Kronos) — supervised forecasting of future OHLCV bars.
- **TensorTrade — learning a trading *policy*** (when to buy/sell/hold) via trial-and-error against a simulated market, optimizing realized P&L directly rather than predicting prices.

That's a materially different scope than the Stock feature's current design: [pipelines/stock_pipeline.py](../pipelines/stock_pipeline.py) produces one-shot, explainable research briefs (fundamentals + sentiment + deterministic technical signals + backtest), not an autonomous trading agent, and the project doesn't currently execute trades at all. Bringing in TensorTrade would mean:

- A heavy new dependency chain (TensorFlow + Ray) purely for RL training infrastructure, most of which (distributed hyperparameter search, live training loops) has no use once a policy is merely being *researched* rather than run live.
- A shift in kind, not just degree — from "generate a research brief a human reads" to "train and (eventually) deploy an autonomous decision-making agent." That's a product-scope decision, not an implementation detail.
- The project's own experiments show the naive approach doesn't clear realistic trading costs — so even on its own terms this isn't a drop-in win; it would require real ongoing RL research investment (reward shaping, commission-aware training) to be worth anything.

**Recommendation:** not adopted. Of the three RL/ML approaches researched (OpenStock's live tracking, Kronos's forecasting, TensorTrade's RL trading policies), only the first was implemented (see [docs/researchStockSolutions.md](researchStockSolutions.md)) because it filled a real gap in existing scope. TensorTrade is the least aligned with the Stock feature's current "informative research brief" design — revisit only if the project's goal explicitly expands to autonomous strategy execution, not analysis.
