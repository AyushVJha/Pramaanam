"""Anthropic SDK wrapper. (M5)

Model name from config, disk cache keyed by hash(model, prompt, params), token/cost
logging to logs/llm_usage.jsonl, retry with backoff.
"""
