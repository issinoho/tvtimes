"""Source ingestion.

Parsers for the cloud source types (M3U, Xtream Codes, Stalker Portal),
adapted from the ``tvdinner`` CLI: the pure parsing/URL logic is kept close to
the original, the HTTP layer is async (httpx) and every outbound request for a
user-supplied URL goes through ``app.ingest.ssrf``.
"""
