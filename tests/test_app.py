import sys
from pathlib import Path

from fasthtml.common import Client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app


def test_home_page_renders_route_browser():
    client = Client(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "Tenerife Cycling Routes" in response.text
    assert "/static/app.js" in response.text
    assert "map" in response.text
