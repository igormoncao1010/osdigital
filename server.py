import json
import mimetypes
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "ordens.db"
HOST = "127.0.0.1"
PORT = 8000


def connection():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    with connection() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS service_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_date TEXT NOT NULL,
                delivery_date TEXT,
                customer_name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                address TEXT,
                device_type TEXT NOT NULL,
                brand TEXT,
                model TEXT,
                serial_number TEXT,
                accessories TEXT,
                reported_issue TEXT NOT NULL,
                technical_report TEXT,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'Recebido',
                estimated_value REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        existing = {row[1] for row in db.execute("PRAGMA table_info(service_orders)")}
        migrations = {
            "cpf": "TEXT", "color": "TEXT", "capacity": "TEXT",
            "unlock_password": "TEXT", "account_removed": "TEXT",
            "device_condition": "TEXT", "technical_checklist": "TEXT",
            "warranty_until": "TEXT", "service_kind": "TEXT DEFAULT 'Ordem de serviço'",
            "payment_method": "TEXT", "picked_up_by": "TEXT", "pickup_cpf": "TEXT",
            "pickup_date": "TEXT", "technician": "TEXT", "received_by": "TEXT",
        }
        for column, kind in migrations.items():
            if column not in existing:
                db.execute(f"ALTER TABLE service_orders ADD COLUMN {column} {kind}")


def order_dict(row):
    item = dict(row)
    item["number"] = f"OS-{item['id']:06d}"
    return item


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return None

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/orders":
            with connection() as db:
                rows = db.execute("SELECT * FROM service_orders ORDER BY id DESC").fetchall()
            return self.send_json([order_dict(row) for row in rows])

        if path.startswith("/api/orders/"):
            try:
                order_id = int(path.rsplit("/", 1)[1])
            except ValueError:
                return self.send_json({"error": "Número de OS inválido."}, 400)
            with connection() as db:
                row = db.execute("SELECT * FROM service_orders WHERE id = ?", (order_id,)).fetchone()
            if not row:
                return self.send_json({"error": "OS não encontrada."}, 404)
            return self.send_json(order_dict(row))

        return self.serve_static(path)

    def do_POST(self):
        if urlparse(self.path).path != "/api/orders":
            return self.send_json({"error": "Rota não encontrada."}, 404)
        payload = self.body()
        if payload is None:
            return self.send_json({"error": "JSON inválido."}, 400)
        error = validate(payload)
        if error:
            return self.send_json({"error": error}, 400)

        now = datetime.now().isoformat(timespec="seconds")
        values = normalized(payload)
        columns = list(values)
        with connection() as db:
            cursor = db.execute(
                f"INSERT INTO service_orders ({', '.join(columns)}, created_at, updated_at) "
                f"VALUES ({', '.join('?' for _ in columns)}, ?, ?)",
                [values[column] for column in columns] + [now, now],
            )
            row = db.execute("SELECT * FROM service_orders WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self.send_json(order_dict(row), 201)

    def do_PUT(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/orders/"):
            return self.send_json({"error": "Rota não encontrada."}, 404)
        try:
            order_id = int(path.rsplit("/", 1)[1])
        except ValueError:
            return self.send_json({"error": "Número de OS inválido."}, 400)
        payload = self.body()
        if payload is None:
            return self.send_json({"error": "JSON inválido."}, 400)
        error = validate(payload)
        if error:
            return self.send_json({"error": error}, 400)

        values = normalized(payload)
        assignments = ", ".join(f"{column} = ?" for column in values)
        now = datetime.now().isoformat(timespec="seconds")
        with connection() as db:
            exists = db.execute("SELECT 1 FROM service_orders WHERE id = ?", (order_id,)).fetchone()
            if not exists:
                return self.send_json({"error": "OS não encontrada."}, 404)
            db.execute(
                f"UPDATE service_orders SET {assignments}, updated_at = ? WHERE id = ?",
                [values[column] for column in values] + [now, order_id],
            )
            row = db.execute("SELECT * FROM service_orders WHERE id = ?", (order_id,)).fetchone()
        return self.send_json(order_dict(row))

    def serve_static(self, path):
        relative = "index.html" if path == "/" else path.lstrip("/")
        target = (ROOT / relative).resolve()
        if ROOT not in target.parents and target != ROOT:
            return self.send_error(403)
        if not target.is_file():
            return self.send_error(404)
        content = target.read_bytes()
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{kind}; charset=utf-8" if kind.startswith("text/") else kind)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


FIELDS = (
    "entry_date", "delivery_date", "customer_name", "cpf", "email", "phone", "address",
    "device_type", "brand", "model", "color", "capacity", "serial_number",
    "unlock_password", "account_removed", "accessories", "reported_issue",
    "device_condition", "technical_checklist", "technical_report", "notes", "status",
    "estimated_value", "warranty_until", "service_kind", "payment_method", "picked_up_by",
    "pickup_cpf", "pickup_date", "technician", "received_by",
)


def normalized(payload):
    result = {}
    for field in FIELDS:
        value = payload.get(field, "")
        if field == "estimated_value":
            try:
                result[field] = float(value) if value not in ("", None) else None
            except (TypeError, ValueError):
                result[field] = None
        else:
            result[field] = str(value).strip()
    return result


def validate(payload):
    labels = {
        "entry_date": "data de entrada",
        "customer_name": "nome completo",
        "device_type": "tipo do aparelho",
        "reported_issue": "defeito relatado",
    }
    for field, label in labels.items():
        if not str(payload.get(field, "")).strip():
            return f"Preencha o campo {label}."
    if payload.get("email") and "@" not in str(payload["email"]):
        return "Informe um e-mail válido."
    return None


if __name__ == "__main__":
    init_db()
    print(f"Sistema de OS disponível em http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
