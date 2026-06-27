"""Paper trading frontend smoke test."""

from __future__ import annotations

import app as app_module


def test_paper_frontend_smoke_page_contains_m4_markers():
    app_module.app.config["TESTING"] = True

    response = app_module.app.test_client().get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    for marker in (
        "paperPanel",
        "paperRunBtn",
        "paperExportBtn",
        "paperScoreInput",
        "paperEquityChart",
        "仅为模拟交易与技术演示，不构成投资建议。",
        "/api/paper/account",
        "/api/paper/positions",
        "/api/paper/orders?limit=100",
        "/api/paper/equity",
        "/api/paper/run",
        "/api/paper/report.xlsx",
    ):
        assert marker in html
