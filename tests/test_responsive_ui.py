import pytest
from fastapi.testclient import TestClient
from fpl_bot.web.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_responsive_meta_viewport(client):
    """Verify that proper viewport meta tag is defined for multi-screen responsiveness."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'name="viewport"' in resp.text
    assert "width=device-width" in resp.text


def test_responsive_media_queries(client):
    """Verify presence of CSS media query breakpoints for Desktop, Tablet, and Mobile Phone."""
    resp = client.get("/")
    assert resp.status_code == 200
    text = resp.text

    # Tablet breakpoint (768px - 1024px)
    assert "@media screen and (min-width: 768px) and (max-width: 1024px)" in text or "768px" in text
    assert "max-width: 1024px" in text

    # Phone breakpoint (< 768px)
    assert "max-width: 767px" in text

    # Small Phone breakpoint (< 380px)
    assert "max-width: 380px" in text


def test_device_switcher_component(client):
    """Verify that the interactive device preview switcher is embedded with Desktop, Tablet, and Phone modes."""
    resp = client.get("/")
    assert resp.status_code == 200
    text = resp.text

    assert "device-switcher" in text
    assert "btn-device" in text
    assert "data-device=\"desktop\"" in text
    assert "data-device=\"tablet\"" in text
    assert "data-device=\"phone\"" in text
    assert "data-device=\"auto\"" in text
    assert "setDeviceMode" in text


def test_responsive_layout_containers(client):
    """Verify responsive wrappers for pitch, stats, tables, and sidebar columns."""
    resp = client.get("/")
    assert resp.status_code == 200
    text = resp.text

    # Table horizontal scroll container for mobile & tablet
    assert "table-responsive" in text

    # Pitch and player card classes
    assert "pitch-container" in text
    assert "lineup-row" in text
    assert "player-card" in text
    assert "bench-section" in text

    # Main layout columns
    assert "main-content-col" in text
    assert "sidebar-col" in text
