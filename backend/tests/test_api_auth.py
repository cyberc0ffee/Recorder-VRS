from pathlib import Path

import pytest
from conftest import ADMIN_PASSWORD, CSRF
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.auth_service import INITIAL_PASSWORD_FILE

PROTECTED = [
    ("GET", "/api/cameras"),
    ("GET", "/api/system"),
    ("GET", "/api/events"),
    ("GET", "/api/recordings"),
    ("GET", "/api/recordings/1/download"),
    ("POST", "/api/cleanup"),
    ("DELETE", "/api/cameras/1"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_api_requires_login(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, headers=CSRF)
    assert response.status_code == 401


def test_state_changes_require_csrf_header(admin: TestClient) -> None:
    response = admin.post("/api/cleanup", headers={"X-Requested-With": ""})
    assert response.status_code == 403
    assert admin.post("/api/cleanup").status_code == 200


def test_login_cookie_and_logout(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}, headers=CSRF
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/auth/me").json() == {"username": "admin", "role": "admin"}

    assert client.post("/api/auth/logout", headers=CSRF).status_code == 204
    assert client.get("/api/cameras").status_code == 401


def test_wrong_password_and_throttle(client: TestClient) -> None:
    for _ in range(5):
        response = client.post(
            "/api/auth/login", json={"username": "admin", "password": "nope"}, headers=CSRF
        )
        assert response.status_code == 401
    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}, headers=CSRF
    )
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_change_password_closes_sessions(admin: TestClient) -> None:
    short = admin.post(
        "/api/auth/password", json={"current_password": ADMIN_PASSWORD, "new_password": "short"}
    )
    assert short.status_code == 422
    wrong = admin.post(
        "/api/auth/password", json={"current_password": "bad", "new_password": "x" * 12}
    )
    assert wrong.status_code == 403
    ok = admin.post(
        "/api/auth/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "another-long-one"},
    )
    assert ok.status_code == 204
    assert admin.get("/api/cameras").status_code == 401
    login = admin.post(
        "/api/auth/login", json={"username": "admin", "password": "another-long-one"}
    )
    assert login.status_code == 200


def test_random_initial_password_written_to_file(
    settings: Settings, frontend_dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RTSP_RECORDER_ADMIN_PASSWORD", raising=False)
    with TestClient(create_app(settings, frontend_dist=frontend_dist)) as client:
        password_file = settings.database_path.parent / INITIAL_PASSWORD_FILE
        password = password_file.read_text(encoding="utf-8").split("password: ")[1].strip()
        response = client.post(
            "/api/auth/login", json={"username": "admin", "password": password}, headers=CSRF
        )
        assert response.status_code == 200


def test_camera_password_never_returned(admin: TestClient, settings: Settings) -> None:
    created = admin.post(
        "/api/cameras",
        json={"name": "Gate", "rtsp_url": "rtsp://admin:s3cret@10.0.0.9/live", "autostart": False},
    )
    assert created.status_code == 201
    camera = created.json()
    assert camera["rtsp_url"] == "rtsp://admin:***@10.0.0.9/live"
    assert "s3cret" not in admin.get("/api/cameras").text

    # sending the masked URL back (edit form) keeps the stored password
    updated = admin.put(f"/api/cameras/{camera['id']}", json={"rtsp_url": camera["rtsp_url"]})
    assert updated.status_code == 200
    stored = admin.app.state.camera_service.get_camera(camera["id"]).rtsp_url
    assert stored == "rtsp://admin:s3cret@10.0.0.9/live"


def test_similar_camera_names_rejected(admin: TestClient) -> None:
    body = {"rtsp_url": "rtsp://10.0.0.9/live", "autostart": False}
    assert admin.post("/api/cameras", json={"name": "Front Door", **body}).status_code == 201
    response = admin.post("/api/cameras", json={"name": "front_door", **body})
    assert response.status_code == 409


def test_health_is_public(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
