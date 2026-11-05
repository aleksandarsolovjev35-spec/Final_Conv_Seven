"""Тесты веб-разметки ROI (``roi_capture_web.py``)."""

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

import roi_capture as core
import roi_capture_web as web


@pytest.fixture()
def mapping():
    return {role: index for index, role in enumerate(core.ROLE_ORDER)}


@pytest.fixture()
def client(tmp_path, mapping):
    source = core.SyntheticCameraSource(mapping, seed=3)
    session = core.RoiSession(
        tmp_path, session_id="web", source_name=source.name,
        step_mode="sim", mapping=mapping,
    )
    controller = core.RoiSessionController(
        mapping=mapping,
        source=source,
        step_driver=core.SimStepDriver(duration=0.01),
        session=session,
    )
    service = web.RoiWebService(controller)
    return TestClient(web.create_app(service)), controller


def save_camera(client, index, points=None):
    points = points or [[100 + index * 10, 80], [600, 420]]
    return client.post("/api/save", json={
        "roi": {"mode": "rect", "points": points, "closed": True},
    })


class TestPage:
    def test_index_is_served_uncached(self, client):
        http, _controller = client
        response = http.get("/")
        assert response.status_code == 200
        assert "РАЗМЕТКА ЗОН ROI" in response.text
        assert response.headers["cache-control"] == web.NO_CACHE

    def test_static_assets_are_available(self, client):
        http, _controller = client
        assert http.get("/static/css/roi.css").status_code == 200
        assert http.get("/static/js/roi.js").status_code == 200

    def test_state_before_start(self, client):
        http, _controller = client
        state = http.get("/api/state").json()
        assert state["phase"] == core.Phase.READY
        assert state["round"] == 0
        assert len(state["cameras"]) == len(core.ROLE_ORDER)
        assert all(not camera["captured"] for camera in state["cameras"])
        assert state["frame_size"] == {"width": 1280, "height": 720}


class TestFrames:
    def test_frame_and_preview_are_jpeg(self, client):
        http, _controller = client
        http.post("/api/start")

        frame = http.get("/api/frame/0")
        preview = http.get("/api/preview/0")
        assert frame.status_code == 200
        assert frame.headers["content-type"] == "image/jpeg"
        assert frame.content[:2] == b"\xff\xd8"
        assert len(preview.content) < len(frame.content)

    def test_unknown_camera_index_is_404(self, client):
        http, _controller = client
        assert http.get("/api/frame/99").status_code == 404
        assert http.get("/api/preview/-1").status_code == 404

    def test_frame_without_capture_is_no_content(self, monkeypatch, client):
        http, controller = client

        def broken(role):
            raise RuntimeError(f"{role}: камера недоступна")

        monkeypatch.setattr(controller.source, "capture", broken)
        response = http.get("/api/frame/0")
        assert response.status_code == 204
        state = http.get("/api/state").json()
        assert state["cameras"][0]["error"]


class TestWorkflow:
    def test_start_opens_markup(self, client):
        http, _controller = client
        result = http.post("/api/start").json()
        assert result["ok"]
        assert result["state"]["phase"] == core.Phase.MARKUP
        assert result["state"]["round"] == 1
        assert result["state"]["cameras"][0]["captured"]

    def test_start_twice_is_rejected(self, client):
        http, _controller = client
        http.post("/api/start")
        second = http.post("/api/start")
        assert second.status_code == 409
        assert not second.json()["ok"]

    def test_seven_saves_close_the_round(self, client):
        http, _controller = client
        http.post("/api/start")
        for index in range(len(core.ROLE_ORDER)):
            response = save_camera(http, index)
            assert response.status_code == 200, response.text
        state = http.get("/api/state").json()
        assert state["phase"] == core.Phase.ROUND_DONE
        assert state["session"]["shots"] == len(core.ROLE_ORDER)
        assert all(camera["saved"] for camera in state["cameras"])

    def test_step_starts_fresh_round(self, client):
        http, _controller = client
        http.post("/api/start")
        for index in range(len(core.ROLE_ORDER)):
            save_camera(http, index)

        result = http.post("/api/step").json()
        assert result["ok"]
        state = result["state"]
        assert state["phase"] == core.Phase.MARKUP
        assert state["round"] == 2
        assert state["step"]["number"] == 1
        assert not any(camera["saved"] for camera in state["cameras"])

    def test_skip_starts_round_without_step(self, client):
        http, controller = client
        http.post("/api/start")
        for index in range(len(core.ROLE_ORDER)):
            save_camera(http, index)

        result = http.post("/api/skip").json()
        assert result["ok"]
        assert result["state"]["round"] == 2
        assert controller.session.steps_made == 0

    def test_skip_before_round_end_is_conflict(self, client):
        http, _controller = client
        http.post("/api/start")
        assert http.post("/api/skip").status_code == 409

    def test_save_without_points_is_rejected(self, client):
        http, _controller = client
        http.post("/api/start")
        response = http.post("/api/save", json={"roi": {"points": []}})
        assert response.status_code == 400
        assert not response.json()["ok"]

    def test_polygon_is_saved_with_mode(self, client):
        http, _controller = client
        http.post("/api/start")
        points = [[120, 100], [640, 130], [620, 430], [130, 400]]
        result = http.post("/api/save", json={
            "roi": {"mode": "poly", "points": points, "closed": True},
        }).json()
        assert result["ok"]
        state = result["state"]
        saved = next(camera for camera in state["cameras"] if camera["roi"])
        assert saved["roi"]["mode"] == "poly"
        assert len(saved["roi"]["points"]) == 4

    def test_finish_writes_manifest_and_blocks_actions(self, client):
        http, controller = client
        http.post("/api/start")
        save_camera(http, 0)
        result = http.post("/api/finish").json()
        assert result["ok"]
        assert result["state"]["phase"] == core.Phase.FINISHED

        manifest = json.loads(
            (controller.session.folder / "session.json").read_text("utf-8")
        )
        assert manifest["status"] == "CLOSED"
        assert http.post("/api/save", json={
            "roi": {"mode": "rect", "points": [[1, 1], [40, 40]]},
        }).status_code == 409

    def test_camera_selection_changes_cursor(self, client):
        http, _controller = client
        http.post("/api/start")
        result = http.post("/api/camera/3").json()
        assert result["ok"]
        assert result["state"]["cursor"] == 3
        assert result["state"]["cameras"][3]["captured"]

    def test_recapture_drops_zone_and_frame(self, client):
        http, controller = client
        http.post("/api/start")
        save_camera(http, 0)
        controller.select_camera(0)

        result = http.post("/api/capture").json()
        assert result["ok"]
        state = result["state"]
        assert state["cameras"][0]["roi"] is None


class TestStepFailure:
    def test_unconfirmed_step_reports_fault(self, client, monkeypatch):
        http, controller = client
        http.post("/api/start")
        for index in range(len(core.ROLE_ORDER)):
            save_camera(http, index)

        def failing(on_progress=None):
            controller.step_driver.fault = "шаг не подтверждён"
            return core.StepResult(False, None, "шаг не подтверждён")

        monkeypatch.setattr(controller.step_driver, "step", failing)
        response = http.post("/api/step")
        assert response.status_code == 502
        payload = response.json()
        assert not payload["ok"]
        assert payload["state"]["step"]["fault"]
        assert payload["state"]["phase"] == core.Phase.ROUND_DONE


class TestStateContract:
    def test_state_is_json_serialisable_and_complete(self, client):
        http, _controller = client
        http.post("/api/start")
        state = http.get("/api/state").json()
        for key in ("phase", "round", "cursor", "mode", "progress", "notice",
                    "frame_size", "session", "step", "source", "cameras",
                    "can_step"):
            assert key in state
        assert 0.0 <= state["progress"] <= 1.0
        for camera in state["cameras"]:
            for key in ("index", "role", "label", "camera_id", "saved",
                        "captured", "error", "token", "roi"):
                assert key in camera

    def test_progress_reflects_saved_cameras(self, client):
        http, _controller = client
        http.post("/api/start")
        save_camera(http, 0)
        state = http.get("/api/state").json()
        # после сохранения приложение само переходит к следующей камере,
        # поэтому в состоянии видна уже следующая (ещё не размеченная) камера
        assert state["progress"] == pytest.approx(1 / len(core.ROLE_ORDER), abs=1e-4)
        assert state["cameras"][0]["saved"]
        assert not state["cameras"][state["cursor"]]["saved"]


class TestFrameHelpers:
    def test_role_by_index(self):
        for index, role in enumerate(core.ROLE_ORDER):
            assert web._role_by_index(index) == role
        assert web._role_by_index(-1) is None
        assert web._role_by_index(len(core.ROLE_ORDER)) is None

    def test_build_state_survives_without_frames(self, tmp_path, mapping):
        source = core.SyntheticCameraSource(mapping, seed=1)
        session = core.RoiSession(tmp_path, session_id="empty",
                                  source_name=source.name, step_mode="none",
                                  mapping=mapping)
        controller = core.RoiSessionController(
            mapping=mapping, source=source, step_driver=core.NoStepDriver(),
            session=session,
        )
        state = web.build_state(controller)
        assert state["phase"] == core.Phase.READY
        assert all(camera["token"] == "0" for camera in state["cameras"])
        assert np.isfinite(state["progress"])
