"""Free, deterministic extraction: matches scraped strategy text against vocabulary.py
to produce a StrategySpec directly, with no LLM call. Primary extraction path — covers
the common case (known indicators/archetypes). Falls through to distiller/gemini_client.py
only on low confidence or bulk/large input.

Phase 2 (Automated Strategy Discovery Pipeline). Not yet implemented.
"""
