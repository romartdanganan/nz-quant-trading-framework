"""JSON-backed registry of every strategy candidate and its lifecycle status. See
CLAUDE.md "Strategy lifecycle" for the full state machine this enforces:

    candidate -> validated -> incubating -> proven
                    \\-> rejected <-/ (from any stage)

This module owns storage and the `candidate` stage only (Phase 2). Backtesting (Phase 4)
promotes candidate->validated/rejected; the incubation forward-test engine (Phase 7/8)
promotes validated->incubating->proven/rejected. Tracked in git (data/strategy_registry.json)
since it's project state, not a runtime cache.

Stores two shapes of record, disambiguated by a "kind" field each spec's own to_dict()
sets: "single" (strategy_research.strategy_spec.StrategySpec — one ticker, indicator
conditions) and "pairs" (strategies.pairs_trading.strategy.PairsSpec — two tickers, a
spread relationship). This module stays decoupled from both concrete types — it only
requires whatever is passed to add_candidate() to expose .to_dict().
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Protocol

DEFAULT_REGISTRY_PATH = Path("data/strategy_registry.json")

STATUSES = ("candidate", "validated", "incubating", "proven", "rejected")


class StrategyNotFound(KeyError):
    pass


class InvalidTransition(ValueError):
    """Raised when a status transition is attempted from a record not in the required
    starting status — e.g. starting incubation on something that was never "validated".
    """


class _SpecLike(Protocol):
    def to_dict(self) -> dict: ...


class StrategyRegistry:
    def __init__(self, path: Path | str = DEFAULT_REGISTRY_PATH):
        self.path = Path(path)
        self._records: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._records, f, indent=2)

    def add_candidate(self, spec: _SpecLike) -> dict:
        record = spec.to_dict()
        record["id"] = uuid.uuid4().hex
        record["status"] = "candidate"
        record["metrics"] = None
        record["history"] = [{"status": "candidate", "reason": "discovered by pipeline"}]
        self._records.append(record)
        return record

    def get(self, record_id: str) -> dict:
        for record in self._records:
            if record.get("id") == record_id:
                return record
        raise StrategyNotFound(record_id)

    def promote_to_validated(self, record_id: str, metrics: dict, reason: str) -> dict:
        record = self.get(record_id)
        record["status"] = "validated"
        record["metrics"] = metrics
        record["history"].append({"status": "validated", "reason": reason})
        return record

    def reject(self, record_id: str, reason: str) -> dict:
        record = self.get(record_id)
        record["status"] = "rejected"
        record["history"].append({"status": "rejected", "reason": reason})
        return record

    def start_incubation(self, record_id: str) -> dict:
        """validated -> incubating: begins the forward-test (CLAUDE.md Strategy
        Lifecycle). Captures the backtest metrics as baseline_metrics so
        quant_engine/validation/incubation.py can measure live-vs-backtest decay.
        """
        record = self.get(record_id)
        if record["status"] != "validated":
            raise InvalidTransition(
                f"cannot start incubation from status {record['status']!r} (must be 'validated')"
            )
        record["status"] = "incubating"
        record["incubation_start_date"] = date.today().isoformat()
        record["baseline_metrics"] = record["metrics"]
        record["incubation_log"] = []
        record["incubation_trades"] = []
        record["history"].append({"status": "incubating", "reason": "forward-test started"})
        return record

    def promote_to_proven(self, record_id: str, metrics: dict, reason: str) -> dict:
        record = self.get(record_id)
        record["status"] = "proven"
        record["metrics"] = metrics
        record["history"].append({"status": "proven", "reason": reason})
        return record

    def list(self, status: str | None = None) -> list[dict]:
        if status is None:
            return list(self._records)
        return [record for record in self._records if record.get("status") == status]

    def seen_source_urls(self) -> set[str]:
        return {record["source_url"] for record in self._records if "source_url" in record}
