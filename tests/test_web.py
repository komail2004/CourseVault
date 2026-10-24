"""Local web UI and session API tests without live Canvas credentials."""
from unittest.mock import patch
from fastapi.testclient import TestClient
from coursevault.web import app, SESSIONS


def test_homepage_renders():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Take your courses" in response.text
        assert "Connect to Canvas" in response.text


def test_unauthenticated_requests_rejected():
    with TestClient(app) as client:
        assert client.get("/api/courses").status_code == 401
        assert client.get("/api/export/fake").status_code == 401


def test_connect_requires_token():
    with TestClient(app) as client:
        response = client.post("/api/connect", json={
            "origin":"https://baumancollege.instructure.com","token":"short"
        })
        assert response.status_code == 422


def test_token_not_reflected_in_response():
    with patch("coursevault.web.Session.courses", return_value=[
        {"id":42,"name":"Intro to Nutrition","course_code":"NUT101"}
    ]):
        with TestClient(app) as client:
            response = client.post("/api/connect", json={
                "origin":"https://baumancollege.instructure.com",
                "token":"super-secret-test-token"
            })
            assert response.status_code == 200
            assert "super-secret-test-token" not in response.text
            assert response.json()["courses"][0]["id"] == 42
            assert client.get("/api/courses").status_code == 200
            assert client.post("/api/logout",json={}).status_code == 200
            assert client.get("/api/courses").status_code == 401


def test_cross_origin_rejected():
    with TestClient(app) as client:
        response = client.post("/api/connect",headers={
            "Origin":"https://attacker.example"
        },json={"origin":"https://baumancollege.instructure.com","token":"long-enough-test-token"})
        assert response.status_code == 403
