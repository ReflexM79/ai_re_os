import os
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from dotenv import load_dotenv
from google import genai
from google.genai import types

from db import get_connection
from pricing import cargar_politicas, calcular_pisos_tarifa
from calendar_engine import detectar_huecos_huerfanos, listar_reservas_activas
from agent_booking import procesar_mensaje_huesped, llamar_gemini_rapido
from agent_ops import generar_plan_limpieza_y_turnovers, calcular_net_parity
from reconcile import auditar_reservas_vs_pagos

load_dotenv()

def registrar_evento(trace_id: str, ruta: str, entrada: str, salida_resumen: str):
    """Guarda cada decisión del Director en una tabla append-only en SQLite."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL,
            timestamp_utc TEXT NOT NULL,
            ruta_ejecutada TEXT NOT NULL,
            entrada TEXT NOT NULL,
            salida_resumen TEXT NOT NULL
        )
    """)
    cursor.execute(
        "INSERT INTO events (trace_id, timestamp_utc, ruta_ejecutada, entrada, salida_resumen) VALUES (?, ?, ?, ?, ?)",
        (trace_id, datetime.now(timezone.utc).isoformat(), ruta, entrada, salida_resumen)
    )
    conn.commit()
    conn.close()

def enrutar_por_reglas(instruccion: str) -> str:
    """Router determinista: clasifica la intención sin gastar llamadas LLM innecesarias."""
    texto = instruccion.lower()
    if any(p in texto for p in ["huésped", "huesped", "mensaje", "descuento", "reservar", "check-in", "checkout", "late"]):
        return "GUEST_REQUEST"
    if any(p in texto for p in ["limpieza", "turnover", "back-to-back", "operaciones", "canal", "booking", "vrbo"]):
        return "OPERATIONS_SYNC"
    if any(p in texto for p in ["pago", "payout", "concili", "auditor", "banco", "cobrar", "dinero"]):
        return "AUDIT_FINANCE"
    return "STRATEGIC_DIRECTOR"

def ejecutar_director(instruccion: str, tarifa_actual_noche: Decimal = Decimal("1300.00")) -> dict:
    """
    Orquestador central del AI Property Management OS.
    Coordina los motores deterministas y los skills LLM con trazabilidad completa.
    """
    trace_id = str(uuid.uuid4())[:8]
    ruta = enrutar_por_reglas(instruccion)
    politicas = cargar_politicas()

    if ruta == "GUEST_REQUEST":
        resultado = procesar_mensaje_huesped(instruccion, tarifa_actual_noche=tarifa_actual_noche)
        resumen = f"Decisión Booking: {resultado['auditoria_matematica']['decision_sistema']}"

    elif ruta == "OPERATIONS_SYNC":
        ordenes = generar_plan_limpieza_y_turnovers()
        paridad = calcular_net_parity(tarifa_actual_noche)
        resultado = {
            "ordenes_limpieza": ordenes,
            "paridad_canales_sobre_tarifa_base": paridad
        }
        resumen = f"Generadas {len(ordenes)} órdenes de limpieza y paridad multicanal."

    elif ruta == "AUDIT_FINANCE":
        auditoria = auditar_reservas_vs_pagos()
        resultado = auditoria
        resumen = f"Saldo por cobrar: ${auditoria['resumen']['saldo_por_cobrar_mxn']} MXN"

    else:
        # Consulta estratégica general: cruza datos reales de la propiedad y usa Gemini Director
        api_key = os.environ["GEMINI_API_KEY"]
        modelo_principal = os.environ.get("MODEL_ROUTER", "gemini-4-hydrogen")
        modelos_fallback = list(dict.fromkeys([modelo_principal, "gemini-3.5-flash-lite", "gemini-3.6-flash"]))
        cliente = genai.Client(api_key=api_key)

        pisos = calcular_pisos_tarifa(noches=2)
        huecos = detectar_huecos_huerfanos(max_noches_hueco=2)
        conc = auditar_reservas_vs_pagos()["resumen"]

        contexto_propiedad = (
            f"Propiedad: {politicas.get('property_name', 'Depa Las Villas')} (Monterrey).\n"
            f"Tarifa lista actual: ${tarifa_actual_noche} MXN | Equilibrio (2 noches): ${pisos['adr_objetivo_noche']} | "
            f"Piso marginal: ${pisos['piso_marginal_noche']}.\n"
            f"Reservas activas: {conc['total_reservas_activas']} | Neto esperado: ${conc['total_neto_esperado_mxn']}.\n"
            f"Días huérfanos detectados: {huecos}"
        )

        resp = llamar_gemini_rapido(
            cliente,
            modelos_fallback,
            contents=f"Contexto operativo real:\n{contexto_propiedad}\n\nConsulta del dueño: {instruccion}",
            system_instruction=(
                "Eres el Agente Director Inmobiliario 360° de Depa Las Villas en Monterrey. "
                "Responde con rigor financiero, directo al grano y basándote estrictamente en los datos reales proporcionados."
            )
        )
        resultado = {
            "analisis_ejecutivo": resp.text.strip(),
            "datos_base_utilizados": {
                "pisos_tarifa": {k: str(v) for k, v in pisos.items()},
                "huecos_huerfanos": huecos,
                "resumen_financiero": conc
            }
        }
        resumen = "Dictamen estratégico del Director emitido."

    registrar_evento(trace_id, ruta, instruccion, resumen)

    return {
        "trace_id": trace_id,
        "ruta_activada": ruta,
        "resumen_auditoria": resumen,
        "resultado": resultado
    }

if __name__ == "__main__":
    print("--- PRUEBA DEL AGENTE DIRECTOR (ORQUESTADOR + TRAZA SQLITE) ---\n")
    consulta = "Dame un resumen ejecutivo de cómo estamos hoy en Depa Las Villas, qué huecos tenemos y qué tarifa me recomiendas para llenarlos."
    salida = ejecutar_director(consulta, tarifa_actual_noche=Decimal("1300.00"))
    print(json.dumps(salida, indent=2, ensure_ascii=False))