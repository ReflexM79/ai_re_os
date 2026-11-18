import os
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from dotenv import load_dotenv
from google import genai

from db import get_connection
from pricing import cargar_politicas, calcular_pisos_tarifa
from calendar_engine import detectar_huecos_huerfanos, listar_reservas_activas
from agent_booking import procesar_mensaje_huesped, llamar_gemini_rapido
from agent_ops import generar_plan_limpieza_y_turnovers, calcular_net_parity
from reconcile import auditar_reservas_vs_pagos

load_dotenv()

def asegurar_tablas_director():
    """Asegura que existan las tablas de eventos y memoria aprendida en SQLite."""
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,
            regla TEXT NOT NULL,
            estado TEXT DEFAULT 'activa'
        )
    """)
    conn.commit()
    conn.close()

def guardar_conocimiento(regla: str):
    """Guarda una regla nueva enseñada por el dueño en SQLite."""
    asegurar_tablas_director()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO knowledge (timestamp_utc, regla, estado) VALUES (?, ?, 'activa')",
        (datetime.now(timezone.utc).isoformat(), regla.strip())
    )
    conn.commit()
    conn.close()

def obtener_conocimiento_activo(limite: int = 15) -> list[str]:
    """Recupera las reglas activas aprendidas para inyectarlas al cerebro del Director."""
    asegurar_tablas_director()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, regla FROM knowledge WHERE estado = 'activa' ORDER BY id DESC LIMIT ?", (limite,))
    filas = cursor.fetchall()
    conn.close()
    return [f"[Regla #{r['id']}] {r['regla']}" for r in filas]

def registrar_evento(trace_id: str, ruta: str, entrada: str, salida_resumen: str):
    """Guarda cada decisión del Director en una tabla append-only en SQLite."""
    asegurar_tablas_director()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO events (trace_id, timestamp_utc, ruta_ejecutada, entrada, salida_resumen) VALUES (?, ?, ?, ?, ?)",
        (trace_id, datetime.now(timezone.utc).isoformat(), ruta, entrada, salida_resumen)
    )
    conn.commit()
    conn.close()

def enrutar_por_reglas(instruccion: str) -> str:
    """Router determinista: clasifica la intención sin gastar llamadas LLM innecesarias."""
    texto = instruccion.lower()
    if any(p in texto for p in ["aprende", "recuerda que", "guarda esta regla", "nueva regla", "memoriza"]):
        return "LEARN_RULE"
    if any(p in texto for p in ["huésped", "huesped", "mensaje del", "pide descuento", "me puedes hacer un", "me haces un", "late check", "early check"]):
        return "GUEST_REQUEST"
    if any(p in texto for p in ["limpieza", "turnover", "back-to-back", "paridad", "vrbo", "booking.com"]):
        return "OPERATIONS_SYNC"
    if any(p in texto for p in ["concili", "payout", "auditor", "por cobrar", "depositado"]):
        return "AUDIT_FINANCE"
    return "STRATEGIC_DIRECTOR"

def ejecutar_director(
    instruccion: str,
    tarifa_actual_noche: Decimal = Decimal("1300.00"),
    historial_chat: list[dict] | None = None
) -> dict:
    """
    Orquestador central del AI Property Management OS.
    Funciona como chat conversacional con memoria persistente y acceso a herramientas reales.
    """
    trace_id = str(uuid.uuid4())[:8]
    ruta = enrutar_por_reglas(instruccion)
    politicas = cargar_politicas()
    nombre_prop = politicas.get("property_name", "Depa Las Villas")

    if ruta == "LEARN_RULE":
        guardar_conocimiento(instruccion)
        mensaje_chat = (
            f"✅ **Regla guardada en mi memoria permanente** para *{nombre_prop}*:\n\n"
            f"> *\"{instruccion}\"*\n\n"
            "La tomaré en cuenta automáticamente en mis próximos análisis y recomendaciones."
        )
        resultado = {"analisis_ejecutivo": mensaje_chat, "datos_base_utilizados": {"regla_guardada": instruccion}}
        resumen = "Nueva regla aprendida en SQLite."

    elif ruta == "GUEST_REQUEST":
        res_bk = procesar_mensaje_huesped(instruccion, tarifa_actual_noche=tarifa_actual_noche)
        aud = res_bk["auditoria_matematica"]
        mensaje_chat = (
            f"Analicé la solicitud con el motor de negociación y calendario:\n\n"
            f"* **Decisión:** `{aud['decision_sistema']}`\n"
            f"* **Equilibrio (ADR):** `${aud['adr_objetivo_equilibrio']}` | **Piso marginal:** `${aud['piso_marginal_absoluto']}` | **Descuento máx. seguro:** `{aud['descuento_max_permitido_pct']}%`\n\n"
            f"**Borrador listo para copiar (Modo Sombra L0):**\n```text\n{res_bk['borrador_respuesta']}\n```"
        )
        resultado = {"analisis_ejecutivo": mensaje_chat, "datos_base_utilizados": res_bk}
        resumen = f"Decisión Booking: {aud['decision_sistema']}"

    elif ruta == "OPERATIONS_SYNC":
        ordenes = generar_plan_limpieza_y_turnovers()
        paridad = calcular_net_parity(tarifa_actual_noche)
        mensaje_chat = (
            f"Revisé operaciones y paridad multicanal sobre una meta neta de **${tarifa_actual_noche} MXN**:\n\n"
            f"* **Órdenes de limpieza activas:** {len(ordenes)} programadas.\n"
            f"* **Paridad de precios públicos para recibir lo mismo neto:**\n"
            f"  * Directo: `${paridad['directo']['precio_publico_mxn']}`\n"
            f"  * Airbnb (18.56%): `${paridad['airbnb']['precio_publico_mxn']}`\n"
            f"  * Booking.com (15%): `${paridad['booking']['precio_publico_mxn']}`\n"
            f"  * Vrbo (8%): `${paridad['vrbo']['precio_publico_mxn']}`"
        )
        resultado = {
            "analisis_ejecutivo": mensaje_chat,
            "datos_base_utilizados": {"ordenes_limpieza": ordenes, "paridad_canales": paridad}
        }
        resumen = f"Generadas {len(ordenes)} órdenes de limpieza y paridad multicanal."

    elif ruta == "AUDIT_FINANCE":
        auditoria = auditar_reservas_vs_pagos()
        r_fin = auditoria["resumen"]
        mensaje_chat = (
            f"Aquí está el estado financiero actual en SQLite:\n\n"
            f"* **Reservas activas:** {r_fin['total_reservas_activas']}\n"
            f"* **Neto esperado:** `${r_fin['total_neto_esperado_mxn']} MXN`\n"
            f"* **Depositado en banco:** `${r_fin['total_depositado_mxn']} MXN`\n"
            f"* **Saldo por cobrar:** `${r_fin['saldo_por_cobrar_mxn']} MXN`"
        )
        resultado = {"analisis_ejecutivo": mensaje_chat, "datos_base_utilizados": auditoria}
        resumen = f"Saldo por cobrar: ${r_fin['saldo_por_cobrar_mxn']} MXN"

    else:
        api_key = os.environ["GEMINI_API_KEY"]
        modelo_principal = os.environ.get("MODEL_ROUTER", "gemini-4-hydrogen")
        modelos_fallback = list(dict.fromkeys([modelo_principal, "gemini-3.5-flash-lite", "gemini-3.6-flash"]))
        cliente = genai.Client(api_key=api_key)

        pisos = calcular_pisos_tarifa(noches=2)
        huecos = detectar_huecos_huerfanos(max_noches_hueco=2)
        reservas = listar_reservas_activas()
        conc = auditar_reservas_vs_pagos()["resumen"]
        reglas_aprendidas = obtener_conocimiento_activo()

        bloque_memoria = "\n".join(reglas_aprendidas) if reglas_aprendidas else "Ninguna regla adicional registrada aún."
        bloque_historial = ""
        if historial_chat:
            ultimos = historial_chat[-6:]
            bloque_historial = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in ultimos])

        contexto_propiedad = (
            f"Propiedad: {nombre_prop} (Nuevo León, México).\n"
            f"Tarifa lista actual: ${tarifa_actual_noche} MXN | Equilibrio ADR (2 noches): ${pisos['adr_objetivo_noche']} | "
            f"Piso marginal: ${pisos['piso_marginal_noche']}.\n"
            f"Reservas activas ({len(reservas)}): {reservas}\n"
            f"Resumen financiero: {conc}\n"
            f"Días huérfanos detectados: {huecos}\n\n"
            f"MEMORIA Y REGLAS APRENDIDAS DEL DUEÑO:\n{bloque_memoria}\n\n"
            f"HISTORIAL RECIENTE DE CONVERSACIÓN:\n{bloque_historial}"
        )

        resp = llamar_gemini_rapido(
            cliente,
            modelos_fallback,
            contents=f"Contexto operativo real:\n{contexto_propiedad}\n\nMensaje actual del dueño: {instruccion}",
            system_instruction=(
                f"Eres el Agente Director Inmobiliario 360° de {nombre_prop} en Nuevo León, México. "
                "Habla como un socio experto en bienes raíces, hospitality e inversiones: directo, conversacional, estratégico y sin relleno. "
                "Tienes acceso en tiempo real a los datos operativos, calendario, pisos financieros y memoria del dueño. "
                "Basa tus cálculos estrictamente en los números reales proporcionados."
            )
        )
        resultado = {
            "analisis_ejecutivo": resp.text.strip(),
            "datos_base_utilizados": {
                "pisos_tarifa": {k: str(v) for k, v in pisos.items()},
                "huecos_huerfanos": huecos,
                "reglas_activas": reglas_aprendidas
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