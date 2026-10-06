# NZ Quant Trading & Research Framework

A modular Python framework for a New Zealand-based trader. It discovers trading
strategies, translates them into structured rules, backtests and validates them against
strict quantitative thresholds (Sharpe, max drawdown, profit factor, sample size), applies
NZ FIF tax and USD/NZD FX drag before any pass/fail decision, and forward-tests survivors
as paper trades via Interactive Brokers or Alpaca before they're ever trusted with capital.

## What it does

- **Strategy discovery (two independent paths).** One pipeline scrapes strategy write-ups
  from GitHub READMEs, Reddit, quant-blog RSS, and arXiv via official APIs (never raw HTML
  scraping), then extracts entry/exit rules against a controlled indicator vocabulary. A
  second, data-driven path mines real OHLCV history directly — bucketing indicator values
  into deciles and running significance tests against forward returns — to generate
  hypotheses that weren't copied from anyone.
- **Deterministic translation, not LLM judgment.** Every candidate, however it was found,
  is normalized into a schema-validated spec before it can reach a backtest. An LLM
  (Gemini) is used only as a fallback distiller for low-confidence or large free-text
  input — it never decides an entry/exit rule unsupervised, and never places a trade.
- **Backtest -> validate -> incubate -> prove.** A strategy must clear fixed thresholds
  (Sharpe > 1.5, max drawdown < 15%, profit factor > 1.3, minimum trade count) net of
  realistic FX fees, *then* run as an unfunded forward test on live data for 60+ days with
  a live-vs-backtest divergence check, before it is ever allocated paper capital. Nothing
  skips a gate to get to market faster.
- **NZ tax modeled honestly, not bolted on.** FIF/FDR/CV liability and USD/NZD conversion
  are computed as a real decision-support figure, kept separate from the risk ratios so
  that a once-a-year lump-sum tax calculation can't corrupt a volatility-based metric like
  Sharpe (see the project's internal notes for the exact bug this guards against).
- **Hardcoded, non-negotiable risk controls.** Position size caps, mandatory stop-loss, and
  a daily-loss circuit breaker are plain deterministic code, identical in paper and live
  trading — never tunable by a model at runtime.

## Where AI is used

- **Gemini API** — fallback distillation of free-text strategy write-ups into structured
  rules, used only when deterministic extraction has low confidence. Capped per run; skips
  rather than crashes on quota errors.
- **Claude Code** — used throughout development to write and maintain the pipeline,
  backtesting engine, tax/FX logic, and risk controls as plain, deterministic Python. The
  model's role stays fixed to *writing code*, never to making a trading decision at
  runtime — see the Guardrails in the project's internal docs.

## What I learned building it

Most strategies, including well-known textbook ones, don't survive honest validation —
the commit history is full of candidates rejected on real backtested numbers rather than
tuned until something passed. Three separate, compounding bugs in the tax/FX pipeline once
made every strategy converge on the same (wrong) Sharpe ratio regardless of how different
they actually were; tracking that down reinforced that a quant system has to be as
rigorous about *validating its own numbers* as it is about validating the strategies it
tests.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env          # then fill in broker/API keys
python -m cli.main
```

Run `pytest` to run the test suite.
