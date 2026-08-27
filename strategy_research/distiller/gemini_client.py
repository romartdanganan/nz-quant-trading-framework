"""Gemini API fallback distiller — used only when rule_extractor.py has low confidence,
or the input is a large raw corpus (long PDF, huge forum thread) where a big context
window is actually needed. Rate/quota-capped (research_pipeline.max_gemini_calls_per_run
in config.yaml); must degrade gracefully (log + skip) on 429/quota errors rather than
crash the pipeline run. Requires GEMINI_API_KEY (free tier) in .env.

Phase 2 (Automated Strategy Discovery Pipeline). Not yet implemented.
"""
