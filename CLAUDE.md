# CLAUDE.md — NZ Quant Trading & Research Framework

Guidance for Claude Code (and any contributor) working in this repository.

## What this is

A modular Python quant trading framework for a **New Zealand-based trader**. It discovers
strategies online, translates them into structured rules, backtests them, validates them
against strict thresholds *after* NZ tax and FX drag, and executes paper trades via
Interactive Brokers (`ib_insync`) or Alpaca. All money figures are reported in **NZD**.

## Setup commands

```bash
python -m venv .venv
.venv\Scripts\activate              # Windows (PowerShell: .venv\Scripts\Activate.ps1)
pip install -r requirements.txt
cp .env.example .env                # fill in IBKR/Alpaca/FX keys — never commit .env
python -m cli.main                  # launch the interactive CLI dashboard
pytest                              # run tests
```

## Architecture

```
strategy_research/            # Phase 2 — automated discovery pipeline (see below)
  scrapers/                   #   GitHub/Reddit/RSS/arXiv API pulls (no raw HTML scraping)
  translator/rule_extractor.py#   free, deterministic vocabulary-based extraction (primary)
  translator/nl_to_rules.py   #   normalizes any candidate into a schema-validated StrategySpec
  distiller/gemini_client.py  #   Gemini API fallback for low-confidence/bulk input only
  vocabulary.py                #   controlled indicator/strategy-archetype vocabulary
  pipeline.py                  #   orchestrates scrape->extract->distill->translate->registry
quant_engine/         # Phase 4/5 — validation metrics, overfit guard, fundamental + sentiment screeners
nz_tax_fx/            # Phase 3 — FX conversion, FIF calculator (FDR/CV), tax reports
strategies/           # Phase 6 — mean_reversion, momentum, pairs_trading, breakout
backtester/           # Phase 4 — backtrader engine + historical data loader
execution_ibkr/       # Phase 7 — ib_insync connector, US-market-hours → NZT scheduling
execution_alpaca/     # Phase 7 — Alpaca connector
risk_management/      # Phase 7 — ATR/Kelly position sizing, stop-loss/target logic
cli/                  # Interactive dashboard entrypoint (python -m cli.main)
config/               # settings.py loads .env + config.yaml into one Settings object
data/                 # historical/, cache/, logs/ — gitignored, never commit market data
tests/
```

Each module currently contains a docstring-only stub stating its purpose and phase. Do not
add implementation logic to a module until its phase is reached (see Roadmap below) unless
the user explicitly asks to jump ahead.

**Module boundaries** — keep these separated; don't let tax/FX logic leak into strategies,
and don't let broker-specific code leak into the backtester:
- `strategies/` must stay broker-agnostic and currency-agnostic (works in raw price units).
- `nz_tax_fx/` is the only place FIF/FDR/CV math and USD/NZD conversion happens.
- `execution_ibkr/` and `execution_alpaca/` are the only places broker SDK calls happen.
- `quant_engine/validation/` is the only gate a strategy passes through before it's allowed
  into paper trading — it must apply tax drag and FX fees before checking thresholds.

## Automated strategy discovery pipeline (important — no manual steps)

The user explicitly wants **zero manual work**: no copy-pasting scraped content into a
browser, no running a separate tool by hand. The whole chain — scrape → distill → translate
→ backtest → validate → bin/keep — runs from a single trigger (`cli/main.py` option
`[1] Search Online Strategies`, or a future `scripts/` entrypoint), **on-demand only** (not
on a recurring schedule, per the user's explicit choice — revisit only if they ask).

Pipeline stages (`strategy_research/pipeline.py` is the orchestrator):

1. **Scrape** (`strategy_research/scrapers/`) — pull raw strategy-concept text from
   **official APIs only**, never fragile HTML scraping: GitHub Search API, Reddit API
   (e.g. r/algotrading), quant-blog RSS feeds, arXiv API for papers. Dedup against
   `data/cache/seen_sources.json` so the same source is never reprocessed.
2. **Extract — primary path, free and deterministic**
   (`strategy_research/translator/rule_extractor.py` + `strategy_research/vocabulary.py`):
   match scraped text against a controlled vocabulary of known indicators (RSI, MACD,
   Bollinger Bands, ATR, VWAP, z-score/spread, breakout+volume) and the four strategy
   archetypes this repo targets (mean reversion, momentum, pairs trading, breakout). This
   covers the large majority of scraped content with **no LLM call at all** — no quota risk,
   no hallucination risk in something that will eventually drive trades.
3. **Distill — fallback path, Gemini free tier** (`strategy_research/distiller/gemini_client.py`):
   used **only** when the rule extractor has low confidence, or the input is a genuinely
   large raw corpus (a long PDF, a huge forum thread) where Gemini's large context window is
   actually needed — this is the original justification for using Gemini at all; it is not
   the backbone of every scrape. Capped per run via `research_pipeline.max_gemini_calls_per_run`
   in `config.yaml`. On a 429/quota error, log and **skip that item — never crash the run**;
   free-tier quotas are tight and the pipeline must degrade gracefully. Note: Google's free
   tier may use submitted input to improve their models — acceptable here since inputs are
   already-public forum/blog text, but don't send anything else through this path.
4. **Translate & validate schema** (`strategy_research/translator/nl_to_rules.py`): whichever
   path produced the candidate, it must be normalized into a schema-validated `StrategySpec`
   (`strategy_research/strategy_spec.py`) before proceeding — reject anything that doesn't
   map cleanly onto the controlled vocabulary rather than guessing.
5. **Backtest → validate → bin/keep**: hand off to `backtester/` and
   `quant_engine/validation/` per the Strategy Lifecycle section below; `pipeline.py` is the
   concrete mechanism that appends to the strategy registry.

Claude Code's own role stays as before: write and maintain all of this as deterministic
Python — the pipeline *code* is engineered by Claude Code, but no step in the pipeline lets
an LLM (Gemini or otherwise) decide entry/exit rules unsupervised; extraction output is
always schema-validated before it can reach the backtester (see Guardrails below).

## NZ tax & timezone rules (do not get these wrong)

- **FIF (Foreign Investment Fund) regime**: applies once total cost of foreign shares
  exceeds **NZD $50,000** (the "de minimis" threshold), tracked in `nz_tax_fx/fif_calculator.py`.
  Below the threshold, ordinary capital gains/dividend rules apply instead.
- **FDR (Fair Dividend Rate)**: taxes **5% of the opening market value** of foreign shares
  for the tax year, regardless of actual gain — this is usually the default/required method.
- **CV (Comparative Value)**: taxes the **actual increase in value** over the year
  (closing value − opening value − purchases + sales + dividends). Only usable in limited
  cases (e.g. when CV would produce a loss and the taxpayer qualifies to use it).
- Where a choice exists, take the **lower** of FDR/CV tax liability (`fif_method: auto` in
  `config.yaml`) — but note some structures (e.g. attributing interests held at a loss) have
  restrictions on which method is selectable. Flag this rather than silently assuming.
- **NZ tax year**: 1 April – 31 March (`tax_year_end: "03-31"` in config.yaml), not calendar year.
- **FX conversion**: all P&L, cost basis, and thresholds are evaluated in **NZD**, converted
  using the **USD/NZD rate at the time of the transaction** for realized amounts and
  period-end rates for unrealized/opening-value calculations — don't use a single blended
  rate across a tax year.
- **Timezones**: home timezone is `Pacific/Auckland` (NZST/UTC+12, NZDT/UTC+13 — DST-aware,
  and NZ/US daylight saving transitions don't align, so the NZT offset to US market hours
  shifts by an hour twice a year at different dates than the US). US market session is
  `America/New_York` 09:30–16:00 ET. Always convert with a tz-aware library (`pytz`/`zoneinfo`),
  never a fixed UTC offset, and always re-derive the NZT session window rather than hardcoding it.

## Validation gate (non-negotiable thresholds)

A strategy may not proceed to paper trading unless, **after** applying NZ tax drag and FX
fees (`quant_engine/validation/`, thresholds in `config.yaml` under `validation_thresholds`):
- Sharpe Ratio > 1.5
- Max Drawdown < 15%
- Profit Factor > 1.3

`overfit_guard.py` must also confirm out-of-sample / walk-forward performance doesn't
materially decay versus in-sample before a strategy is considered validated.

## Strategy lifecycle — bin the losers, keep the winners

Every strategy discovered/translated/backtested must go through a pass/fail lifecycle, not
just be generated and left lying around:

1. Translate (`strategy_research/`) → implement (`strategies/`) → backtest (`backtester/`)
   → validate (`quant_engine/validation/`) against the thresholds above.
2. **Strategies that fail validation are rejected, not fixed by relaxing thresholds or
   retrying until something passes** — that's p-hacking / overfitting to the backtest.
   Log the failed spec and its metrics (e.g. under `data/logs/` or a `strategy_registry`
   — decide the concrete mechanism in Phase 4/6) and move on to the next candidate.
3. Only strategies that clear validation get promoted into `strategies/` as real,
   paper-trading-eligible implementations. Maintain a clear record of what was tried,
   what passed, and what was rejected and why — don't silently discard the history, since
   it prevents re-testing the same dead-end idea later.
4. Re-validate periodically (walk-forward on new data) — a strategy that passed once is not
   permanently trusted; performance decay should demote it back out of live paper trading.

## Guardrails — do not repeat common AI-trader mistakes

These are known failure modes in AI-built trading systems. Treat every one of these as a
hard constraint, not a suggestion:

- **Never use the LLM as the trading decision-maker.** Don't build a flow where the model
  is asked "what stock should I buy today" or similar, and don't let an LLM's own judgment
  substitute for computed signals. LLMs hallucinate, echo mainstream news hype, and get
  quantitative nuance wrong. The model's role is fixed to *writing code*: data pipelines,
  scrapers, translating natural-language rules into structured logic, and wiring APIs. All
  actual trading math — indicators, signals, position sizing, P&L, tax — must execute as
  plain deterministic Python (pandas/numpy/pandas-ta/backtrader/scikit-learn), never as an
  LLM call at runtime.
- **Guard against lookahead / training-data leakage in backtests.** Because LLMs (and any
  data pulled from them) may have memorized historical prices/news, a strategy can look
  "unbeatable" purely because the model already "knew" what happened. Backtests must use
  strictly time-sliced historical data from a real market-data API (never from LLM
  knowledge or recall), with walk-forward / out-of-sample splits, and must never let a
  strategy's rules or parameters be tuned using information from outside its training
  window. `quant_engine/validation/overfit_guard.py` is responsible for enforcing this.
- **Don't rely on fragile, arbitrary web scraping for price/market data.** HTML layouts
  change, IPs get blocked, and scrapers silently break. Use standardized market-data APIs
  (`yfinance`, broker APIs, or similar) for all price/fundamentals data. Scraping
  (`strategy_research/scrapers/`) is only for strategy *concept* text (forum posts, blog
  write-ups, README files) — never for OHLCV or fundamentals data that a proper API can
  provide.
- **Never ignore operational costs.** A strategy that looks profitable gross is worthless
  if broker commissions, bid/ask spread, USD/NZD FX conversion spread, and NZ FIF tax drag
  eat the edge. Every backtest and validation run must subtract realistic spread/slippage
  and FX fees (`fx_fee_pct` in `config.yaml`) and apply NZ tax drag (`nz_tax_fx/`) *before*
  checking Sharpe/MaxDD/Profit Factor — a strategy is only "valid" net of all of these, per
  the Validation gate above. Never report or act on a pre-cost, pre-tax return figure as if
  it were realistic.

## GitHub / version control workflow

- Repo: private, created via `gh repo create` under the authenticated GitHub account.
- **Never commit**: `.env`, API keys, `data/cache/`, `data/historical/`, `data/logs/`, `.venv/`,
  DB files, backtest result artifacts (see `.gitignore`).
- Commit and push at the completion of every major milestone (end of each roadmap phase,
  or any working, tested increment) — don't let uncommitted work pile up across phases.
- Standard sync shortcuts from repo root:

```bash
git add -A                      # review with `git status` first — never blind-add secrets
git commit -m "<milestone summary>"
git push
git pull --rebase               # sync before starting new work
git checkout -b feature/<name>  # for larger/riskier changes; merge back to main when validated
```

## Roadmap (implementation phases)

1. **Scaffold** (done) — directory structure, configs, .gitignore, CLAUDE.md, GitHub repo.
2. **Strategy Discovery Engine** — forum/blog/GitHub scrapers + NL-to-rules translator (`strategy_research/`).
3. **NZ Tax & FX Engine** — FX converter, FIF/FDR/CV calculator, tax reports (`nz_tax_fx/`).
4. **Backtesting & Validation Engine** — backtrader integration, metrics, overfit guard, and a strategy registry (tried/passed/rejected record — see Strategy Lifecycle above) (`backtester/`, `quant_engine/validation/`).
5. **Screener & Sentiment Engine** — fundamental screener + news sentiment scoring (`quant_engine/screeners/`).
6. **Strategy Library** — implement mean reversion, momentum, pairs trading, breakout; only validated strategies get promoted here (`strategies/`).
7. **Execution & Risk Engine** — IBKR/Alpaca connectors, market-hours scheduling, ATR/Kelly sizing, stop/target logic (`execution_ibkr/`, `execution_alpaca/`, `risk_management/`).
8. **CLI wiring & end-to-end paper trading** — connect all menu options in `cli/main.py` to the real modules; run full paper-trading loop.
9. **Live-readiness review** — re-validate thresholds, tax handling, and risk controls before any live capital is considered.

Confirm with the user before starting each new phase — build and commit one phase at a time.
