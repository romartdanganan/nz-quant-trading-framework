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
quant_engine/
  validation/metrics.py      # Phase 4 — Sharpe/MaxDD/ProfitFactor from an equity curve + trades
  validation/overfit_guard.py# Phase 4 — walk-forward in/out-of-sample Sharpe decay check
  validation/validator.py    # Phase 4 — the single candidate->validated/rejected gate
  validation/runner.py       # Phase 4 — drives validator.py over every "single"-kind registry candidate
  validation/pairs_validator.py # Phase 6 — cointegration gate + thresholds for pairs candidates
  validation/pairs_runner.py    # Phase 6 — drives pairs_validator.py over every "pairs"-kind candidate
  validation/incubation.py      # Phase 7 — forward-test decision logic: validated->incubating->proven/rejected
  screeners/fundamental_screener.py # Phase 5 — deterministic P/E, PEG, D/E, revenue growth, earnings surprise scoring
  screeners/sentiment_scorer.py     # Phase 5 — NLTK VADER headline sentiment (local, no LLM call)
  screeners/watchlist.py            # Phase 5 — combines both + ATR stop/target into the CLI's advisory-only watchlist
  screeners/earnings_calendar.py    # manual-research extension — upcoming earnings dates + EPS estimates (yfinance)
  screeners/news_events.py          # manual-research extension — deterministic keyword tagging of headlines
  screeners/research_briefing.py    # manual-research extension — combines all of the above for CLI option [5] and Claude's own use, see below
nz_tax_fx/            # Phase 3 — FX conversion, FIF calculator (FDR/CV), tax reports
strategies/                   # Phase 6 — hand-designed classic reference strategies
  mean_reversion/strategy.py  #   classic_rsi_reversion() -> StrategySpec
  momentum/strategy.py        #   classic_macd_momentum() -> StrategySpec
  breakout/strategy.py        #   classic_channel_breakout() -> StrategySpec (channel-high + volume)
  pairs_trading/strategy.py   #   PairsSpec + hedge ratio/spread/z-score/cointegration math (two tickers — a
                               #   different shape from StrategySpec; see "Pairs trading" section below)
  library.py                  #   seed_classic_strategies() registers all of the above as registry candidates
backtester/
  data_loader.py       # Phase 4 — yfinance OHLCV, cached to data/historical/
  signals.py           # Phase 4/6 — pure-pandas entry/exit boolean signals from a StrategySpec
  engine.py            # Phase 4 — backtrader Cerebro execution simulation over those signals
  nz_adjustments.py    # Phase 4 — bridges an equity curve through nz_tax_fx/ for net-of-cost metrics
  pairs_engine.py       # Phase 6 — direct spread P&L simulation for PairsSpec (not backtrader — see below)
execution_ibkr/
  ibkr_connector.py    # Phase 7 — ib_insync bracket orders; needs TWS/Gateway, unverified beyond mocks
  market_hours.py      # Phase 7 — US session (America/New_York) <-> NZT, DST-aware, fully real/tested
execution_alpaca/
  alpaca_connector.py       # Phase 7 — alpaca-py bracket orders (paper); no live credentials configured yet
  paper_trading_engine.py   # Phase 7 — one incubation polling cycle: signal -> size -> circuit breakers -> order/shadow
  pairs_paper_trading_engine.py # Phase 7 — pairs-trading counterpart; shadow-only, no two-leg broker execution yet
risk_management/
  position_sizing.py   # Phase 7 — ATR/Kelly sizing, hard-capped by max_position_size_pct
  stop_target.py        # Phase 7 — stop-loss/target-profit + trailing-stop ratchet
  circuit_breakers.py   # Phase 7 — hardcoded, non-negotiable: stop-loss required, position cap, daily-loss halt
cli/                  # Interactive terminal menu entrypoint (python -m cli.main)
dashboard/generator.py # visual HTML status dashboard (registry pipeline breakdown, Sharpe
                        # comparison, equity curves) — local file, CLI option [6], see below
scripts/run_incubation_cycle.py # non-interactive form of CLI option [4] — run by a real
                        # Windows Scheduled Task daily, see "Execution & incubation engine"
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

**Not tax advice — decision-support only.** `nz_tax_fx/` produces estimates for backtesting
and validation purposes (net-of-tax return figures, the FIF threshold check). It is not a
filing-ready tax calculation: real NZ FIF rules have edge cases this module simplifies
(e.g. quick-sale adjustments, attributing interest exclusions). The user must verify actual
filings with a qualified tax professional or the IRD — same "AI/tooling assists, human
verifies" principle as trading signals (see Human-in-the-loop execution below).

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

**Known Phase 4 backtest engine limitations** (honest, not silently papered over):
- **Fixed**: `compute_profit_factor()` used to return Python's `float("inf")` for a
  strategy with wins and zero losses. `strategy_registry.json` is read by the dashboard's
  JS `JSON.parse()`, and JSON has no Infinity token — Python's `json` module silently wrote
  the non-standard `Infinity` literal, which breaks in any strict JSON consumer. It now
  returns `UNCAPPED_PROFIT_FACTOR` (999.0) instead — a documented cap, not a silent
  truncation; the pass/fail threshold comparison is unaffected either way.
- `backtester/signals.py` rejects `BOLLINGER_BANDS` conditions outright
  (`UnsupportedIndicatorError`) rather than guessing which band edge a single threshold
  means — a strategy using it is rejected at the backtest stage, not mis-evaluated.
- No stop-loss or position sizing is modeled in the Phase 4 backtest (that's
  `risk_management/`, Phase 7) — a full position is bought/sold on signal only. This means
  `validated` status reflects the raw strategy edge, not the edge with real risk controls
  active; `incubating` (which runs with real risk controls) is what actually proves the
  combination is trustworthy — consistent with the Strategy Lifecycle below.
- **Fixed**: `runner.py` used to backtest every single-ticker candidate against one
  hardcoded ticker (SPY) regardless of the strategy. It now validates each candidate
  against every ticker in `config.yaml`'s `strategy_validation.universe`, and promotes
  using whichever ticker gave the best passing result — that ticker is stored on the
  record (`record["ticker"]`) and is what `execution_alpaca/paper_trading_engine.py`
  actually trades during incubation. `StrategySpec` itself still carries no ticker of its
  own — a strategy is a rule, not a rule-plus-instrument — so a candidate that's rejected
  on every universe ticker is genuinely rejected, not just untested against the right one.

## Pairs trading (a genuinely different shape)

Pairs trading cannot be expressed as a `StrategySpec` — it needs two tickers and a spread
relationship, not indicator conditions on one price series. It gets its own parallel stack
instead of being forced through the single-ticker path:

- `strategies/pairs_trading/strategy.py` — `PairsSpec` (ticker_a, ticker_b, lookback
  period, entry/exit z-score) plus the math: OLS hedge ratio, spread, rolling z-score, and
  an Engle-Granger cointegration test (`statsmodels`).
- **Cointegration is the pairs-trading equivalent of `overfit_guard.py`.** Two tickers that
  merely moved together during a backtest window, without a real statistical relationship,
  is curve-fitting wearing a disguise — exactly the overfitting failure mode the Guardrails
  warn about. `quant_engine/validation/pairs_validator.py` rejects a pair outright
  (`config.yaml` `pairs_trading.cointegration_significance`) before it ever reaches the
  Sharpe/MaxDD/ProfitFactor thresholds. Known limitation: there's no walk-forward check for
  pairs yet beyond the cointegration test itself.
- `backtester/pairs_engine.py` simulates spread P&L directly (long/short the spread as the
  z-score crosses entry/exit thresholds) rather than reusing `engine.py`'s backtrader
  Cerebro model, which is built around one instrument. This is a documented simplification:
  Phase 7's execution engine will place the two real broker legs; this backtest only needs
  to prove the spread relationship is tradeable.
- Registry records carry a `"kind"` field ("single" vs "pairs") set by each spec's own
  `to_dict()` so `runner.py`/`pairs_runner.py` each only pick up their own shape — a pairs
  record has no `entry_conditions`/`archetype` to reconstruct a `StrategySpec` from, and
  vice versa.
- `strategies/library.py` seeds the classic reference strategies (one hand-designed
  implementation per archetype, including pairs pulled from `config.yaml`
  `watchlists.pairs_trading`) into the registry as `candidate`s — idempotent via each
  spec's internal `source_url` acting as its dedup key. This runs automatically whenever
  the discovery pipeline runs (`cli/main.py` option `[1]`), so a fresh registry always has
  something real to backtest even before any online discovery happens.

## Execution & incubation engine (Phase 7)

- `execution_ibkr/market_hours.py` and `risk_management/{position_sizing,stop_target,
  circuit_breakers}.py` are fully real and fully tested — no external dependency, no
  credentials needed. `circuit_breakers.py` is the one place `execution_ibkr/` and
  `execution_alpaca/` must call through before placing any order (`check_order()`): it
  enforces the hardcoded position-size ceiling, the mandatory stop-loss, and (via a
  supplied `DailyLossTracker`) the daily-loss halt — see "Hardcoded risk circuit breakers"
  above. Neither connector will construct or send a naked order; `stop_loss`/`take_profit`
  are required arguments on both `submit_bracket_order()` functions, not optional ones.
- `execution_alpaca/alpaca_connector.py` (alpaca-py) is real, working code, unit-tested
  against a mocked `TradingClient` — but **this repo has no `ALPACA_API_KEY` configured**,
  so it has never been exercised against Alpaca's actual paper endpoint. Whoever adds real
  credentials should treat the first live run as the actual verification, not this code
  review.
- `execution_ibkr/ibkr_connector.py` (ib_insync) needs TWS or IB Gateway **running locally**
  with API access enabled — this cannot be exercised in a sandboxed environment or CI
  runner at all, credentials or not. `build_bracket_order()` (pure order construction) is
  unit-tested with no connection; `submit_bracket_order()` is unit-tested only against a
  mocked `ib` object. Real verification requires a human running TWS/Gateway locally.
- `quant_engine/validation/incubation.py` is the forward-test **decision logic**:
  `evaluate_incubation()` checks for Sharpe/MaxDD decay on every call (a strategy blowing
  through its tolerance is rejected immediately, not after waiting out the full window),
  and only recommends promotion once both `incubation.min_days` and `incubation.min_trades`
  are satisfied with no decay. `strategy_research/registry.py` owns the actual
  `validated -> incubating -> proven/rejected` transitions (`start_incubation()`,
  `promote_to_proven()`).
- `execution_alpaca/paper_trading_engine.py`'s `run_incubation_cycle()` is **one polling
  cycle**: for each `incubating` single-ticker strategy, it generates today's signal with
  the same `backtester/signals.py` logic used in backtesting, and opens/holds/closes a
  position with real stateful tracking persisted directly on the registry record
  (`incubation_position`, `incubation_realized_pnl`) — mark-to-market each cycle, booking a
  trade on exit/stop/target. If `ALPACA_API_KEY` is configured it places a real paper
  bracket order; otherwise it runs in **shadow mode** (tracks the position and its P&L
  without calling any broker), so the whole pipeline is exercisable without live
  credentials. **This is not a continuously-running process** — something has to invoke it
  on a recurring schedule for incubation to actually progress over its 60+ day window (a
  single Claude Code session cannot itself run a multi-week background loop).
- **Fixed**: `scripts/run_incubation_cycle.py` is the non-interactive entrypoint (the same
  steps as `cli/main.py` option `[4]`, plus regenerating the dashboard afterward), and a
  real Windows Scheduled Task (`NZQuantTrader-IncubationCycle`, daily at 11:00 local time,
  `-StartWhenAvailable` so a missed run catches up on next login) invokes
  `python -m scripts.run_incubation_cycle` from the repo root. Set up with the user's
  explicit permission (persistent system config) and live-verified by manually triggering
  it via `Start-ScheduledTask` and confirming the log/dashboard actually updated — not just
  assumed to work. Logs to `data/logs/incubation_cycle.log` (gitignored). To
  inspect/modify/remove: `Get-ScheduledTask -TaskName NZQuantTrader-IncubationCycle` /
  `Unregister-ScheduledTask -TaskName NZQuantTrader-IncubationCycle` in PowerShell, or via
  the Task Scheduler GUI (`taskschd.msc`).
- `paper_trading_engine.py` trades each record's own `record["ticker"]` (set by `runner.py`
  during validation), fetching price data once per unique ticker needed per cycle, not once
  per record — no longer the single-shared-ticker limitation this section used to describe.
- **Fixed**: pairs-trading incubation is now wired via
  `execution_alpaca/pairs_paper_trading_engine.py`'s `run_pairs_incubation_cycle()` —
  mirrors `paper_trading_engine.py` exactly (same state-tracking-on-the-record design,
  same `evaluate_incubation()`/registry transitions downstream), swapping single-ticker
  signal generation for the hedge-ratio/spread/z-score math from
  `strategies/pairs_trading/strategy.py`. It stays **shadow-only**, though: a pairs
  position needs two linked broker legs (long ticker_a, short ticker_b, sized by the hedge
  ratio), and `alpaca_connector.py`'s `submit_bracket_order()` only places one instrument
  per call — real two-leg execution is still future work, not hidden here. Both cycles run
  from `cli/main.py` option `[4]`.
- Known limitation, carried forward honestly rather than hidden: long-only (`StrategySpec`
  doesn't model a short side yet).

## Visual status dashboard

`dashboard/generator.py`'s `generate_dashboard()` (CLI option `[6]`) reads
`data/strategy_registry.json` and writes a self-contained local HTML file
(`reports/dashboard.html`, gitignored — it's a regenerable report, not source) showing:
pipeline status breakdown (candidate/validated/incubating/proven/rejected as a bar chart),
a Sharpe-ratio comparison across every backtested strategy (colored pass/fail against the
required threshold, with a reference line), incubation equity curves for anything with
enough history, and a full sortable-by-eye table of every strategy with its metrics and
last outcome. Regenerate anytime — it always reflects current registry state.

This is a plain local file opened directly in a browser, not a claude.ai Artifact, so none
of the Artifact tool's CSP restrictions apply — but colors are drawn from the same
validated reference palette the `dataviz` skill uses for Artifacts (light/dark via
`prefers-color-scheme`), for consistency and accessibility. Charts are hand-rendered inline
SVG computed at generation time — no JS charting library, so the file works fully offline.
Live-verified by actually opening the generated file in a real browser (via a local
`python -m http.server`, since the browser-automation extension can't load `file://` URLs
directly) — dark mode, all four charts, and the table all render correctly.

**Every user-supplied or registry-derived string (strategy name, rejection reason, ticker)
is HTML-escaped before being embedded** — registry reason strings routinely contain literal
`<=`/`>=` (e.g. `"Sharpe 0.05 <= required 1.5"`), which would silently break the page's
markup if injected raw. Any future change to this module must keep every such field passed
through `html.escape()`.

## Strategy lifecycle — bin the losers, keep the winners

**A backtest pass is necessary but never sufficient.** The user has been explicit about
this: a strategy that looks amazing backtested can still fail live — via overfitting, a
regime shift, or costs/slippage/latency the backtest didn't capture — and the whole point
of this framework is for the user to actually be profitable, not to produce good-looking
backtest reports. Every strategy must go through the full lifecycle below; no stage may be
skipped or shortcut to get a strategy into live/paper trading faster.

Registry status values (`strategy_research/registry.py`), in order:

1. **`candidate`** — produced by the discovery pipeline (Phase 2), not yet backtested.
2. **`validated`** — passed backtest + thresholds (`backtester/`, `quant_engine/validation/`,
   Phase 4) net of NZ tax/FX. **Strategies that fail here are rejected outright** — never
   fixed by relaxing thresholds or retrying until something passes; that's p-hacking. Log the
   failed spec and its metrics and move on.
3. **`incubating`** — a `validated` strategy is *not* promoted straight to real paper
   trading. It first runs as a **forward test**: real-time paper-traded (or shadow-tracked)
   execution on live/streaming data it has never seen, for **at least 1–3 months** (config
   `incubation.min_days`, floor of 30, prefer 60–90 — this is a widely-cited minimum for
   surfacing execution bugs, slippage, and timing errors that a backtest can't show) AND a
   minimum trade count, whichever is stricter — before it is trusted with anything
   (including paper capital sizing decisions). This is the guard against backtest-vs-live
   divergence. Also requires a **live-vs-backtest divergence check** — incubation
   Sharpe/drawdown/profit factor must not decay beyond a configured tolerance relative to
   the backtest numbers that got it here. A strategy that decays during incubation is
   demoted straight to `rejected`, logged with the divergence that killed it — this is a
   filter, not a warm-up formality.
4. **`proven`** — cleared incubation. Only `proven` strategies are eligible to actually
   receive the CLI's paper-trading capital allocation and dynamic risk sizing
   (`risk_management/`). Re-validate `proven` strategies periodically against fresh
   walk-forward data; decay demotes them back out (to `incubating` or `rejected` depending
   on severity) rather than leaving a stale strategy trusted indefinitely.
5. **`rejected`** — terminal for this candidate's current form. Keep the record (spec +
   metrics + the reason/stage it failed at) rather than discarding it, so a dead-end idea
   isn't silently re-tried later. A rejected strategy can still be revisited manually if the
   user has a specific reason to (e.g. a parameter tweak), but the pipeline itself must not
   auto-retry a rejected spec.
6. **Live capital** is a separate, explicit decision gated by the Phase 9 live-readiness
   review below — `proven` in paper trading is not itself authorization to go live.

Maintain a clear, queryable record of every strategy's current stage and full history
(`data/strategy_registry.json` — tracked in git, since it's project state, not a runtime
cache) so nothing is silently generated and forgotten, and nothing skips a gate.

## Hardcoded risk circuit breakers (non-negotiable, never AI-adjusted)

`risk_management/` must enforce these as plain deterministic code — constants read from
`config.yaml`, never inferred, tuned, or overridden by an LLM at runtime:

- **Max position size**: a hard ceiling on the % of total portfolio equity any single trade
  may risk (`risk_management.max_position_size_pct`), enforced *regardless* of what the
  ATR/Kelly sizing math outputs — Kelly/ATR can only size *within* this ceiling, never above it.
- **Mandatory stop-loss on every trade**: no order may open without a stop-loss attached in
  the same instruction — never a "monitor and decide later" approach.
- **Max daily loss circuit breaker**: if realized+unrealized portfolio loss on a given day
  exceeds `risk_management.max_daily_loss_pct`, the execution engine halts all new entries
  and (config-dependent) flattens open positions for the day — automatically, not on request.
- These limits apply identically in paper and live trading — paper trading is exactly where
  you want to discover a circuit breaker is mis-tuned, not live.

## Human-in-the-loop execution

Not everything that clears validation/incubation should place orders unattended:

- **Pure rule-based technical strategies** (the `strategies/` library, backtested and
  incubated per the lifecycle above) may execute automatically once `proven`, but only
  **in paper trading**. This is what incubation is *for* — proving the automation itself is
  trustworthy before it ever touches capital that matters.
- **Any AI/sentiment-influenced signal** (`quant_engine/screeners/sentiment_scorer.py`, or
  anything an LLM scored/ranked) is advisory input to the fundamental screener only — it
  must never auto-trigger an order at any stage, paper or live. The screener's job ends at
  producing a ranked watchlist with an entry/stop/target; a human reviews and approves before
  it becomes a trade. This mirrors the tax module's own rule below: AI assists, a human verifies.
- **Live capital always starts human-confirmed**, independent of how long a strategy spent
  `proven` in paper trading. Clearing incubation is not authorization for unattended live
  execution — that's a separate, later decision the user makes explicitly (see Phase 9), and
  the default even after that decision is a confirm-to-execute mode, not full autonomy,
  unless the user explicitly chooses to relax it after building a live track record.

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
  **The user will still ask "what should I invest in" or "what should I look out for"
  directly, in conversation, for their own manual buy-in decisions — that request is fine;
  what must never happen is answering it from training-data knowledge or general market
  opinion.** When asked, run `quant_engine/screeners/research_briefing.py`'s
  `build_briefing()`/`scan_watchlist()` (or the CLI's option `[5]`) and present its real,
  freshly-fetched fundamentals/sentiment/upcoming-earnings/headline output — then let the
  user read the actual headlines and decide. Never paraphrase a headline as if you'd read
  more into it than the tool surfaced; never state a P/E, earnings date, or sentiment score
  without having just fetched it. The tool's output is the answer; your job is to run it and
  present it clearly, not to add an opinion on top of it.
- **Guard against lookahead / training-data leakage in backtests.** Because LLMs (and any
  data pulled from them) may have memorized historical prices/news, a strategy can look
  "unbeatable" purely because the model already "knew" what happened. Backtests must use
  strictly time-sliced historical data from a real market-data API (never from LLM
  knowledge or recall), with walk-forward / out-of-sample splits, and must never let a
  strategy's rules or parameters be tuned using information from outside its training
  window. `quant_engine/validation/overfit_guard.py` is responsible for enforcing this.
- **A great backtest does not mean a strategy is ready.** Backtested outperformance
  regularly fails to survive contact with live markets — overfitting, regime change, and
  execution realities (slippage, latency, partial fills) a backtest can't fully model. No
  strategy skips the `incubating` forward-test stage in the Strategy Lifecycle above on its
  way to real paper-trading capital, no matter how good its backtest numbers look.
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
2. **Strategy Discovery Engine** (done) — automated scrape→extract→distill pipeline, schema-validated `StrategySpec`, and the `strategy_registry.json` (`status="candidate"`) (`strategy_research/`).
3. **NZ Tax & FX Engine** (done) — FX converter, FIF/FDR/CV calculator, tax reports (`nz_tax_fx/`).
4. **Backtesting & Validation Engine** (done) — backtrader integration (via pure-pandas `signals.py` + `engine.py`), Sharpe/MaxDD/ProfitFactor metrics net of NZ tax/FX drag, walk-forward overfit guard; `runner.py` promotes registry entries `candidate` → `validated`/`rejected` (`backtester/`, `quant_engine/validation/`). Known limitation: `BOLLINGER_BANDS` conditions and stop-loss/position-sizing are not yet modeled — see "Known Phase 4 backtest engine limitations" above.
5. **Screener & Sentiment Engine** (done) — deterministic fundamental screener (P/E, PEG, D/E, revenue growth, earnings surprise via yfinance) + NLTK VADER headline sentiment (local, no LLM call); `watchlist.py` combines both into a ranked, ATR-based entry/stop/target watchlist — advisory-only per Human-in-the-loop below, wired to CLI option `[3]` (`quant_engine/screeners/`). Known limitation: VADER is a general-purpose lexicon, not finance-tuned — treat scores as directional, not precise.
6. **Strategy Library** (done) — hand-designed classic reference strategies for all four archetypes: `classic_rsi_reversion`, `classic_macd_momentum`, `classic_channel_breakout` (added a proper `CHANNEL_HIGH`/`CHANNEL_LOW` indicator + per-condition `period` override to the schema for this), and pairs trading's own `PairsSpec`/cointegration/spread stack (`strategies/`, `backtester/pairs_engine.py`, `quant_engine/validation/pairs_validator.py` + `pairs_runner.py` — see "Pairs trading" above). `library.py` seeds all of them into the registry automatically.
7. **Execution & Risk Engine** (done) — IBKR (`ib_insync`) and Alpaca (`alpaca-py`) bracket-order connectors (both refuse a naked order), NZT market-hours conversion, ATR/Kelly position sizing, stop/target + trailing-stop logic, and the hardcoded circuit breakers, all wired through `quant_engine/validation/incubation.py`'s forward-test decision logic and `execution_alpaca/paper_trading_engine.py`'s one-cycle-at-a-time paper execution loop (`execution_ibkr/`, `execution_alpaca/`, `risk_management/` — see "Execution & incubation engine" above for what's real vs. unverified-pending-credentials/TWS).
8. **CLI wiring & end-to-end paper trading** (done) — option `[4]` runs one incubation cycle for both single-ticker and pairs-trading candidates, each validated/traded on its own best-fit ticker from `strategy_validation.universe`; `scripts/run_incubation_cycle.py` is the non-interactive form, run daily by a real Windows Scheduled Task (`NZQuantTrader-IncubationCycle`) — see "Execution & incubation engine" above. Only `proven` strategies should get real paper-trading capital. Remaining work: real two-leg broker execution for pairs (currently shadow-only).
9. **Live-readiness review** — re-validate thresholds, tax handling, incubation track record, and risk controls before any live capital is considered.

Confirm with the user before starting each new phase — build and commit one phase at a time.
