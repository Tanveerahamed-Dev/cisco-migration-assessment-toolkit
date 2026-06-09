"""AssessHub backend — a served web platform on top of the Cisco Migration-Assessment engine.

This package is *additive*: it imports the existing `cisco_toolkit` engine and re-uses it
(snapshot contract, `html.compute_snapshot_delta`, `html.compute_campaign_trend`,
`html.write_html_explorer`) rather than re-implementing any analysis. The CLI engine stays
the single source of truth; this layer gives stored snapshots a live, multi-campaign web surface.
"""

__all__ = ["create_app"]


def create_app(*args, **kwargs):  # lazy import so `import backend` is cheap
    from .app import create_app as _create_app

    return _create_app(*args, **kwargs)
