# NZ Quant Trading & Research Framework

A modular Python framework for a New Zealand-based trader: discovers strategies online,
backtests and validates them against strict quant thresholds, applies NZ FIF tax and
USD/NZD FX conversion, and executes paper trades via Interactive Brokers or Alpaca.

See [CLAUDE.md](./CLAUDE.md) for setup, architecture, and the phase roadmap.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env          # then fill in broker/API keys
python -m cli.main
```
