import pytest
from fastapi.testclient import TestClient

TRAVERSALS = [
    "/%2e%2e/%2e%2e/pyproject.toml",
    "/..%2F..%2F..%2Fpyproject.toml",
    "/..%5C..%5Cpyproject.toml",
    "/assets/..%2F..%2Fdata%2Ftest.sqlite3",
    "/%2e%2e/data/test.sqlite3",
]


@pytest.mark.parametrize("path", TRAVERSALS)
def test_no_file_outside_dist(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert response.text == "<html>app shell</html>"


def test_spa_routes_and_static_files(client: TestClient) -> None:
    assert client.get("/cameras").text == "<html>app shell</html>"
    assert client.get("/favicon.svg").text == "<svg/>"
    assert client.get("/assets/app.js").status_code == 200


def test_unknown_api_path_is_404_not_app_shell(client: TestClient) -> None:
    assert client.get("/api/nothing").status_code in (401, 404)
    assert client.get("/api").status_code == 404


def test_security_headers(client: TestClient) -> None:
    response = client.get("/")
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" not in client.get("/docs").headers
