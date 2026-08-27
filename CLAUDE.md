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
  validation/runner.py       # Phase 4 — drives validator.py over every registry "candidate"
  screeners/fundamental_screener.py # Phase 5 — deterministic P/E, PEG, D/E, revenue growth, earnings surprise scoring
  screeners/sentiment_scorer.py     # Phase 5 — NLTK VADER headline sentiment (local, no LLM call)
  screeners/watchlist.py            # Phase 5 — combines both + ATR stop/target into the CLI's advisory-only watchlist
nz_tax_fx/            # Phase 3 — FX conversion, FIF calculator (FDR/CV), tax reports
strategies/           # Phase 6 — mean_reversion, momentum, pairs_trading, breakout
backtester/
  data_loader.py       # Phase 4 — yfinance OHLCV, cached to data/historical/
  signals.py           # Phase 4 — pure-pandas entry/exit boolean signals from a StrategySpec
  engine.py            # Phase 4 — backtrader Cerebro execution simulation over those signals
  nz_adjustments.py    # Phase 4 — bridges an equity curve through nz_tax_fx/ for net-of-cost metrics
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
- `backtester/signals.py` rejects `BOLLINGER_BANDS` conditions outright
  (`UnsupportedIndicatorError`) rather than guessing which band edge a single threshold
  means — a strategy using it is rejected at the backtest stage, not mis-evaluated.
- No stop-loss or position sizing is modeled in the Phase 4 backtest (that's
  `risk_management/`, Phase 7) — a full position is bought/sold on signal only. This means
  `validated` status reflects the raw strategy edge, not the edge with real risk controls
  active; `incubating` (which runs with real risk controls) is what actually proves the
  combination is trustworthy — consistent with the Strategy Lifecycle below.

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
6. **Strategy Library** — implement mean reversion, momentum, pairs trading, breakout; only `validated` strategies get real implementations here (`strategies/`).
7. **Execution & Risk Engine** — IBKR/Alpaca connectors, market-hours scheduling, ATR/Kelly sizing, stop/target logic, and the **incubation forward-test engine** that runs `validated` strategies live-but-unfunded and promotes/demotes `incubating` → `proven`/`rejected` (`execution_ibkr/`, `execution_alpaca/`, `risk_management/`).
8. **CLI wiring & end-to-end paper trading** — connect all menu options in `cli/main.py` to the real modules; only `proven` strategies get real paper-trading capital.
9. **Live-readiness review** — re-validate thresholds, tax handling, incubation track record, and risk controls before any live capital is considered.

Confirm with the user before starting each new phase — build and commit one phase at a time.
