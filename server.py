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


def br_date(value):
    value = str(value or "")
    if len(value) >= 10 and value[4:5] == "-":
        return f"{value[8:10]}/{value[5:7]}/{value[:4]}"
    return value or "—"


def template_copy(commands, order, translate_x=0, translate_y=0, scale=1, copy_name="VIA DO CLIENTE"):
    commands.append(f"q {scale} 0 0 {scale} {translate_x} {translate_y} cm")
    commands.append("q 595 0 0 842 0 0 cm /Im2 Do Q")
    commands.append("0.75 0 0 rg")
    pdf_text(commands, 443, 795, str(order.get("number", "")).replace("OS-", ""), 22, True)
    commands.append("0 0 0 rg")
    pdf_text(commands, 470, 772, br_date(order.get("warranty_until")), 7)
    pdf_text(commands, 85, 735, br_date(order.get("entry_date")), 7, True)
    pdf_text(commands, 385, 735, br_date(order.get("delivery_date")), 7, True)
    pdf_text(commands, 68, 704, order.get("customer_name"), 7)
    pdf_text(commands, 443, 704, order.get("phone"), 7)
    pdf_text(commands, 63, 682, order.get("cpf"), 7)
    pdf_text(commands, 238, 682, order.get("email"), 7)
    pdf_text(commands, 66, 663, order.get("address"), 7)
    pdf_text(commands, 58, 627, order.get("brand"), 7)
    pdf_text(commands, 174, 627, order.get("model"), 7)
    pdf_text(commands, 291, 627, order.get("color"), 7)
    pdf_text(commands, 378, 627, order.get("capacity"), 7)
    pdf_text(commands, 464, 627, order.get("serial_number"), 7)
    pdf_text(commands, 150, 603, order.get("unlock_password"), 7)
    if str(order.get("account_removed", "")).lower() == "sim": pdf_text(commands, 411, 603, "X", 7, True)
    if str(order.get("account_removed", "")).lower() == "não": pdf_text(commands, 451, 603, "X", 7, True)
    for index, line in enumerate(textwrap.wrap(str(order.get("reported_issue") or ""), 42)[:6]):
        pdf_text(commands, 18, 570-index*12, line, 6.5)
    condition_map = {"Tela trincada":(214,578),"Tampa quebrada":(214,566),"Amassado":(214,554),"Oxidação/Líquido":(214,542),"Sem imagem":(214,530),"Não liga":(214,518),"Já aberto":(309,578),"Touch falha":(309,566),"Botões falham":(309,554),"Carga intermitente":(309,542)}
    accessory_map = {"Carregador":(423,578),"Cabo USB":(423,566),"Capinha":(423,554),"Cartão/Chip":(423,542),"Película":(423,530),"Caixa original":(423,518)}
    checklist_map = {"Liga":(48,487),"Carrega":(164,487),"Som":(277,487),"Microfone":(391,487),"Alto-falante":(502,487),"Wi-Fi":(48,468),"Bluetooth":(164,468),"Face ID":(277,468),"Biometria":(391,468),"Câmeras":(502,468),"Botões":(164,449),"Chip":(277,449),"Tela":(391,449),"Conector":(502,449),"NFC":(48,430),"Vibração":(164,430),"Flash":(277,430),"Proximidade":(391,430)}
    selected = lambda key: {item.strip() for item in str(order.get(key) or "").split(",")}
    for key, position in condition_map.items():
        if key in selected("device_condition"): pdf_text(commands, *position, "X", 6, True)
    for key, position in accessory_map.items():
        if key in selected("accessories"): pdf_text(commands, *position, "X", 6, True)
    for key, position in checklist_map.items():
        if key in selected("technical_checklist"): pdf_text(commands, *position, "X", 6, True)
    for index, line in enumerate(textwrap.wrap(" ".join(filter(None,[str(order.get('technical_report') or ''),str(order.get('notes') or '')])), 105)[:2]):
        pdf_text(commands, 98, 409-index*10, line, 6)
    warranty_map = {"Aparelho completo":(25,157),"Tela":(124,157),"Bateria":(181,157),"Conector de carga":(254,157),"Alto-falante":(341,157),"Microfone":(425,157)}
    for key, position in warranty_map.items():
        if key in selected("warranty_items"): pdf_text(commands, *position, "X", 6, True)
    payment_map = {"Dinheiro":(25,108),"Pix":(78,108),"Cartão":(131,108)}
    for key, position in payment_map.items():
        if str(order.get("payment_method") or "").lower() == key.lower(): pdf_text(commands, *position, "X", 6, True)
    commands.append("1 1 1 rg")
    pdf_text(commands, 358, 103, f"R$ {order.get('estimated_value') or '—'}", 10, True)
    commands.append("0 0 0 rg")
    pdf_text(commands, 457, 102, order.get("picked_up_by"), 6)
    pdf_text(commands, 457, 82, order.get("pickup_cpf"), 6)
    pdf_text(commands, 470, 64, br_date(order.get("pickup_date")), 6)
    pdf_text(commands, 220, 42, order.get("technician"), 6, True)
    pdf_text(commands, 340, 42, order.get("received_by"), 6, True)
    commands.append("1 1 1 rg")
    pdf_text(commands, 455, 10, copy_name, 4.5, True)
    commands.append("Q")


def digital_page(commands, order, copy_name, translate_x=0, translate_y=0, scale=1):
    commands.append(f"q {scale} 0 0 {scale} {translate_x} {translate_y} cm")
    commands.extend(["0.02 0.03 0.02 rg", "24 762 547 62 re f", "q 92 0 0 52 34 767 cm /Im1 Do Q", "1 1 1 rg"])
    pdf_text(commands, 350, 797, order["number"], 18, True)
    pdf_text(commands, 350, 780, copy_name, 8, True)
    pdf_text(commands, 350, 769, "ORDEM DE SERVIÇO · BUZZ TECH", 6)
    commands.append("0 0 0 rg")
    pdf_text(commands, 30, 748, f"Entrada: {br_date(order.get('entry_date'))}    Entrega: {br_date(order.get('delivery_date'))}    Garantia: {br_date(order.get('warranty_until'))}    Status: {order.get('status') or '—'}", 7, True)
    commands.extend(["0.92 0.96 0.86 rg", "24 712 547 25 re f", "0 0 0 rg"])
    pdf_text(commands, 32, 722, "1  DADOS DO CLIENTE", 9, True)
    pdf_text(commands, 32, 698, f"Nome: {order.get('customer_name') or '—'}", 8)
    pdf_text(commands, 315, 698, f"Telefone: {order.get('phone') or '—'}", 8)
    pdf_text(commands, 32, 682, f"CPF: {order.get('cpf') or '—'}    E-mail: {order.get('email') or '—'}", 7)
    pdf_text(commands, 32, 666, f"Endereço: {order.get('address') or '—'}", 7)
    commands.extend(["0.92 0.96 0.86 rg", "24 625 547 25 re f", "0 0 0 rg"])
    pdf_text(commands, 32, 635, "2  DADOS DO APARELHO", 9, True)
    pdf_text(commands, 32, 611, f"Aparelho: {order.get('device_type') or '—'}    Marca: {order.get('brand') or '—'}    Modelo: {order.get('model') or '—'}", 7.5)
    pdf_text(commands, 32, 595, f"Cor: {order.get('color') or '—'}    Capacidade: {order.get('capacity') or '—'}    IMEI/Série: {order.get('serial_number') or '—'}", 7)
    pdf_text(commands, 32, 579, f"Senha/Padrão: {order.get('unlock_password') or '—'}    Conta removida: {order.get('account_removed') or '—'}    Acessórios: {order.get('accessories') or '—'}", 7)
    commands.extend(["0.92 0.96 0.86 rg", "24 538 547 25 re f", "0 0 0 rg"])
    pdf_text(commands, 32, 548, "3  ATENDIMENTO E DIAGNÓSTICO", 9, True)
    for index, line in enumerate(textwrap.wrap(f"Defeito informado: {order.get('reported_issue') or '—'}", 78)[:3]): pdf_text(commands, 32, 522-index*11, line, 7)
    for index, line in enumerate(textwrap.wrap(f"Estado na entrada: {order.get('device_condition') or '—'}", 62)[:3]): pdf_text(commands, 315, 522-index*11, line, 7)
    pdf_text(commands, 32, 480, f"Checklist: {order.get('technical_checklist') or '—'}", 6.5)
    for index, line in enumerate(textwrap.wrap(f"Laudo/Diagnóstico: {order.get('technical_report') or 'A preencher'}  Observações: {order.get('notes') or '—'}", 115)[:3]): pdf_text(commands, 32, 462-index*10, line, 7)
    commands.extend(["0.02 0.03 0.02 rg", "24 414 547 20 re f", "1 1 1 rg"])
    pdf_text(commands, 50, 421, "TELA TRINCADA, OXIDAÇÃO E DANOS FÍSICOS NÃO SÃO COBERTOS PELA GARANTIA.", 7, True)
    commands.append("0 0 0 rg")
    for column, start in enumerate((0, 9)):
        y = 400; x = 28 + column * 280
        for number, term in enumerate(LEGAL_TERMS[start:start+9], start+1):
            for line in textwrap.wrap(f"{number}. {term}", 73):
                pdf_text(commands, x, y, line, 4.4)
                y -= 5
            y -= 2
    commands.extend(["0.92 0.96 0.86 rg", "24 166 547 24 re f", "0 0 0 rg"])
    pdf_text(commands, 32, 175, f"GARANTIA REFERENTE A: {order.get('warranty_items') or '—'}", 7, True)
    pdf_text(commands, 32, 145, f"Pagamento: {order.get('payment_method') or '—'}", 7)
    commands.extend(["0.02 0.03 0.02 rg", "300 126 271 31 re f", "1 1 1 rg"])
    pdf_text(commands, 320, 137, f"VALOR TOTAL APROVADO: R$ {order.get('estimated_value') or '—'}", 9, True)
    commands.append("0 0 0 rg")
    for index, line in enumerate(textwrap.wrap(f"DECLARAÇÃO DO CLIENTE: {CLIENT_DECLARATION}", 135)[:3]): pdf_text(commands, 30, 108-index*7, line, 5)
    pdf_text(commands, 30, 72, f"Responsável técnico: {order.get('technician') or '________________'}", 6)
    pdf_text(commands, 220, 72, f"Recebido por: {order.get('received_by') or '________________'}", 6)
    pdf_text(commands, 390, 72, "Assinatura do cliente: __________________", 6)
    commands.extend(["0.02 0.03 0.02 rg", "24 24 547 31 re f", "1 1 1 rg"])
    pdf_text(commands, 32, 43, "BUZZ TECH · Feira dos Importados de Brasília · Bloco A · Loja 73/74 · (61) 98199-4436 · @buzztechbsb", 5.5, True)
    pdf_text(commands, 32, 32, "Terça a domingo, 09h às 18h · Este documento não possui valor fiscal.", 5)
    commands.append("Q")


def compact_copy(commands, order, top, copy_name):
    def bar(y, title, x=24, width=547):
        commands.extend(["0.02 0.03 0.02 rg", f"{x} {y} {width} 10 re f", "1 1 1 rg"])
        pdf_text(commands, x+4, y+3, title, 5.2, True)
        commands.append("0 0 0 rg")

    def field(x, y, width, height, label, value, wrap_width=38, max_lines=2):
        commands.extend(["0.55 0.58 0.56 RG", f"{x} {y} {width} {height} re S", "0 0 0 rg"])
        pdf_text(commands, x+3, y+height-6, label.upper(), 3.6, True)
        for index, line in enumerate(textwrap.wrap(str(value or "—"), wrap_width)[:max_lines]):
            pdf_text(commands, x+3, y+height-13-index*6, line, 5)

    commands.extend(["0.02 0.03 0.02 rg", f"24 {top-34} 547 32 re f", f"q 66 0 0 29 31 {top-32} cm /Im1 Do Q", "1 1 1 rg"])
    pdf_text(commands, 92, top-14, "BUZZ TECH", 12, True)
    pdf_text(commands, 92, top-25, "Assistência técnica especializada", 4.5)
    pdf_text(commands, 420, top-13, copy_name, 5)
    pdf_text(commands, 455, top-27, order["number"], 13, True)
    commands.append("0 0 0 rg")
    pdf_text(commands, 28, top-44, f"Entrada: {br_date(order.get('entry_date'))}", 4.5, True)
    pdf_text(commands, 183, top-44, f"Entrega: {br_date(order.get('delivery_date'))}", 4.5, True)
    pdf_text(commands, 330, top-44, f"Garantia: {br_date(order.get('warranty_until'))}", 4.5, True)
    pdf_text(commands, 480, top-44, f"Status: {order.get('status') or '—'}", 4.5, True)
    bar(top-58, "1. DADOS DO CLIENTE")
    field(24, top-80, 188, 20, "Nome completo", order.get("customer_name"), 42)
    field(212, top-80, 95, 20, "CPF", order.get("cpf"), 20)
    field(307, top-80, 115, 20, "Telefone", order.get("phone"), 24)
    field(422, top-80, 149, 20, "E-mail", order.get("email"), 32)
    field(24, top-94, 547, 14, "Endereço", order.get("address"), 105, 1)
    bar(top-107, "2. DADOS DO APARELHO")
    field(24, top-129, 110, 20, "Aparelho", order.get("device_type"), 22)
    field(134, top-129, 110, 20, "Marca", order.get("brand"), 22)
    field(244, top-129, 110, 20, "Modelo", order.get("model"), 22)
    field(354, top-129, 110, 20, "Cor", order.get("color"), 22)
    field(464, top-129, 107, 20, "Capacidade", order.get("capacity"), 22)
    field(24, top-147, 185, 18, "IMEI / Série", order.get("serial_number"), 36)
    field(209, top-147, 185, 18, "Senha / Padrão", order.get("unlock_password"), 36)
    field(394, top-147, 177, 18, "Conta removida", order.get("account_removed"), 34)
    bar(top-159, "3. DEFEITO INFORMADO", 24, 181)
    bar(top-159, "4. ESTADO NA ENTRADA", 207, 181)
    bar(top-159, "5. ACESSÓRIOS", 390, 181)
    field(24, top-194, 181, 35, "", order.get("reported_issue"), 38, 4)
    field(207, top-194, 181, 35, "", order.get("device_condition"), 38, 4)
    field(390, top-194, 181, 35, "", order.get("accessories"), 38, 4)
    bar(top-206, "6. CHECKLIST TÉCNICO")
    field(24, top-220, 547, 14, "", order.get("technical_checklist"), 108, 1)
    field(24, top-243, 280, 21, "Laudo / observações técnicas", " ".join(filter(None,[str(order.get('technical_report') or ''),str(order.get('notes') or '')])), 58, 2)
    field(304, top-243, 267, 21, "Valor / Pagamento", f"R$ {order.get('estimated_value') or '—'} · {order.get('payment_method') or '—'}", 52, 2)
    field(24, top-255, 547, 12, "Garantia referente a", order.get("warranty_items"), 105, 1)
    bar(top-267, "TELA TRINCADA, OXIDAÇÃO E DANOS FÍSICOS NÃO SÃO COBERTOS PELA GARANTIA.")
    for column, start in enumerate((0, 6, 12)):
        y = top-274; x = 25 + column*182
        for number, term in enumerate(LEGAL_TERMS[start:start+6], start+1):
            for line in textwrap.wrap(f"{number}. {term}", 93):
                pdf_text(commands, x, y, line, 2.25)
                y -= 2.5
            y -= .7
    pdf_text(commands, 25, top-327, f"DECLARAÇÃO DO CLIENTE: {CLIENT_DECLARATION}", 2.6)
    field(24, top-349, 190, 18, "Responsável técnico", order.get("technician"), 38, 1)
    field(214, top-349, 100, 18, "Recebido por", order.get("received_by"), 20, 1)
    field(314, top-349, 120, 18, "Retirado por / CPF", " · ".join(filter(None,[str(order.get('picked_up_by') or ''),str(order.get('pickup_cpf') or '')])), 24, 1)
    field(434, top-349, 137, 18, "Assinatura do cliente", "", 26, 1)
    pdf_text(commands, 175, top-358, "Feira dos Importados de Brasília · Bloco A · Loja 73/74 · (61) 98199-4436 · @buzztechbsb", 2.8)


def technician_page(commands, order):
    commands.extend(["0.02 0.03 0.02 rg", "6 213 130 36 re f", "q 43 0 0 24 9 219 cm /Im1 Do Q", "1 1 1 rg"])
    pdf_text(commands, 78, 235, order["number"], 8, True)
    pdf_text(commands, 78, 223, "FICHA DO TÉCNICO", 5.5, True)
    commands.append("0 0 0 rg")
    fields = [
        (177, 30, "CLIENTE", order.get("customer_name"), 31, 2),
        (141, 30, "CONTATO", " · ".join(filter(None, [order.get("phone"), order.get("email")])), 31, 2),
        (105, 30, "SENHA / PADRÃO", order.get("unlock_password"), 31, 2),
        (38, 61, "PROBLEMA / DIAGNÓSTICO", order.get("technical_report") or order.get("reported_issue") or "A preencher", 34, 6),
    ]
    for y, height, label, value, width, max_lines in fields:
        commands.extend(["0.92 0.96 0.86 rg", f"8 {y+height-10} 126 10 re f", "0.72 0.78 0.74 RG", f"8 {y} 126 {height} re S", "0 0 0 rg"])
        pdf_text(commands, 12, y+height-7, label, 5.5, True)
        for index, line in enumerate(textwrap.wrap(str(value or "—"), width)[:max_lines]):
            pdf_text(commands, 12, y+height-20-index*8, line, 6.5)
    pdf_text(commands, 10, 29, f"Técnico: {order.get('technician') or '________________'}   Data: ____/____", 5)
    commands.extend(["0.02 0.03 0.02 rg", "6 5 130 19 re f", "1 1 1 rg"])
    pdf_text(commands, 11, 15, "BUZZ TECH · (61) 98199-4436", 5.5, True)
    pdf_text(commands, 11, 8, "Feira dos Importados · Bloco A · Loja 73/74", 4)


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
        compact_copy(commands, order, 820, "VIA DA LOJA")
        compact_copy(commands, order, 400, "VIA DO CLIENTE")
    elif variant == "client":
        compact_copy(commands, order, 360, "VIA DIGITAL DO CLIENTE")
    else:
        compact_copy(commands, order, 360, "VIA ARQUIVADA DA LOJA")
    size = (142, 255) if variant == "technician" else (595, 842) if variant == "physical" else (595, 365)
    write_simple_pdf(target, commands, size)
    return target


if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Sistema de OS disponível em http://{HOST}:{PORT}")
    if os.environ.get("OS_DIGITAL_NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    server.serve_forever()
