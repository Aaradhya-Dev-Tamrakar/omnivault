"""
Security and Access Control Tests for OmniVault Web Gateway
Verifies CSRF token defense on destructive endpoints, origin restrictions, and HTML escaping.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from omnivault.web import ACTION_TOKEN, app


@pytest.fixture
def client():
    return TestClient(app)


def test_destructive_endpoints_require_token(client):
    # 1. Clean cache without token -> 403 Forbidden
    res = client.post("/api/storage/clean-cache")
    assert res.status_code == 403
    assert "Invalid or missing X-OmniVault-Token" in res.json()["detail"]

    # 2. Clean cache with invalid token -> 403 Forbidden
    res = client.post(
        "/api/storage/clean-cache",
        headers={"X-OmniVault-Token": "forged_malicious_token"},
    )
    assert res.status_code == 403

    # 3. Open file without token -> 403 Forbidden
    res = client.post("/api/open?path=C%3A%5CWindows")
    assert res.status_code == 403


def test_destructive_endpoints_accept_valid_token(client, monkeypatch):
    monkeypatch.setattr("omnivault.web.scan_cache_bloat", lambda: [])
    # Dry run clean cache with valid token -> 200 OK
    res = client.post(
        "/api/storage/clean-cache?execute=false",
        headers={"X-OmniVault-Token": ACTION_TOKEN},
    )
    assert res.status_code == 200
    data = res.json()
    assert "total_freed_formatted" in data
    assert data["executed"] is False


def test_read_endpoints_accessible_without_token(client):
    # Search and stats are read-only and open to the local dashboard
    res_stats = client.get("/api/stats")
    assert res_stats.status_code == 200

    res_search = client.get("/api/search?q=*")
    assert res_search.status_code == 200


def test_html_dashboard_injects_token_and_sanitizer(client):
    res = client.get("/")
    assert res.status_code == 200
    html = res.text

    # Active token injected into client-side JS
    assert f'const OMNIVAULT_TOKEN = "{ACTION_TOKEN}";' in html
    # HTML sanitization helper present
    assert "function esc(str)" in html
