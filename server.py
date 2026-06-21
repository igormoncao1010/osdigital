import json
import mimetypes
import os
import sqlite3
import textwrap
import threading
import webbrowser
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
            "warranty_items": "TEXT",
        }
        for column, kind in migrations.items():
            if column not in existing:
                db.execute(f"ALTER TABLE service_orders ADD COLUMN {column} {kind}")


def order_dict(row):
    item = dict(row)
    item["number"] = f"OS-{item['id']:06d}"
    item["pdf_url"] = f"/api/orders/{item['id']}/pdf"
    item["technician_pdf_url"] = f"/api/orders/{item['id']}/technician-pdf"
    item["client_pdf_url"] = f"/api/orders/{item['id']}/client-pdf"
    item["store_pdf_url"] = f"/api/orders/{item['id']}/store-pdf"
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
        if path == "/api/health":
            return self.send_json({"status": "online"})
        if path == "/api/orders":
            with connection() as db:
                rows = db.execute("SELECT * FROM service_orders ORDER BY id DESC").fetchall()
            return self.send_json([order_dict(row) for row in rows])

        if path.startswith("/api/orders/") and path.endswith(("/pdf", "/technician-pdf", "/client-pdf", "/store-pdf")):
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
            variant = "technician" if path.endswith("/technician-pdf") else "client" if path.endswith("/client-pdf") else "store" if path.endswith("/store-pdf") else "physical"
            target = generate_pdf(order, variant)
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
        print("[OS] Solicitação para criar ordem recebida.")
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
        for variant in ("physical", "technician", "client", "store"):
            generate_pdf(order, variant)
        print(f"[OS] {order['number']} criada; PDFs gerados em {PDF_DIR}.")
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
        for variant in ("physical", "technician", "client", "store"):
            generate_pdf(order, variant)
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
    "pickup_cpf", "pickup_date", "technician", "received_by", "warranty_items",
)

LEGAL_TERMS = [
    "Toda troca de peças ou manutenção em aparelhos eletrônicos tem garantia de 90 (noventa) dias, a contar da data de entrega do serviço.",
    "Procedimento de banho químico por si só não tem garantia, entrando somente na garantia as peças que forem trocadas junto com o serviço de banho químico.",
    "Nos procedimentos de banho químico é de conhecimento do cliente que o aparelho, caso esteja ligando e/ou funcionando parcialmente, pode parar de funcionar e/ou responder sem aviso ou intervenção técnica, não sendo a loja responsável por esses acontecimentos.",
    "A garantia exclui totalmente danos causados por mau uso, incluindo quedas, arranhões e/ou amassados.",
    "Devido à escassez de peças e dificuldade de importação, os retornos podem demorar até 2 dias úteis para serem atendidos.",
    "Orçamento e/ou procedimento de banho químico: o prazo para retorno ao cliente é de 3 a 4 dias úteis.",
    "Teste seu aparelho na entrega, pois não nos responsabilizamos por defeitos diferentes dos especificados na ordem de serviço.",
    "Não nos responsabilizamos por chips, cartões de memória, capas, películas ou quaisquer acessórios deixados no aparelho. Em caso de extravio, não haverá qualquer ressarcimento.",
    "A Buzz Tech não realiza backup de dados e não se responsabiliza pela perda de fotos, vídeos, documentos, aplicativos, contas ou quaisquer informações armazenadas no aparelho.",
    "Aparelhos que ingressarem na assistência sem imagem, sem ligar ou sem possibilidade de teste terão garantia limitada aos serviços efetivamente executados, não abrangendo componentes que não puderem ser testados previamente.",
    "Equipamentos abandonados: após 90 dias da comunicação de conclusão do serviço, poderão ser cobradas taxas de armazenamento conforme legislação aplicável, ficando o aparelho disponível para resgate mediante pagamento.",
    "A aprovação verbal, por mensagem, ligação telefônica, WhatsApp ou qualquer meio eletrônico autoriza a execução do orçamento e dos serviços descritos nesta Ordem de Serviço/Garantia.",
    "Aparelhos com histórico de queda, oxidação, contato com líquidos, superaquecimento, tentativas anteriores de reparo ou danos estruturais podem apresentar falhas adicionais ou tornar-se irrecuperáveis durante o processo técnico.",
    "Serviços realizados em aparelhos Apple ou Android poderão afetar funcionalidades biométricas já comprometidas anteriormente. Não garantimos recuperação de Face ID, Touch ID ou biometria quando houver defeito pré-existente.",
    "Equipamentos que apresentam cola solta, tela descolando, carcaça empenada ou estrutura comprometida poderão sofrer agravamento dos danos durante o reparo, não caracterizando falha na execução do serviço.",
    "Em aparelhos com oxidação ou contato com líquidos não há garantia sobre recuperação de dados ou funcionamento futuro, ainda que o aparelho volte a funcionar após o reparo.",
    "Orçamentos aprovados autorizam a execução integral do serviço descrito nesta Ordem de Serviço/Garantia.",
    "A garantia concedida pela Buzz Tech cobre exclusivamente defeitos de funcionamento relacionados ao produto ou serviço descrito nesta OS. Não cobre quedas, impactos, líquidos, oxidação, mau uso, tentativa de reparo por terceiros, violação de lacres ou danos estéticos.",
]

CLIENT_DECLARATION = "Declaro que as informações fornecidas nesta Ordem de Serviço são verdadeiras e autorizo a Buzz Tech Assistência Técnica a realizar os procedimentos necessários para diagnóstico, orçamento e reparo do equipamento descrito neste documento."


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
    commands.extend(["0.02 0.03 0.02 rg", f"24 {top-42} 547 37 re f", f"q 64 0 0 36 31 {top-41} cm /Im1 Do Q", "1 1 1 rg"])
    pdf_text(commands, 385, top - 17, f"{order['number']} · {copy_name}", 8, True)
    pdf_text(commands, 385, top - 29, order.get("service_kind") or "ORDEM DE SERVIÇO", 5)
    pdf_text(commands, 385, top - 37, "BUZZ TECH · ASSISTÊNCIA TÉCNICA ESPECIALIZADA", 4)
    commands.append("0 0 0 rg")
    pdf_text(commands, 30, top-50, f"Entrada: {order.get('entry_date') or '—'}  Entrega: {order.get('delivery_date') or '—'}  Garantia: {order.get('warranty_until') or '—'}  Status: {order.get('status') or '—'}", 5, True)
    pdf_text(commands, 30, top-63, f"CLIENTE: {order.get('customer_name') or '—'}  CPF: {order.get('cpf') or '—'}  CONTATO: {order.get('phone') or '—'}  E-MAIL: {order.get('email') or '—'}", 5)
    pdf_text(commands, 30, top-74, f"ENDEREÇO: {order.get('address') or '—'}", 5)
    pdf_text(commands, 30, top-87, f"APARELHO: {order.get('device_type') or '—'}  MARCA/MODELO: {order.get('brand') or '—'} / {order.get('model') or '—'}  COR/CAP.: {order.get('color') or '—'} / {order.get('capacity') or '—'}  IMEI/SÉRIE: {order.get('serial_number') or '—'}", 5)
    pdf_text(commands, 30, top-98, f"SENHA/PADRÃO: {order.get('unlock_password') or '—'}  CONTA REMOVIDA: {order.get('account_removed') or '—'}  ACESSÓRIOS: {order.get('accessories') or '—'}", 5)
    for index, line in enumerate(textwrap.wrap(f"DEFEITO: {order.get('reported_issue') or '—'}", 90)[:3]):
        pdf_text(commands, 30, top-112-index*6, line, 5)
    for index, line in enumerate(textwrap.wrap(f"ESTADO NA ENTRADA: {order.get('device_condition') or '—'}", 72)[:3]):
        pdf_text(commands, 330, top-112-index*6, line, 5)
    pdf_text(commands, 30, top-134, f"CHECKLIST: {order.get('technical_checklist') or '—'}", 5)
    for index, line in enumerate(textwrap.wrap(f"LAUDO/DIAGNÓSTICO: {order.get('technical_report') or 'A preencher'}  OBS.: {order.get('notes') or '—'}", 112)[:3]):
        pdf_text(commands, 30, top-147-index*6, line, 5)
    pdf_text(commands, 30, top-169, f"VALOR: R$ {order.get('estimated_value') or '—'}  PAGAMENTO: {order.get('payment_method') or '—'}  GARANTIA REFERENTE A: {order.get('warranty_items') or '—'}", 5, True)
    commands.extend(["0.92 0.95 0.97 rg", f"30 {top-185} 535 11 re f", "0 0 0 rg"])
    pdf_text(commands, 35, top-181, "TELA TRINCADA, OXIDAÇÃO E DANOS FÍSICOS NÃO SÃO COBERTOS PELA GARANTIA.", 5, True)
    for column, start in enumerate((0, 6, 12)):
        legal_y = top - 195
        x = 30 + column * 182
        for number, term in enumerate(LEGAL_TERMS[start:start+6], start+1):
            for line in textwrap.wrap(f"{number}. {term}", 72):
                pdf_text(commands, x, legal_y, line, 3.6)
                legal_y -= 4.2
            legal_y -= 1
    for index, line in enumerate(textwrap.wrap(f"DECLARAÇÃO: {CLIENT_DECLARATION}", 165)[:2]):
        pdf_text(commands, 30, top-325-index*4, line, 3.4)
    pdf_text(commands, 30, top-345, f"Técnico: {order.get('technician') or '________________'}  Recebido por: {order.get('received_by') or '________________'}  Retirado por: {order.get('picked_up_by') or '________________'}  Cliente: ____________________", 4.5)
    pdf_text(commands, 30, top-363, "BUZZ TECH · Feira dos Importados de Brasília · Bloco A · Loja 73/74 · (61) 98199-4436 · @buzztechbsb", 4.2, True)
    pdf_text(commands, 30, top-374, "Terça a domingo, 09h às 18h (inclusive feriados) · Este documento não possui valor fiscal.", 4)
    commands.append(f"0.65 0.65 0.65 RG 24 {bottom} 547 {top-bottom} re S")


def technician_page(commands, order):
    commands.extend(["0.18 0.48 0.72 rg", "6 213 130 36 re f", "0 0 0 rg"])
    pdf_text(commands, 12, 232, "BUZZ TECH", 12, True)
    pdf_text(commands, 88, 232, order["number"], 7, True)
    pdf_text(commands, 12, 219, "FICHA DO TÉCNICO · 5 x 9 cm", 5)
    fields = [
        ("CLIENTE", order.get("customer_name"), 3),
        ("CONTATO", " · ".join(filter(None, [order.get("phone"), order.get("email")])), 3),
        ("SENHA / PADRÃO", order.get("unlock_password"), 2),
        ("PROBLEMA / DIAGNÓSTICO", order.get("technical_report") or order.get("reported_issue") or "A preencher", 5),
    ]
    y = 199
    for index, (label, value, lines) in enumerate(fields):
        height = 52 if index == 3 else 36
        commands.append(f"0.82 0.86 0.9 RG 8 {y-height+4} 126 {height} re S")
        pdf_lines(commands, 12, y - 6, label, value, 28 if index == 3 else 31, lines)
        y -= height + 5
    pdf_text(commands, 10, 18, "Técnico: ____________________", 6)
    pdf_text(commands, 10, 8, "Data: ____/____/______", 6)


def write_simple_pdf(path, commands, media_box=(595, 842)):
    stream = "\n".join(commands).encode("cp1252", "replace")
    logo = (ROOT / "01.jpg").read_bytes()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {media_box[0]} {media_box[1]}] /Resources << /Font << /F1 5 0 R /F2 6 0 R >> /XObject << /Im1 7 0 R >> >> /Contents 4 0 R >>".encode(),
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        f"<< /Type /XObject /Subtype /Image /Width 288 /Height 163 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(logo)} >>\nstream\n".encode() + logo + b"\nendstream",
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


def generate_pdf(order, variant="physical"):
    PDF_DIR.mkdir(exist_ok=True)
    suffix = {"technician": "-TECNICO", "client": "-CLIENTE-DIGITAL", "store": "-LOJA"}.get(variant, "")
    target = PDF_DIR / f"{order['number']}{suffix}.pdf"
    commands = []
    if variant == "technician":
        technician_page(commands, order)
    elif variant == "physical":
        service_copy(commands, order, 830, "VIA DA EMPRESA")
        service_copy(commands, order, 420, "VIA DO CLIENTE")
    elif variant == "client":
        service_copy(commands, order, 420, "VIA DIGITAL DO CLIENTE")
    else:
        service_copy(commands, order, 420, "VIA ARQUIVADA DA LOJA")
    size = (142, 255) if variant == "technician" else (595, 842) if variant == "physical" else (595, 421)
    write_simple_pdf(target, commands, size)
    return target


if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Sistema de OS disponível em http://{HOST}:{PORT}")
    if os.environ.get("OS_DIGITAL_NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    server.serve_forever()
