import streamlit as st
from decimal import Decimal
import pandas as pd

from db import get_connection
from pricing import cargar_politicas, calcular_pago_neto
from calendar_engine import listar_reservas_activas, detectar_huecos_huerfanos, verificar_disponibilidad
from agent_booking import procesar_mensaje_huesped
from agent_ops import generar_plan_limpieza_y_turnovers, calcular_net_parity
from agent_auditor import analizar_evidencia_danos
from agent_listing import generar_anuncios_y_geo
from director import ejecutar_director, obtener_conocimiento_activo
from reconcile import auditar_reservas_vs_pagos

st.set_page_config(page_title="Director Inmobiliario 360° — AI OS", page_icon="🧠", layout="wide")

politicas = cargar_politicas()
nombre_propiedad = politicas.get("property_name", "Propiedad Activa")

# --- BARRA LATERAL (Configuración + Herramientas Avanzadas) ---
with st.sidebar:
    st.title(f"🏢 {nombre_propiedad}")
    st.caption("Nuevo León • Modo Sombra (L0)")

    modo_vista = st.radio(
        "Modo de trabajo:",
        [
            "🧠 Chat con Director 360°",
            "💬 Simulador Booking",
            "📅 Calendario y Huecos",
            "🧹 Operaciones & Paridad",
            "🛡️ Auditor AirCover (L3)",
            "📣 Listing & GEO",
            "💰 Finanzas & RFC",
            "📜 Bitácora y Memoria"
        ],
        index=0
    )

    st.divider()
    tarifa_global = st.number_input(
        "Tarifa Lista Base (MXN/noche):",
        min_value=300.0,
        value=1300.0,
        step=50.0
    )

    if st.button("🗑️ Limpiar historial de chat", use_container_width=True):
        st.session_state.mensajes_chat = []
        st.rerun()

# ==============================================================================
# VISTA PRINCIPAL: CHAT PURO CON EL DIRECTOR 360° Y TODOS SUS SUPERPODERES
# ==============================================================================
if modo_vista == "🧠 Chat con Director 360°":
    st.title("🧠 Director Inmobiliario 360°")
    st.caption("Conversa libremente: analiza propiedades, negocia con huéspedes, consulta tu calendario o enséñame nuevas reglas.")

    if "mensajes_chat" not in st.session_state:
        st.session_state.mensajes_chat = [
            {
                "role": "assistant",
                "content": (
                    f"¡Hola! Soy tu **Director Inmobiliario 360°** para **{nombre_propiedad}**.\n\n"
                    "Tengo conectados en tiempo real tu calendario de Airbnb, tu calculadora fiscal con RFC, "
                    "tu motor de negociación con límites y mi memoria persistente. ¿Qué revisamos hoy?"
                ),
                "meta": None
            }
        ]

    # Botones rápidos de sugerencia si la conversación apenas inicia
    if len(st.session_state.mensajes_chat) == 1:
        c1, c2, c3 = st.columns(3)
        sugerencia_1 = "Dame un resumen ejecutivo de cómo estamos hoy, qué huecos tenemos y qué tarifa recomiendas."
        sugerencia_2 = "Un huésped pide 3 noches del 2026-12-23 al 2026-12-26 con 18% de descuento. ¿Qué le respondo?"
        sugerencia_3 = "Aprende que en fines de semana de concierto o festival en Monterrey no damos ningún descuento."

        prompt_rapido = None
        if c1.button("📊 Diagnóstico y huecos hoy", use_container_width=True):
            prompt_rapido = sugerencia_1
        if c2.button("💬 Probar negociación huésped", use_container_width=True):
            prompt_rapido = sugerencia_2
        if c3.button("🧠 Enseñarle una regla nueva", use_container_width=True):
            prompt_rapido = sugerencia_3
    else:
        prompt_rapido = None

    # Mostrar historial de conversación
    for msg in st.session_state.mensajes_chat:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("meta"):
                with st.expander(f"🔍 Superpoderes activados ({msg['meta']['ruta']} • Trace: {msg['meta']['trace_id']})"):
                    st.json(msg["meta"]["datos"])

    # Entrada de chat libre
    entrada_usuario = st.chat_input("Escribe aquí tu pregunta, mensaje de huésped o regla para que aprenda...")
    mensaje_final = prompt_rapido or entrada_usuario

    if mensaje_final:
        st.session_state.mensajes_chat.append({"role": "user", "content": mensaje_final, "meta": None})
        with st.chat_message("user"):
            st.markdown(mensaje_final)

        with st.chat_message("assistant"):
            with st.spinner("Pensando y consultando motores..."):
                out = ejecutar_director(
                    mensaje_final,
                    tarifa_actual_noche=Decimal(str(tarifa_global)),
                    historial_chat=st.session_state.mensajes_chat
                )
            res = out["resultado"]
            respuesta_texto = res.get("analisis_ejecutivo", str(res))
            st.markdown(respuesta_texto)

            meta_info = {
                "trace_id": out["trace_id"],
                "ruta": out["ruta_activada"],
                "datos": res.get("datos_base_utilizados", res)
            }
            with st.expander(f"🔍 Superpoderes activados ({meta_info['ruta']} • Trace: {meta_info['trace_id']})"):
                st.json(meta_info["datos"])

        st.session_state.mensajes_chat.append({
            "role": "assistant",
            "content": respuesta_texto,
            "meta": meta_info
        })
        st.rerun()

# ==============================================================================
# HERRAMIENTAS TÉCNICAS AVANZADAS (Accesibles desde el menú lateral)
# ==============================================================================
elif modo_vista == "💬 Simulador Booking":
    st.subheader("Asistente de Reservas y Negociación con Límites")
    c1, c2 = st.columns([2, 1])
    with c1:
        msg_huesped = st.text_area(
            "Mensaje del huésped (Airbnb / WhatsApp):",
            value="Hola! Me interesa quedarme 3 noches del 2026-12-23 al 2026-12-26. ¿Me podrías hacer un 18% de descuento?",
            height=120
        )
    with c2:
        tarifa_bk = st.number_input("Tarifa Lista Actual (MXN):", min_value=300.0, value=float(tarifa_global), step=50.0)
        btn_bk = st.button("Analizar y Redactar Respuesta", type="primary", use_container_width=True)

    if btn_bk and msg_huesped.strip():
        with st.spinner("Validando calendario, márgenes y redactando..."):
            res_bk = procesar_mensaje_huesped(msg_huesped, tarifa_actual_noche=Decimal(str(tarifa_bk)))
        aud = res_bk["auditoria_matematica"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Decisión", aud["decision_sistema"])
        m2.metric("Equilibrio (ADR)", f"${aud['adr_objetivo_equilibrio']}")
        m3.metric("Piso Marginal", f"${aud['piso_marginal_absoluto']}")
        m4.metric("Descuento Máx. Seguro", f"{aud['descuento_max_permitido_pct']}%")
        st.success("**Borrador listo para copiar (Modo Sombra L0):**")
        st.code(res_bk["borrador_respuesta"], language=None)

elif modo_vista == "📅 Calendario y Huecos":
    st.subheader("Disponibilidad y Radar de Días Huérfanos")
    cv1, cv2, cv3 = st.columns(3)
    with cv1:
        f_in = st.date_input("Check-in")
    with cv2:
        f_out = st.date_input("Check-out")
    with cv3:
        st.write("")
        st.write("")
        if st.button("Verificar Fechas", use_container_width=True):
            disp = verificar_disponibilidad(str(f_in), str(f_out))
            if disp["disponible"]:
                st.success(f"✅ Disponible ({disp['noches']} noches): {disp['motivo']}")
            else:
                st.error(f"⛔ No disponible: {disp['motivo']}")

    st.divider()
    col_r, col_h = st.columns([2, 1])
    with col_r:
        st.markdown("**Reservas Activas (SQLite WAL)**")
        reservas = listar_reservas_activas()
        if reservas:
            st.dataframe(pd.DataFrame(reservas), use_container_width=True, hide_index=True)
    with col_h:
        st.markdown("**⚠️ Días Huérfanos (<= 2 noches)**")
        huecos = detectar_huecos_huerfanos(max_noches_hueco=2)
        for h in huecos:
            st.warning(f"**{h['inicio_libre']} al {h['fin_libre']}** ({h['noches_huerfanas']} noches)\n\nEntre {h['entre_reservas']}.")

elif modo_vista == "🧹 Operaciones & Paridad":
    st.subheader("Órdenes de Limpieza, Back-to-Backs y Paridad Multicanal")
    neto_meta = st.number_input("Ingreso Neto Deseado por Noche en Banco (MXN):", min_value=300.0, value=1000.0, step=50.0)
    paridad = calcular_net_parity(Decimal(str(neto_meta)))
    cols_p = st.columns(4)
    for idx, (canal, datos) in enumerate(paridad.items()):
        cols_p[idx].metric(
            label=canal.replace("_", " ").upper(),
            value=f"${datos['precio_publico_mxn']} MXN",
            delta=f"Neto: ${datos['neto_recibido_mxn']} (-{datos['comision_efectiva_pct']}%)"
        )
    st.divider()
    ordenes = generar_plan_limpieza_y_turnovers()
    if ordenes:
        st.dataframe(pd.DataFrame(ordenes), use_container_width=True, hide_index=True)

elif modo_vista == "🛡️ Auditor AirCover (L3)":
    st.subheader("Peritaje de Daños y Relojes Legales AirCover (Nivel L3)")
    ca1, ca2 = st.columns(2)
    with ca1:
        cod_res = st.text_input("Código de Reserva:", value="HM001")
        f_out_claim = st.text_input("Fecha de Check-out (YYYY-MM-DD):", value="2026-12-20")
    with ca2:
        nota_limp = st.text_area(
            "Reporte del equipo de limpieza:",
            value="Toalla de baño blanca con mancha permanente de tinte y un vaso de cristal roto en cocina."
        )
    if st.button("Evaluar Daños y Calcular Relojes Legales", type="primary"):
        with st.spinner("Calculando corte estricto y redactando expediente L3..."):
            rep_claim = analizar_evidencia_danos(cod_res, f_out_claim, nota_limpieza=nota_limp)
        rel = rep_claim["relojes_legales_aircover"]
        st.warning(f"⏰ **Corte estricto:** `{rel['corte_estricto_reporte']}` — {rel['motivo_corte_estricto']}")
        st.metric("Monto Total Estimado del Reclamo", f"${rep_claim['monto_total_reclamo_mxn']} MXN")
        st.info(rep_claim["accion_permitida"])
        st.code(rep_claim["evaluacion_pericial"]["borrador_reclamo_resolucion"], language=None)

elif modo_vista == "📣 Listing & GEO":
    st.subheader("Generador Multicanal + Optimización GEO (Cero Alucinaciones)")
    perfil_propiedad = politicas.get("property_profile", {
        "property_id": politicas.get("property_id", "propiedad-nl"),
        "municipio": "Nuevo León, México",
    })
    no_tiene = perfil_propiedad.get("amenidades_prohibidas", [])
    feedback_txt = st.text_area(
        "Reseñas o preguntas frecuentes de huéspedes (opcional):",
        value="",
        placeholder="Ej. El internet vuela para hacer home office..."
    )
    if st.button("Generar Copys Validados (Airbnb / Booking / Vrbo)", type="primary"):
        lineas = [l.strip() for l in feedback_txt.splitlines() if l.strip()]
        with st.spinner("Generando copys y auditando amenidades..."):
            res_geo = generar_anuncios_y_geo(perfil_propiedad, lineas, no_tiene)
        st.success(f"**Claim Checker:** {res_geo['gate_claim_checker']} | **Longitudes:** {res_geo['longitudes_validadas']}")
        st.json(res_geo["resultado"])

elif modo_vista == "💰 Finanzas & RFC":
    st.subheader("Conciliación Bancaria y Calculadora Fiscal RFC")
    conc = auditar_reservas_vs_pagos()
    resumen = conc["resumen"]
    f1, f2, f3, f4 = st.columns(4)
    f1.metric("Reservas Activas", resumen["total_reservas_activas"])
    f2.metric("Neto Esperado", f"${resumen['total_neto_esperado_mxn']} MXN")
    f3.metric("Depositado", f"${resumen['total_depositado_mxn']} MXN")
    f4.metric("Por Cobrar", f"${resumen['saldo_por_cobrar_mxn']} MXN")
    if conc["detalle"]:
        st.dataframe(pd.DataFrame(conc["detalle"]), use_container_width=True, hide_index=True)

    st.divider()
    sub_sim = st.number_input("Simular Subtotal Hospedaje + Limpieza (MXN):", min_value=100.0, value=3174.08, step=100.0)
    desglose = calcular_pago_neto(Decimal(str(sub_sim)))
    st.success(
        f"Subtotal: ${desglose['subtotal_hospedaje']} | Comisión (-18.56%): -${desglose['comision_airbnb_total']} | "
        f"IVA Ret (-8%): -${desglose['iva_retenido']} | ISR Ret (-4%): -${desglose['isr_retenido']} ➡️ "
        f"**Depósito Neto Real: ${desglose['tu_ganas_neto']} MXN**"
    )

elif modo_vista == "📜 Bitácora y Memoria":
    st.subheader("Reglas Aprendidas por el Director (`knowledge` en SQLite)")
    reglas = obtener_conocimiento_activo(limite=50)
    if reglas:
        for r_txt in reglas:
            st.info(r_txt)
    else:
        st.caption("Aún no le has enseñado reglas en el chat. Dile 'Aprende que...' en el chat principal.")

    st.divider()
    st.subheader("Registro Append-Only de Decisiones (`events` en SQLite)")
    conn = get_connection()
    try:
        df_events = pd.read_sql_query("SELECT * FROM events ORDER BY id DESC LIMIT 50", conn)
        st.dataframe(df_events, use_container_width=True, hide_index=True)
    except Exception:
        st.info("Aún no hay eventos registrados.")
    finally:
        conn.close()