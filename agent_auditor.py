import os
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, Optional
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from db import get_connection
from calendar_engine import listar_reservas_activas

load_dotenv()

class DanoDetectado(BaseModel):
    articulo: str
    descripcion_objetiva: str
    severidad: Literal["leve", "moderada", "grave"]
    confianza_pct: float = Field(ge=0.0, le=100.0)
    costo_reposicion_estimado_mxn: float = Field(ge=0.0)

class ReporteInspeccionVisual(BaseModel):
    hay_danos: bool
    danos: list[DanoDetectado]
    borrador_reclamo_resolucion: str
    requiere_aprobacion_humana: bool = True

def calcular_relojes_aircover(codigo_reserva: str, fecha_checkout_str: str) -> dict:
    """
    Paso 8b: Máquina de estados de reclamos AirCover con los 4 relojes legales.
    Aplica la regla estricta: vence lo que ocurra primero (14 días o siguiente check-in).
    """
    checkout_dt = datetime.strptime(fecha_checkout_str.strip(), "%Y-%m-%d")
    limite_14_dias = checkout_dt + timedelta(days=14)
    limite_30_dias_aircover = checkout_dt + timedelta(days=30)

    # Buscar si hay un siguiente check-in después de este checkout
    reservas = [r for r in listar_reservas_activas() if r["status"] != "cancelada"]
    siguientes = [
        datetime.strptime(r["checkin"], "%Y-%m-%d")
        for r in reservas
        if datetime.strptime(r["checkin"], "%Y-%m-%d") >= checkout_dt and r["codigo_reserva"] != codigo_reserva
    ]
    siguiente_checkin = min(siguientes) if siguientes else None

    # Corte estricto: antes del siguiente check-in o 14 días, lo que ocurra primero
    corte_estricto = limite_14_dias
    motivo_corte = "Plazo máximo 14 días post-checkout (Centro de Resoluciones)"
    if siguiente_checkin and siguiente_checkin < limite_14_dias:
        corte_estricto = siguiente_checkin
        motivo_corte = f"CRÍTICO: Antes del siguiente check-in ({siguiente_checkin.strftime('%Y-%m-%d')})"

    ahora = datetime.now()
    horas_restantes = round((corte_estricto - ahora).total_seconds() / 3600, 1)

    return {
        "codigo_reserva": codigo_reserva,
        "checkout": fecha_checkout_str,
        "corte_estricto_reporte": corte_estricto.strftime("%Y-%m-%d %H:%M"),
        "motivo_corte_estricto": motivo_corte,
        "ventana_respuesta_huesped": "24 horas tras enviar solicitud",
        "limite_formal_aircover_30d": limite_30_dias_aircover.strftime("%Y-%m-%d"),
        "horas_restantes_para_reportar": horas_restantes,
        "estado_reloj": "VENCIDO" if horas_restantes <= 0 else "EN_TIEMPO_ACCION_REQUERIDA",
        "nivel_autonomia": "L3_APROBACION_HUMANA_OBLIGATORIA"
    }

def registrar_reclamo_db(codigo_reserva: str, corte_estricto: str, monto_mxn: Decimal, resumen: str):
    """Guarda el expediente del reclamo en SQLite en estado 'pendiente_aprobacion_humana'."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_reserva TEXT NOT NULL,
            corte_estricto TEXT NOT NULL,
            monto_estimado_mxn TEXT NOT NULL,
            resumen_danos TEXT NOT NULL,
            estado TEXT DEFAULT 'pendiente_aprobacion_humana',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute(
        "INSERT INTO claims (codigo_reserva, corte_estricto, monto_estimado_mxn, resumen_danos) VALUES (?, ?, ?, ?)",
        (codigo_reserva, corte_estricto, str(monto_mxn), resumen)
    )
    conn.commit()
    conn.close()

def analizar_evidencia_danos(
    codigo_reserva: str,
    fecha_checkout: str,
    ruta_foto_antes: Optional[str] = None,
    ruta_foto_despues: Optional[str] = None,
    nota_limpieza: str = ""
) -> dict:
    """
    Paso 8c: Analiza evidencia post-checkout (fotos antes/después y/o reporte de limpieza),
    calcula los relojes legales de AirCover y prepara expediente L3 (nunca envía solo).
    """
    relojes = calcular_relojes_aircover(codigo_reserva, fecha_checkout)

    api_key = os.environ["GEMINI_API_KEY"]
    modelo = os.environ.get("MODEL_ROUTER", "gemini-3.5-flash")
    cliente = genai.Client(api_key=api_key)

    contenidos = [
        f"Reserva: {codigo_reserva} | Checkout: {fecha_checkout}\n"
        f"Reporte del equipo de limpieza: {nota_limpieza or 'Sin notas adicionales.'}\n"
        "Evalúa objetivamente si existen daños atribuibles al huésped (no desgaste normal). "
        "Si hay fotos adjuntas, compara el estado ANTES vs DESPUÉS."
    ]

    for etiqueta, ruta in [("FOTO ANTES (Referencia):", ruta_foto_antes), ("FOTO DESPUÉS (Post-checkout):", ruta_foto_despues)]:
        if ruta and Path(ruta).exists():
            contenidos.append(etiqueta)
            contenidos.append(types.Part.from_bytes(data=Path(ruta).read_bytes(), mime_type="image/jpeg"))

    resp = cliente.models.generate_content(
        model=modelo,
        contents=contenidos,
        config=types.GenerateContentConfig(
            system_instruction=(
                "Eres un perito auditor de seguros AirCover para propiedades en Monterrey. "
                "Sé estrictamente objetivo: una falsa acusación daña la reputación del anfitrión. "
                "Distingue desgaste normal de daños reales y redacta un reclamo formal neutral para el Centro de Resoluciones."
            ),
            response_mime_type="application/json",
            response_schema=ReporteInspeccionVisual,
            temperature=0.2,
        ),
    )
    reporte: ReporteInspeccionVisual = resp.parsed
    total_reclamo = Decimal(str(sum(d.costo_reposicion_estimado_mxn for d in reporte.danos))).quantize(Decimal("0.01"))

    if reporte.hay_danos:
        resumen_txt = "; ".join(f"{d.articulo}: {d.descripcion_objetiva} (${d.costo_reposicion_estimado_mxn})" for d in reporte.danos)
        registrar_reclamo_db(codigo_reserva, relojes["corte_estricto_reporte"], total_reclamo, resumen_txt)

    return {
        "relojes_legales_aircover": relojes,
        "evaluacion_pericial": reporte.model_dump(),
        "monto_total_reclamo_mxn": str(total_reclamo),
        "accion_permitida": "BORRADOR_GUARDADO_EN_DB — Requiere aprobación manual del dueño antes de enviar a Airbnb (Nivel L3)."
    }

if __name__ == "__main__":
    print("--- PRUEBA PASO 8b/8c: AUDITOR DE RECLAMOS Y RELOJES AIRCOVER ---\n")
    # Simulamos un hallazgo post-checkout de HM001 (sale 2026-12-20 y el siguiente huésped entra 2026-12-22)
    resultado = analizar_evidencia_danos(
        codigo_reserva="HM001",
        fecha_checkout="2026-12-20",
        nota_limpieza="Al entrar a limpiar encontramos una toalla de baño blanca con mancha permanente de tinte de cabello y un vaso de cristal roto en la cocina."
    )
    print(json.dumps(resultado, indent=2, ensure_ascii=False))