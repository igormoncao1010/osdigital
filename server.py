import json
import mimetypes
import sqlite3
import textwrap
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "ordens.db"
PDF_DIR = ROOT / "pdfs"
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
    item["pdf_url"] = f"/api/orders/{item['id']}/pdf"
    item["technician_pdf_url"] = f"/api/orders/{item['id']}/technician-pdf"
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

        if path.startswith("/api/orders/") and path.endswith(("/pdf", "/technician-pdf")):
            parts = path.strip("/").split("/")
            try:
                order_id = int(parts[2])
            except (ValueError, IndexError):
                return self.send_json({"error": "Número de OS inválido."}, 400)
            with connection() as db:
                row = db.execute("SELECT * FROM service_orders WHERE id = ?", (order_id,)).fetchone()
            if not row:
                return self.send_json({"error": "OS não encontrada."}, 404)
            order = order_dict(row)
            technician = path.endswith("/technician-pdf")
            target = generate_pdf(order, technician)
            return self.send_pdf(target)

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

    def send_pdf(self, target):
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", f'inline; filename="{target.name}"')
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

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
        order = order_dict(row)
        generate_pdf(order, False)
        generate_pdf(order, True)
        return self.send_json(order, 201)

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
        order = order_dict(row)
        generate_pdf(order, False)
        generate_pdf(order, True)
        return self.send_json(order)

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


def pdf_safe(value):
    return str(value or "—").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_text(commands, x, y, text, size=8, bold=False):
    font = "F2" if bold else "F1"
    safe = pdf_safe(text).encode("cp1252", "replace").decode("cp1252")
    commands.append(f"BT /{font} {size} Tf {x} {y} Td ({safe}) Tj ET")


def pdf_lines(commands, x, y, label, value, width=64, max_lines=2):
    pdf_text(commands, x, y, label.upper(), 6, True)
    lines = textwrap.wrap(str(value or "—"), width=width)[:max_lines] or ["—"]
    for index, line in enumerate(lines):
        pdf_text(commands, x, y - 10 - index * 9, line, 7)


def service_copy(commands, order, top, copy_name):
    bottom = top - 395
    commands.extend(["0.18 0.48 0.72 rg", f"24 {top-48} 547 42 re f", "0 0 0 rg"])
    pdf_text(commands, 38, top - 25, "OS DIGITAL", 17, True)
    pdf_text(commands, 390, top - 20, f"{order['number']}  ·  {copy_name}", 10, True)
    pdf_text(commands, 390, top - 36, order.get("service_kind") or "ORDEM DE SERVIÇO", 7)
    y = top - 66
    pdf_text(commands, 30, y, f"Entrada: {order.get('entry_date') or '—'}", 7, True)
    pdf_text(commands, 190, y, f"Entrega: {order.get('delivery_date') or '—'}", 7)
    pdf_text(commands, 350, y, f"Status: {order.get('status') or '—'}", 7)
    pdf_text(commands, 475, y, f"Garantia: {order.get('warranty_until') or '—'}", 7)
    y -= 18
    pdf_text(commands, 30, y, "CLIENTE", 8, True)
    y -= 12
    pdf_lines(commands, 30, y, "Nome", order.get("customer_name"), 42)
    pdf_lines(commands, 235, y, "CPF", order.get("cpf"), 24)
    pdf_lines(commands, 360, y, "Contato", order.get("phone") or order.get("email"), 34)
    y -= 32
    pdf_lines(commands, 30, y, "Endereço", order.get("address"), 90)
    y -= 32
    pdf_text(commands, 30, y, "APARELHO", 8, True)
    y -= 12
    pdf_lines(commands, 30, y, "Equipamento", order.get("device_type"), 22)
    pdf_lines(commands, 145, y, "Marca / Modelo", " / ".join(filter(None, [order.get("brand"), order.get("model")])), 30)
    pdf_lines(commands, 305, y, "Cor / Capacidade", " / ".join(filter(None, [order.get("color"), order.get("capacity")])), 24)
    pdf_lines(commands, 440, y, "IMEI / Série", order.get("serial_number"), 24)
    y -= 34
    pdf_lines(commands, 30, y, "Senha / padrão", order.get("unlock_password"), 22)
    pdf_lines(commands, 145, y, "Conta removida", order.get("account_removed"), 20)
    pdf_lines(commands, 265, y, "Acessórios", order.get("accessories"), 48)
    y -= 34
    pdf_lines(commands, 30, y, "Defeito informado", order.get("reported_issue"), 65, 3)
    pdf_lines(commands, 330, y, "Estado na entrada", order.get("device_condition"), 45, 3)
    y -= 44
    pdf_lines(commands, 30, y, "Checklist técnico", order.get("technical_checklist"), 85, 2)
    y -= 34
    pdf_lines(commands, 30, y, "Laudo / diagnóstico", order.get("technical_report") or "A preencher", 68, 3)
    pdf_lines(commands, 365, y, "Valor aprovado", f"R$ {order.get('estimated_value') or '—'}", 22)
    y -= 44
    commands.extend(["0.92 0.95 0.97 rg", f"30 {y-5} 535 20 re f", "0 0 0 rg"])
    pdf_text(commands, 38, y + 2, "Garantia restrita ao serviço executado. Danos físicos, líquidos, oxidação e mau uso não estão cobertos.", 6, True)
    y -= 27
    pdf_text(commands, 30, y, "Responsável técnico: ____________________", 7)
    pdf_text(commands, 225, y, "Recebido por: ____________________", 7)
    pdf_text(commands, 410, y, "Cliente: ____________________", 7)
    commands.append(f"0.65 0.65 0.65 RG 24 {bottom} 547 {top-bottom} re S")


def technician_page(commands, order):
    commands.extend(["0.18 0.48 0.72 rg", "24 758 547 60 re f", "0 0 0 rg"])
    pdf_text(commands, 42, 790, "FICHA TÉCNICA", 20, True)
    pdf_text(commands, 420, 790, order["number"], 16, True)
    pdf_text(commands, 42, 770, "Documento interno · não entregar ao cliente", 8)
    y = 730
    for label, value in [
        ("CLIENTE", order.get("customer_name")),
        ("CONTATO", " · ".join(filter(None, [order.get("phone"), order.get("email")]))),
        ("APARELHO", " · ".join(filter(None, [order.get("device_type"), order.get("brand"), order.get("model")]))),
        ("SENHA / PADRÃO", order.get("unlock_password")),
        ("PROBLEMA INFORMADO", order.get("reported_issue")),
        ("ESTADO NA ENTRADA", order.get("device_condition")),
        ("ACESSÓRIOS", order.get("accessories")),
        ("DIAGNÓSTICO TÉCNICO", order.get("technical_report") or "A preencher pelo técnico"),
    ]:
        commands.append(f"0.86 0.89 0.91 RG 32 {y-48} 531 58 re S")
        pdf_lines(commands, 44, y - 12, label, value, 96, 4)
        y -= 68
    pdf_text(commands, 42, 145, "Serviço realizado / peças utilizadas:", 8, True)
    commands.extend(["0.7 0.7 0.7 RG", "42 125 m 550 125 l S", "42 100 m 550 100 l S", "42 75 m 550 75 l S"])
    pdf_text(commands, 42, 45, "Técnico: __________________________   Data: ____/____/______   Assinatura: __________________________", 8)


def write_simple_pdf(path, commands):
    stream = "\n".join(commands).encode("cp1252", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    content = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(content))
        content.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(content)
    content.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    path.write_bytes(content)


def generate_pdf(order, technician=False):
    PDF_DIR.mkdir(exist_ok=True)
    suffix = "-TECNICO" if technician else ""
    target = PDF_DIR / f"{order['number']}{suffix}.pdf"
    commands = []
    if technician:
        technician_page(commands, order)
    else:
        service_copy(commands, order, 830, "VIA DA EMPRESA")
        service_copy(commands, order, 420, "VIA DO CLIENTE")
    write_simple_pdf(target, commands)
    return target


if __name__ == "__main__":
    init_db()
    print(f"Sistema de OS disponível em http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
