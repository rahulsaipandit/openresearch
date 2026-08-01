# Finance AI Requirements

## Overview

Build a desktop financial research assistant using a Tauri frontend with a FastAPI Python backend. The app should be an LLM-powered stock analyzer that aggregates recent market data, company financials, and news, then produces structured investment intelligence that is easy to consume for non-experts.

The goal is to provide a reliable analysis starting point, not a final trading recommendation. The product should help users avoid endlessly searching YouTube and blogs by delivering focused, sourced, and transparent financial insights.

## Primary User Needs

1. Highly detailed breakdowns of a company’s fundamentals.
2. Insider and Congress trade alerts.
3. Side-by-side comparisons of any two stocks, showing where each one excels.
4. A watchlist of up to 20 stocks.
5. Summarized earnings calls.
6. Insights into the ETFs and institutions that hold any stock.
7. Five-year trend analysis plus a previous-year summary.

## Product Vision

The app should feel like a stock analyzer bot that can answer questions such as:
- "Is it a good time to invest in Yes Bank?"
- "How are the current financials of Reliance Industries looking?"

The system should return a comprehensive analysis in under a minute using recent data, while clearly stating that the output is a research aid and not investment advice.

## Target Architecture

- Desktop frontend: **Tauri**
- Backend API: **FastAPI**
- Core logic: Python
- AI layer: LLMs with retrieval augmentation and structured prompt design
- Data sources: real-time price feeds, fundamentals APIs, news feeds, filings, insider data, ownership data, and optionally sentiment sources

## Deployment Constraints

- Host the Python backend in a **venv** or **Docker container** depending on developer preference and local Windows setup.
- Ensure dependencies, API keys, and environment configuration are isolated and repeatable.
- Target local LLMs that fit an RTX 4070 with **~10 GB VRAM**.
- Prefer compact models such as quantized 7B/8B variants, mixed CPU/GPU inference, or client-server LLM hosting via LM Studio.
- Avoid excessively large models and instead use retrieval and prompt engineering to reduce reliance on model scale.

## Core Features

### 1. Fundamentals Breakdown
- Revenue, gross profit, operating income, net income
- Margin trends, cash flow, balance sheet health
- Growth rates and key ratios (P/E, ROE, ROA, debt/equity, current ratio)
- Revenue/earnings history and forward guidance if available
- Clear positives and negatives for financial health

### 2. Insider and Congress Trade Alerts
- Track insider transactions from filings
- Extract recent buys/sells by executives and directors
- Detect congressional trading activity or related alerts
- Show significance, timing, and potential context

### 3. Stock Comparison
- Compare any two stocks side by side
- Highlight strengths and weaknesses in fundamentals, valuation, growth, profitability, and sentiment
- Include summary of where each company is better
- Support both absolute and relative comparisons

### 4. Watchlist
- Save up to 20 stocks
- Display recent price change, news highlights, and quick sentiment score
- Allow one-click analysis from watchlist items

### 5. Earnings Summary
- Summarize recent earnings calls and results
- Extract key beats/misses, revenue guidance, margin commentary, and management tone
- Provide concise takeaways and action considerations

### 6. ETF and Institutional Ownership Insights
- Show ETF exposure for a stock
- Identify top institutional holders
- Highlight ownership changes and concentration trends

### 7. Trend Analysis
- Five-year trend view for price, revenue, and key metrics
- Previous-year summary with highlights and change indicators
- Visual and textual trend analysis

## AI Requirements

### Reliable AI workflow
- Do not rely on base LLM training data for facts
- Augment the model with real-time data and document context
- Use structured prompts and function calls for stable output
- Enforce evidence-backed reasoning whenever possible
- Add auditability through source citations or data references

### Required capabilities
- Accept natural language queries about stocks and financials
- Extract ticker symbols reliably from user input
- Fetch a mix of data: prices, fundamentals, news, filings, insider activity, ownership data
- Generate a structured analysis containing thesis, evidence, positives, negatives, and suggestions
- Support comparative queries across two tickers
- Summarize earnings and filings in plain language

## Data and Integration Requirements

### Recommended data sources
- Fundamentals API: SimFin, Polygon, or EODHD
- Price data: Polygon, Yahoo Finance, Alpha Vantage, or equivalent
- News and sentiment: StockNewsAPI, news API, or financial search feed
- Filings and SEC data: EDGAR or Valyu-like financial sources
- Insider/ownership data: datasets that include insider filings and institutional holdings
- Congress trade data: public congressional financial disclosures or specialized API if available

### Integration priorities
- Prioritize data sources with recent, clean fundamentals and filings coverage
- Use bulk data or caching for repeated finance queries
- Maintain API key management securely in backend environment variables

## Recommended Open Source Stack

- `EdgarTools`: use as the primary SEC filings and insider/ownership data engine. It is Python-native, MIT-licensed, and built for AI-friendly pipelines.
- `OpenBB`: use for broad market data ingestion, fundamentals, equities/crypto/macro coverage, and backend data orchestration.
- `FinanceToolkit`: use for financial ratios, valuation models, technical metrics, and structured analysis functions.
- `OpenTerminalUI`: use as an architectural and local-LLM integration reference for FastAPI + frontend design and evidence-backed AI agent workflows.
- Keep `Qlib` and `LEAN` as optional advanced modules for future quant research or execution capabilities, not MVP core.
- Avoid direct reuse of `FinceptTerminal` and `Neuberg` because of restrictive licensing and incompatible architecture. Use them only for UX inspiration if needed.

## UX and Interaction

- Query box for natural language questions
- Watchlist panel with up to 20 stocks
- Comparison mode for two stock symbols
- Earnings summary view for the latest quarter
- Trend dashboard with charts for five-year and one-year summaries
- Alerts panel for insider/Congress trades
- Clear disclaimer: research assistant, not investment advice

## Personal Memory & Context System

Build support for personal investor context so the app can use market data more helpfully.

### What to store
- Investor profile: experience, background, goals, time horizon, risk tolerance, portfolio size, strategy style
- Strategy rules: drawdown limits, position sizing, rebalancing rules, entry/exit criteria, watchlist priorities
- Portfolio state: current positions, weights, target allocations
- Watchlist and trade ideas: themes, tickers, potential setups, catalysts
- Prompt templates: saved prompts, query patterns, session workflows

### Folder setup
Create a local folder with five Markdown files and one CSV file to store your personal investment context and memory:

1. `Investor-profile.md`
   - Everything about you as an investor.
   - Include experience/background, goals and time horizon, risk tolerance, portfolio size, preferred sectors, and decision style.

2. `Strategy.md`
   - Your investment framework.
   - Include maximum drawdown, rebalancing parameters, position sizing targets, entry and exit criteria, and rules for adding/removing positions.

3. `Portfolio.csv`
   - Your current positions and weightings.
   - Include symbol, shares, cost basis, market value, current weight, target weight, and notes.

4. `Watchlist.md`
   - Your full watchlist.
   - Include sectors, tickers, potential setups, catalysts, and monitoring notes.

5. `Prompts.md`
   - Your saved prompts.
   - Store prompt templates, question structures, and common analysis workflows so they can be reused each session.

### Scheduled tasks ideas
- Complete portfolio analysis
- Daily news review
- Overnight market moves summary
- Trading ideas based on rule-based parameters

## Nonfunctional Requirements

- Fast enough to respond within ~60 seconds for a full analysis
- Modular backend so new data sources and tools can be added easily
- Secure local desktop app with data privacy by default
- Stable ability to render charts and rich text from backend results

## Notes

- The system should be built as a research support tool, not a fully automated trading system.
- Strong prompts and example-guided output formatting are critical.
- The product should encourage users to verify conclusions and use the AI output as a starting point.
