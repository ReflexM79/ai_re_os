import os
import re
import sqlite3
import shutil
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

from db import get_connection, DB_PATH
from director import ejecutar_director, registrar_evento
from calendar_engine import verificar_disponibilidad

load_dotenv()

app = FastAPI(
    title="Depa Las Villas — AI Property OS API (Paso 10)",
    description="Receptor idempotente de webhooks, sincronizador iCal y respaldos SQLite WAL",
    version="1.0.0"
)

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "depa_las_villas_secret_2026")

# --- MODELOS DE ENTRADA (CONTRATOS PYDANTIC) ---
class WebhookReservaPayload(BaseModel):
    event_id: str
    channel: str  # airbnb, booking, vrbo, directo
    codigo_reserva: str
    checkin: str  # YYYY-MM-DD
    checkout: str  # YYYY-MM-DD
    precio_total: str
    comision: str = "0.00"
    neto: str
    huesped: str = "Huésped Externo"
    status: str = "confirmada"

class WebhookMensajePayload(BaseModel):
    event_id: str
    channel: str
    huesped: str
    mensaje: str
    tarifa_actual_noche: float = 1300.00

# --- UTILIDADES DE IDEMPOTENCIA Y RESPALDO ---
def ya_procesado_webhook(event_id: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_webhooks (
            event_id TEXT PRIMARY KEY,
            processed_at_utc TEXT NOT NULL
        )
    """)
    cursor.execute("SELECT 1 FROM processed_webhooks WHERE event_id = ?", (event_id,))
    existe = cursor.fetchone() is not None
    if not existe:
        cursor.execute(
            "INSERT INTO processed_webhooks (event_id, processed_at_utc) VALUES (?, ?)",
            (event_id, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
    conn.close()
    return existe

def crear_backup_sqlite() -> str:
    """Crea un respaldo consistente en caliente de SQLite WAL."""
    backup_dir = Path("data/backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = backup_dir / f"property_os_{timestamp}.db"

    origen_conn = get_connection()
    destino_conn = sqlite3.connect(str(destino))
    with destino_conn:
        origen_conn.backup(destino_conn)
    destino_conn.close()
    origen_conn.close()
    return str(destino)

def sincronizar_ical_url(ical_url: str, canal: str = "airbnb_ical") -> dict:
    """Descarga un calendario .ics y sincroniza bloqueos nuevos sin duplicar."""
    resp = requests.get(ical_url, timeout=15)
    resp.raise_for_status()
    texto_ics = resp.text

    eventos = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", texto_ics, flags=re.DOTALL)
    importadas = 0
    omitidas = 0

    conn = get_connection()
    cursor = conn.cursor()

    for bloque in eventos:
        uid_m = re.search(r"UID:([^\r\n]+)", bloque)
        dtstart_m = re.search(r"DTSTART(?:;VALUE=DATE)?:(\d{8})", bloque)
        dtend_m = re.search(r"DTEND(?:;VALUE=DATE)?:(\d{8})", bloque)
        summary_m = re.search(r"SUMMARY:([^\r\n]+)", bloque)

        if not (uid_m and dtstart_m and dtend_m):
            continue

        uid = f"ICAL-{uid_m.group(1).strip()[:24]}"
        checkin = datetime.strptime(dtstart_m.group(1), "%Y%m%d").strftime("%Y-%m-%d")
        checkout = datetime.strptime(dtend_m.group(1), "%Y%m%d").strftime("%Y-%m-%d")
        resumen = summary_m.group(1).strip() if summary_m else "Bloqueo iCal"

        disp = verificar_disponibilidad(checkin, checkout)
        if not disp["disponible"]:
            omitidas += 1
            continue

        cursor.execute("""
            INSERT OR IGNORE INTO reservations
            (codigo_reserva, checkin, checkout, precio_total, comision, neto, huesped, status)
            VALUES (?, ?, ?, '0.00', '0.00', '0.00', ?, 'confirmada')
        """, (uid, checkin, checkout, f"{canal}: {resumen}"))
        if cursor.rowcount > 0:
            importadas += 1
        else:
            omitidas += 1

    conn.commit()
    conn.close()
    return {"eventos_leidos": len(eventos), "nuevos_bloqueos": importadas, "ya_existentes_o_traslapados": omitidas}

# --- ENDPOINTS FASTAPI ---
@app.get("/health")
def health_check():
    return {"status": "ok", "property": "Depa Las Villas", "utc": datetime.now(timezone.utc).isoformat()}

@app.post("/webhooks/reserva")
def webhook_reserva(payload: WebhookReservaPayload, x_webhook_secret: Optional[str] = Header(default=None)):
    if x_webhook_secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Firma de webhook inválida")

    # Gate de idempotencia (Paso 10 de Claude: webhooks duplicados no alteran el estado)
    if ya_procesado_webhook(payload.event_id):
        return {"status": "ignored_duplicate", "event_id": payload.event_id}

    disp = verificar_disponibilidad(payload.checkin, payload.checkout)
    if not disp["disponible"] and payload.status != "cancelada":
        registrar_evento(payload.event_id[:8], "WEBHOOK_CONFLICT", payload.codigo_reserva, disp["motivo"])
        return {"status": "conflict_detected", "detalle": disp["motivo"]}

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reservations (codigo_reserva, checkin, checkout, precio_total, comision, neto, huesped, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(codigo_reserva) DO UPDATE SET
            checkin=excluded.checkin,
            checkout=excluded.checkout,
            neto=excluded.neto,
            status=excluded.status
    """, (
        payload.codigo_reserva, payload.checkin, payload.checkout,
        payload.precio_total, payload.comision, payload.neto,
        payload.huesped, payload.status
    ))
    conn.commit()
    conn.close()

    registrar_evento(payload.event_id[:8], "WEBHOOK_RESERVA", payload.codigo_reserva, f"Status: {payload.status}")
    return {"status": "processed", "codigo_reserva": payload.codigo_reserva}

@app.post("/webhooks/mensaje")
def webhook_mensaje(payload: WebhookMensajePayload, x_webhook_secret: Optional[str] = Header(default=None)):
    if x_webhook_secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Firma de webhook inválida")

    if ya_procesado_webhook(payload.event_id):
        return {"status": "ignored_duplicate", "event_id": payload.event_id}

    res = ejecutar_director(payload.mensaje, tarifa_actual_noche=Decimal(str(payload.tarifa_actual_noche)))
    return {"status": "processed", "director_output": res}

@app.post("/jobs/sync-ical")
def job_sync_ical(ical_url: str, canal: str = "airbnb_ical"):
    resultado = sincronizar_ical_url(ical_url, canal=canal)
    return {"status": "synced", **resultado}

@app.post("/jobs/backup")
def job_backup():
    ruta = crear_backup_sqlite()
    return {"status": "backup_created", "archivo": ruta}