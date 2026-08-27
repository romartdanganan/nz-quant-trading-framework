"""Orchestrates the end-to-end automated discovery pipeline: scrape -> rule_extractor
(primary) -> gemini_client (fallback) -> nl_to_rules (schema validation) -> strategy
registry ("candidate") -> backtester -> quant_engine/validation -> bin/keep. Single
entrypoint triggered on-demand from cli/main.py option [1].

Phase 2 (Automated Strategy Discovery Pipeline). Not yet implemented.
"""
