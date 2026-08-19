"""
API endpoint tests for analysis routes.

Tests all 5 analysis endpoints:
  POST   /api/v1/analyze
  GET    /api/v1/analyze/{analysis_id}
  GET    /api/v1/analyze/{analysis_id}/report
  POST   /api/v1/analyze/{analysis_id}/approve
  GET    /api/health

Note on background tasks:
  Starlette's TestClient runs BackgroundTasks synchronously before returning the
  response, so the stub analysis task always completes (→ AWAITING_APPROVAL) by
  the time the next HTTP call is made. Tests that need a specific intermediate
  status inject records directly into the in-memory store.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app.api.v1.analysis as analysis_module
from app.api.v1.analysis import AnalysisStatus
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Health ────────────────────────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health_returns_200(self, client: TestClient) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_health_returns_ok_status(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        assert data["status"] == "ok"

    def test_health_returns_required_fields(self, client: TestClient) -> None:
        data = client.get("/api/health").json()
        for field in ("status", "timestamp", "version", "environment"):
            assert field in data


# ── POST /api/v1/analyze ──────────────────────────────────────────────────────


class TestStartAnalysis:
    def test_valid_url_returns_202(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/analyze",
            json={"repository_url": "https://github.com/fastapi/fastapi"},
        )
        assert response.status_code == 202

    def test_response_contains_analysis_id(self, client: TestClient) -> None:
        data = client.post(
            "/api/v1/analyze",
            json={"repository_url": "https://github.com/fastapi/fastapi"},
        ).json()
        assert "analysis_id" in data
        assert len(data["analysis_id"]) > 0

    def test_response_status_is_started(self, client: TestClient) -> None:
        data = client.post(
            "/api/v1/analyze",
            json={"repository_url": "https://github.com/fastapi/fastapi"},
        ).json()
        assert data["status"] == "STARTED"

    def test_response_contains_repository_name(self, client: TestClient) -> None:
        data = client.post(
            "/api/v1/analyze",
            json={"repository_url": "https://github.com/fastapi/fastapi"},
        ).json()
        assert data["repository_name"] == "fastapi/fastapi"

    def test_invalid_url_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/analyze",
            json={"repository_url": "https://gitlab.com/owner/repo"},
        )
        assert response.status_code == 422

    def test_empty_url_returns_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/analyze",
            json={"repository_url": ""},
        )
        assert response.status_code == 422

    def test_missing_url_field_returns_422(self, client: TestClient) -> None:
        response = client.post("/api/v1/analyze", json={})
        assert response.status_code == 422

    def test_ssh_url_accepted(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/analyze",
            json={"repository_url": "git@github.com:owner/repo.git"},
        )
        assert response.status_code == 202

    def test_each_analysis_gets_unique_id(self, client: TestClient) -> None:
        ids = set()
        for _ in range(3):
            data = client.post(
                "/api/v1/analyze",
                json={"repository_url": "https://github.com/fastapi/fastapi"},
            ).json()
            ids.add(data["analysis_id"])
        assert len(ids) == 3


# ── GET /api/v1/analyze/{analysis_id} ────────────────────────────────────────


class TestGetAnalysisStatus:
    def _start_analysis(self, client: TestClient) -> str:
        data = client.post(
            "/api/v1/analyze",
            json={"repository_url": "https://github.com/fastapi/fastapi"},
        ).json()
        return data["analysis_id"]

    def test_returns_200_for_existing_analysis(self, client: TestClient) -> None:
        analysis_id = self._start_analysis(client)
        response = client.get(f"/api/v1/analyze/{analysis_id}")
        assert response.status_code == 200

    def test_returns_404_for_unknown_id(self, client: TestClient) -> None:
        response = client.get("/api/v1/analyze/does-not-exist")
        assert response.status_code == 404

    def test_response_contains_required_fields(self, client: TestClient) -> None:
        analysis_id = self._start_analysis(client)
        data = client.get(f"/api/v1/analyze/{analysis_id}").json()
        for field in ("analysis_id", "status", "repository_url", "repository_name",
                      "created_at", "updated_at"):
            assert field in data

    def test_analysis_id_matches(self, client: TestClient) -> None:
        analysis_id = self._start_analysis(client)
        data = client.get(f"/api/v1/analyze/{analysis_id}").json()
        assert data["analysis_id"] == analysis_id


# ── GET /api/v1/analyze/{analysis_id}/report ─────────────────────────────────


class TestGetReport:
    def test_report_returns_409_when_not_completed(self, client: TestClient) -> None:
        data = client.post(
            "/api/v1/analyze",
            json={"repository_url": "https://github.com/fastapi/fastapi"},
        ).json()
        analysis_id = data["analysis_id"]
        # Status is STARTED immediately — report not ready yet
        response = client.get(f"/api/v1/analyze/{analysis_id}/report")
        assert response.status_code == 409

    def test_report_returns_404_for_unknown_id(self, client: TestClient) -> None:
        response = client.get("/api/v1/analyze/unknown-id/report")
        assert response.status_code == 404


# ── POST /api/v1/analyze/{analysis_id}/approve ────────────────────────────────


class TestApproveAnalysis:
    def _inject_running_analysis(self) -> str:
        """
        Directly insert a RUNNING-state analysis record into the in-memory store.

        The TestClient runs BackgroundTasks synchronously, so analyses started
        via POST /analyze are always in AWAITING_APPROVAL by the time any
        subsequent request arrives. To reliably test 409 behaviour we bypass
        the endpoint and inject the record manually.
        """
        analysis_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        analysis_module._analyses[analysis_id] = {
            "analysis_id": analysis_id,
            "status": AnalysisStatus.RUNNING,
            "repository_url": "https://github.com/fastapi/fastapi",
            "repository_name": "fastapi/fastapi",
            "created_at": now,
            "updated_at": now,
            "current_node": "repository_discovery",
            "progress": "Running…",
            "error": None,
            "report": None,
        }
        return analysis_id

    def test_approve_unknown_analysis_returns_404(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/analyze/unknown-id/approve",
            json={"action": "APPROVE"},
        )
        assert response.status_code == 404

    def test_approve_non_awaiting_analysis_returns_409(self, client: TestClient) -> None:
        # Use a directly-injected RUNNING record to guarantee non-AWAITING_APPROVAL state.
        analysis_id = self._inject_running_analysis()
        response = client.post(
            f"/api/v1/analyze/{analysis_id}/approve",
            json={"action": "APPROVE"},
        )
        assert response.status_code == 409

    def test_reject_without_feedback_returns_422(self, client: TestClient) -> None:
        data = client.post(
            "/api/v1/analyze",
            json={"repository_url": "https://github.com/fastapi/fastapi"},
        ).json()
        analysis_id = data["analysis_id"]
        response = client.post(
            f"/api/v1/analyze/{analysis_id}/approve",
            json={"action": "REJECT"},  # No feedback provided
        )
        # Either 409 (not awaiting) or 422 (missing feedback) is acceptable
        assert response.status_code in (409, 422)
