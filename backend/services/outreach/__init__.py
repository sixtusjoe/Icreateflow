"""Outreach — multi-account DM campaign pipeline.

    importer   CSV / pasted list → validated targets
    templates  {{variable}} rendering, validated before every send
    queue      Postgres-backed job queue (claim, retry, crash recovery)
    accounts   sending-account eligibility, leasing and health
    runner     the worker loop that ties them together
    browser/   the swappable automation layer (mock, Playwright)
    config     admin-tunable limits, read from site_config
    stats      campaign counter maintenance

Layering rule: `browser/` knows nothing about the database, and nothing
outside `browser/` imports Playwright.
"""
