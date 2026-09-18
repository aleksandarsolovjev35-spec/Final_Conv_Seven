"""belt_editor/serve.py — автономный запускатель экрана сборки ленты.

Только stdlib. Раздаёт статику папки и обменивается конфигурацией:

* ``GET  /api/belt``  — вернуть сохранённый belt_path.json (404, если файла нет);
* ``POST /api/belt``  — валидация belt_model и сохранение в belt_path.json
  (422 со списком нарушений, если конфигурация не проходит).

Запуск из корня репозитория или из любой папки:

    python belt_editor/serve.py [--host 0.0.0.0] [--port 8020] [--open]

Проверка файла без сервера:

    python belt_editor/serve.py --validate belt_editor/belt_path.json
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import belt_model  # noqa: E402

BELT_FILE = HERE / "belt_path.json"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


class BeltEditorHandler(BaseHTTPRequestHandler):
    server_version = "BeltEditor/1.0"

    # ─── helpers ────────────────────────────────────────────────────

    def send_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ─── HTTP ───────────────────────────────────────────────────────

    def do_GET(self):  # noqa: N802 — контракт BaseHTTPRequestHandler
        route = unquote(self.path.split("?", 1)[0])
        if route == "/api/belt":
            if not BELT_FILE.exists():
                self.send_json(404, {"error": "belt_path.json не найден"})
                return
            try:
                self.send_json(200, json.loads(
                    BELT_FILE.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                self.send_json(500, {"error": f"не удалось прочитать: {exc}"})
            return
        self.serve_static(route)

    def do_POST(self):  # noqa: N802 — контракт BaseHTTPRequestHandler
        if unquote(self.path.split("?", 1)[0]) != "/api/belt":
            self.send_json(404, {"error": "неизвестный маршрут"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > 64 * 1024:
            self.send_json(413, {"error": "конфигурация слишком большая"})
            return
        try:
            raw = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self.send_json(400, {"error": "тело запроса — не JSON"})
            return
        try:
            belt, issues = belt_model.check_belt(raw)
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
            return
        blocking = [x for x in issues if x["level"] == belt_model.ERROR]
        if blocking:
            self.send_json(422, {"issues": issues})
            return
        try:
            belt_model.save_belt_file(BELT_FILE, belt)
        except OSError as exc:
            self.send_json(500, {"error": f"запись не удалась: {exc}"})
            return
        self.send_json(200, {"ok": True,
                             "file": BELT_FILE.name,
                             "issues": issues})

    # ─── static ─────────────────────────────────────────────────────

    def serve_static(self, route):
        if route in ("/", ""):
            route = "/index.html"
        target = (HERE / route.lstrip("/")).resolve()
        if not str(target).startswith(str(HERE)) or not target.is_file():
            self.send_json(404, {"error": "не найдено"})
            return
        ctype = CONTENT_TYPES.get(target.suffix.lower())
        if ctype is None:
            self.send_json(403, {"error": "тип файла запрещён"})
            return
        payload = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):  # тише в консоли
        sys.stderr.write("[belt-editor] %s\n" % (fmt % args))


def validate_file(path):
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        belt, issues = belt_model.check_belt(raw)
    except (OSError, ValueError) as exc:
        print(f"Файл не читается: {exc}")
        return 2
    for issue in issues:
        mark = "✕" if issue["level"] == belt_model.ERROR else "⚠"
        where = "" if issue["position"] is None else f" (П{issue['position']})"
        print(f"{mark} [{issue['code']}]{where} {issue['text']}")
    errors = sum(1 for x in issues if x["level"] == belt_model.ERROR)
    print(f"schema={belt['schema']} · позиций={len(belt['positions'])} · "
          f"ошибок={errors} · предупреждений={len(issues) - errors}")
    return 1 if errors else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1",
                        help="адрес (0.0.0.0 — доступна с других машин)")
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--open", action="store_true",
                        help="открыть браузер после старта")
    parser.add_argument("--validate", metavar="FILE",
                        help="проверить JSON-конфигурацию и выйти")
    args = parser.parse_args(argv)

    if args.validate:
        return validate_file(args.validate)

    server = ThreadingHTTPServer((args.host, args.port), BeltEditorHandler)
    print(f"Сборщик ленты: http://{args.host}:{args.port}/ "
          f"(файл конфигурации: {BELT_FILE.name})")
    if args.open:
        webbrowser.open(f"http://127.0.0.1:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("остановлено")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
