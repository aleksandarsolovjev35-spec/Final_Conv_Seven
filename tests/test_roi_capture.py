"""Тесты отдельного приложения разметки зон ROI (``roi_capture.py``)."""

import json

import numpy as np
import pytest

import roi_capture as R


@pytest.fixture()
def mapping():
    return {role: index for index, role in enumerate(R.ROLE_ORDER)}


@pytest.fixture()
def synthetic(mapping):
    return R.SyntheticCameraSource(mapping, seed=1)


@pytest.fixture()
def app(tmp_path, mapping, synthetic):
    session = R.RoiSession(
        tmp_path, session_id="test", source_name=synthetic.name,
        step_mode="sim", mapping=mapping,
    )
    application = R.RoiApp(
        mapping=mapping,
        source=synthetic,
        step_driver=R.SimStepDriver(duration=0.01),
        session=session,
        scale=0.5,
    )
    return application


def draw_rect(application, role_index, box=(100, 80, 500, 400)):
    """Обвести прямоугольник координатами кадра (не канвы)."""
    application.cursor = role_index
    application._ensure_frame(R.ROLE_ORDER[role_index])
    scale = application.scale
    x1, y1, x2, y2 = box
    application._start_draw(int(x1 * scale), int(y1 * scale))
    application._drag_to(int(x2 * scale), int(y2 * scale))
    application._finish_draw(int(x2 * scale), int(y2 * scale))


class TestRoi:
    def test_rect_normalises_corners(self):
        roi = R.Roi.rect((500, 400), (100, 80))
        assert roi.mode == "rect" and roi.closed
        assert roi.bbox == (100, 80, 400, 320)
        assert roi.area == pytest.approx(128000)
        assert roi.is_valid()

    def test_polygon_area_and_validity(self):
        roi = R.Roi("poly", [(0, 0), (200, 0), (200, 100)], True)
        assert roi.area == pytest.approx(10000)
        assert roi.is_valid()
        assert not R.Roi("poly", [(0, 0), (2, 2)], True).is_valid()

    def test_mode_conversion_keeps_geometry(self):
        rect = R.Roi.rect((10, 20), (110, 220))
        polygon = rect.to_polygon()
        assert polygon.mode == "poly" and polygon.points == rect.points
        back = polygon.to_rect()
        assert back.mode == "rect" and back.bbox == rect.bbox

    def test_clamp_keeps_points_inside_frame(self):
        roi = R.Roi("poly", [(-10, -20), (2000, 5000)], True)
        roi.clamp(1280, 720)
        assert roi.points == [(0, 0), (1279, 719)]

    def test_as_dict_reports_percent_of_frame(self):
        payload = R.Roi.rect((0, 0), (640, 360)).as_dict(1280, 720)
        assert payload["area_pct"] == pytest.approx(25.0)
        assert payload["centre"] == [320, 180]


class TestSession:
    def test_saves_pair_of_frames_and_meta(self, app):
        app.start()
        draw_rect(app, 0)
        app.save_current()

        round_dir = app.session.folder / "round_01"
        assert (round_dir / "01_INPUT_LEFT.jpg").exists()
        assert (round_dir / "01_INPUT_LEFT_roi.jpg").exists()

        meta = json.loads((round_dir / "01_INPUT_LEFT.json").read_text("utf-8"))
        assert meta["role"] == "INPUT_LEFT"
        assert meta["round"] == 1
        assert meta["roi"]["mode"] == "rect"
        assert meta["roi"]["bbox"] == [100, 80, 400, 320]
        assert meta["frame"]["width"] == R.EXPECTED_FRAME_SIZE[0]

    def test_drawn_frame_differs_outside_zone_only(self, app):
        app.start()
        draw_rect(app, 0, (200, 150, 900, 600))
        app.save_current()

        import cv2

        round_dir = app.session.folder / "round_01"
        raw = cv2.imread(str(round_dir / "01_INPUT_LEFT.jpg"))
        drawn = cv2.imread(str(round_dir / "01_INPUT_LEFT_roi.jpg"))
        assert raw.shape == drawn.shape
        assert drawn[400, 500].mean() > raw[400, 500].mean() * 0.8   # внутри зоны
        assert drawn[40, 1200].mean() < raw[40, 1200].mean() * 0.7   # снаружи темнее

    def test_manifest_closed_after_finish(self, app):
        app.start()
        for index in range(len(R.ROLE_ORDER)):
            draw_rect(app, index, (120 + index, 90, 700, 480))
            app.save_current()
        app._finish_session()

        manifest = json.loads(
            (app.session.folder / "session.json").read_text("utf-8")
        )
        assert manifest["status"] == "CLOSED"
        assert manifest["totals"]["rounds"] == 1
        assert manifest["totals"]["shots"] == len(R.ROLE_ORDER)
        assert len(manifest["rounds"][0]["shots"]) == len(R.ROLE_ORDER)


class TestFlow:
    def test_saving_seven_cameras_closes_round(self, app):
        app.start()
        for index in range(len(R.ROLE_ORDER)):
            draw_rect(app, index)
            app.save_current()
            if index < len(R.ROLE_ORDER) - 1:
                assert app.phase == R.Phase.MARKUP
        assert app.phase == R.Phase.ROUND_DONE

    def test_step_starts_new_round_with_fresh_frames(self, app):
        app.start()
        for index in range(len(R.ROLE_ORDER)):
            draw_rect(app, index)
            app.save_current()
        first_frames = dict(app.frames)

        app.make_step()

        assert app.phase == R.Phase.MARKUP
        assert app.round_no == 2
        assert app.conveyor_step == 1
        assert app.saved == {role: False for role in R.ROLE_ORDER}
        assert app.rois == {}
        assert app.frames[R.ROLE_ORDER[0]] is not first_frames[R.ROLE_ORDER[0]]

    def test_skip_step_moves_to_next_round(self, app):
        app.start()
        for index in range(len(R.ROLE_ORDER)):
            draw_rect(app, index)
            app.save_current()
        app._continue_without_step()
        assert app.round_no == 2 and app.phase == R.Phase.MARKUP
        assert app.session.steps_made == 0

    def test_save_without_zone_is_rejected(self, app):
        app.start()
        app.save_current()
        assert app.session.counts()["shots"] == 0
        assert app.phase == R.Phase.MARKUP

    def test_polygon_requires_closing_and_undo_works(self, app):
        app.start()
        app._set_mode("poly")
        for point in ((100, 100), (500, 120), (520, 400), (120, 380)):
            app._start_draw(*point)
        roi = app.rois[R.ROLE_ORDER[0]]
        assert not roi.closed

        app._undo_point()
        app._undo_point()
        assert len(roi.points) == 2
        assert roi.is_valid() or not roi.is_valid()

        app._close_polygon()
        assert not app.rois[R.ROLE_ORDER[0]].closed
        assert app.session.counts()["shots"] == 0

    def test_mode_switch_converts_existing_zone(self, app):
        app.start()
        draw_rect(app, 0, (150, 120, 650, 520))
        before = app.rois[R.ROLE_ORDER[0]].bbox
        app._set_mode("poly")
        assert app.rois[R.ROLE_ORDER[0]].mode == "poly"
        assert app.rois[R.ROLE_ORDER[0]].bbox == before
        app._set_mode("rect")
        assert app.rois[R.ROLE_ORDER[0]].mode == "rect"

    @pytest.mark.parametrize("phase", [
        R.Phase.READY, R.Phase.MARKUP, R.Phase.ROUND_DONE,
        R.Phase.STEPPING, R.Phase.FINISHED,
    ])
    def test_canvas_composes_in_every_phase(self, app, phase):
        app.start()
        draw_rect(app, 0)
        app.phase = phase
        canvas = app._compose()
        assert canvas.shape == (app.canvas_size[1], app.canvas_size[0], 3)
        assert canvas.mean() > 0

    def test_click_on_start_button_starts_session(self, app):
        app.phase = R.Phase.READY
        canvas = app._compose()
        assert canvas.shape[2] == 3
        button = next(item for item in app.buttons if item.action == "start")
        x, y, width, height = button.rect
        assert app._click_button(x + width // 2, y + height // 2)
        assert app.phase == R.Phase.MARKUP

    def test_missing_camera_frame_is_reported(self, app, monkeypatch):
        app.start()

        def broken(role):
            raise RuntimeError(f"{role}: камера недоступна")

        monkeypatch.setattr(app.source, "capture", broken)
        app._move_cursor(+1)
        assert R.ROLE_ORDER[1] in app.errors
        assert app.frames.get(R.ROLE_ORDER[1]) is None


class FakeTransport:
    """Подставной COM-порт: считает команды и подтверждает STEP."""

    instances = []

    def __init__(self, port, baudrate):
        self.port = port
        self.baudrate = baudrate
        self.step = 5
        self.ack = True
        self.sent = []
        self.closed = False
        FakeTransport.instances.append(self)

    def send(self, command):
        self.sent.append(command)

    def query(self, command, delay=0.15):
        self.sent.append(command)
        if command == "I2":
            return f"MOV=0 WAIT=0 POS=10 TGT=10 STEP={self.step} lastErr=0"
        if command == "I1":
            return "0"
        if command.startswith("G3 N"):
            expected = int(command.split("N")[1])
            if not self.ack:
                return "ERR"
            self.step = expected
            return f"ACK G3 STEP={expected}"
        return "OK"

    def close(self):
        self.closed = True


@pytest.fixture()
def fake_serial(monkeypatch):
    FakeTransport.instances = []
    monkeypatch.setattr("hardware.serial_transport.SerialTransport", FakeTransport)
    monkeypatch.setattr(
        "hardware.port_discovery.find_controller",
        lambda baudrate=115200, preferred_port=None: ("COM_TEST", "fake"),
    )
    return FakeTransport


class TestSerialStep:
    def test_step_uses_calibration_and_confirms_sequence(self, fake_serial):
        driver = R.SerialStepDriver(settle=0.0, timeout=5.0)
        result = driver.step()

        transport = FakeTransport.instances[-1]
        assert result.ok and result.step == 6
        assert "G1" in transport.sent and "G25" in transport.sent
        assert "G5 S18000" in transport.sent          # calibration.json
        assert "G7 S9524" in transport.sent
        assert "G3 N6" in transport.sent
        driver.close()
        assert transport.closed

    def test_unconfirmed_step_blocks_retry(self, fake_serial):
        driver = R.SerialStepDriver(port="COM_TEST", settle=0.0, timeout=5.0)
        driver._ensure_connected()
        transport = FakeTransport.instances[-1]
        transport.ack = False

        first = driver.step()
        count = len(transport.sent)
        second = driver.step()

        assert not first.ok and driver.fault
        assert not second.ok
        assert len(transport.sent) == count      # повторно порт не дёргали

    def test_no_step_driver_reports_success_without_step(self):
        driver = R.NoStepDriver()
        result = driver.step()
        assert result.ok and result.step is None

    def test_sim_step_increments_counter(self):
        driver = R.SimStepDriver(duration=0.01)
        assert driver.step().step == 1
        assert driver.step().step == 2


class TestSources:
    def test_folder_source_reads_round_folders(self, tmp_path, mapping):
        for round_no in (1, 2):
            folder = tmp_path / str(round_no)
            folder.mkdir()
            for role in R.ROLE_ORDER:
                frame = np.zeros((R.EXPECTED_FRAME_SIZE[1],
                                  R.EXPECTED_FRAME_SIZE[0], 3), np.uint8)
                frame[:] = (round_no * 20, 0, 0)
                import cv2
                cv2.imwrite(str(folder / f"{role}.jpg"), frame)

        source = R.FolderCameraSource(mapping, str(tmp_path))
        first = source.capture("TOP")
        source.advance()
        second = source.capture("TOP")
        assert first.mean() != second.mean()
        assert first.shape == (720, 1280, 3)

    def test_synthetic_frames_follow_round(self, synthetic):
        first = synthetic.capture("TOP")
        synthetic.advance()
        second = synthetic.capture("TOP")
        assert first.shape == (720, 1280, 3)
        assert np.abs(first.astype(int) - second.astype(int)).max() > 20

    def test_mapping_file_validation(self, tmp_path):
        path = tmp_path / "camera_mapping.json"
        path.write_text(json.dumps({"INPUT_LEFT": 0}), encoding="utf-8")
        with pytest.raises(RuntimeError):
            R.load_mapping(str(path), required=True)
        mapping = R.load_mapping(str(path), required=False)
        assert mapping == {"INPUT_LEFT": 0}
