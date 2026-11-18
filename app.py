import streamlit as st
from decimal import Decimal
import pandas as pd

from db import get_connection
from pricing import cargar_politicas, calcular_pago_neto, calcular_pisos_tarifa
from calendar_engine import listar_reservas_activas, detectar_huecos_huerfanos, verificar_disponibilidad
from agent_booking import procesar_mensaje_huesped
from agent_ops import generar_plan_limpieza_y_turnovers, calcular_net_parity
from agent_auditor import analizar_evidencia_danos
from agent_listing import generar_anuncios_y_geo
from director import ejecutar_director
from reconcile import auditar_reservas_vs_pagos

st.set_page_config(page_title="Depa Las Villas - AI Property OS", page_icon="🏢", layout="wide")

politicas = cargar_politicas()
st.title(f"🏢 {politicas.get('property_name', 'Depa Las Villas')} — AI Property Management OS")
st.caption("Monterrey, N.L. • Arquitectura Multi-Agente + Motores Deterministas + SQLite WAL (Modo Sombra L0)")

tabs = st.tabs([
    "🧠 Director 360°",
    "💬 Booking & Negociación",
    "📅 Calendario y Huecos",
    "🧹 Operaciones & Paridad",
    "🛡️ Auditor AirCover (L3)",
    "📣 Listing & GEO",
    "💰 Finanzas & RFC",
    "📜 Bitácora (Events)"
])

# --- TAB 1: DIRECTOR 360° ---
with tabs[0]:
    st.subheader("Orquestador Central y Consultor Estratégico")
    consulta_dir = st.text_area(
        "Pídele cualquier análisis o acción al Director:",
        value="Dame un resumen ejecutivo de cómo estamos hoy en Depa Las Villas, qué huecos tenemos y qué tarifa me recomiendas para llenarlos.",
        height=110
    )
    tarifa_ref = st.number_input("Tarifa Lista de Referencia (MXN):", min_value=300.0, value=1300.0, step=50.0, key="dir_tarifa")
    if st.button("Ejecutar Director", type="primary"):
        with st.spinner("Enrutando y consultando motores..."):
            out = ejecutar_director(consulta_dir, tarifa_actual_noche=Decimal(str(tarifa_ref)))
        st.info(f"**Trace ID:** `{out['trace_id']}` | **Ruta activada:** `{out['ruta_activada']}` | {out['resumen_auditoria']}")
        res = out["resultado"]
        if isinstance(res, dict) and "analisis_ejecutivo" in res:
            st.markdown(res["analisis_ejecutivo"])
            with st.expander("Datos base verificados"):
                st.json(res["datos_base_utilizados"])
        else:
            st.json(res)

# --- TAB 2: AGENTE DE BOOKING ---
with tabs[1]:
    st.subheader("Asistente de Reservas y Negociación con Límites")
    c1, c2 = st.columns([2, 1])
    with c1:
        msg_huesped = st.text_area(
            "Mensaje del huésped (Airbnb / WhatsApp):",
            value="Hola! Me interesa quedarme 3 noches del 2026-12-23 al 2026-12-26. ¿Me podrías hacer un 18% de descuento?",
            height=120
        )
    with c2:
        tarifa_bk = st.number_input("Tarifa Lista Actual (MXN):", min_value=300.0, value=1300.0, step=50.0, key="bk_tarifa")
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

# --- TAB 3: CALENDARIO Y DÍAS HUÉRFANOS ---
with tabs[2]:
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

# --- TAB 4: OPERACIONES & NET-PARITY ---
with tabs[3]:
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
    st.markdown("**Cronograma de Limpieza y Alertas Turnovers**")
    ordenes = generar_plan_limpieza_y_turnovers()
    if ordenes:
        st.dataframe(pd.DataFrame(ordenes), use_container_width=True, hide_index=True)

# --- TAB 5: AUDITOR AIRCOVER (L3) ---
with tabs[4]:
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

# --- TAB 6: LISTING & GEO ---
with tabs[5]:
    st.subheader("Generador Multicanal + Optimización GEO (Cero Alucinaciones)")
    feedback_txt = st.text_area(
        "Pega reseñas o preguntas reales de huéspedes (una por línea):",
        value="El internet vuela para hacer home office todo el día sin cortes.\nSúper fácil entrar de noche con la chapa electrónica y el cajón de estacionamiento.\nEl aire acondicionado enfría riquísimo en verano en Monterrey."
    )
    if st.button("Generar Copys Validados (Airbnb / Booking / Vrbo)", type="primary"):
        ficha_depa = {
            "nombre": "Depa Las Villas",
            "ciudad": "Monterrey, Nuevo León",
            "tipo": "Departamento completo",
            "recamaras": 2,
            "capacidad": 4,
            "amenidades_reales": [
                "Wi-Fi de alta velocidad fibra óptica",
                "Aire acondicionado frío/calor",
                "Cocina equipada",
                "Estacionamiento privado",
                "Cerradura inteligente (self check-in)",
                "Zona residencial tranquila"
            ]
        }
        no_tiene = ["alberca", "piscina", "jacuzzi", "gimnasio", "pet friendly", "mascotas"]
        lineas = [l.strip() for l in feedback_txt.splitlines() if l.strip()]
        with st.spinner("Generando copys y auditando amenidades..."):
            res_geo = generar_anuncios_y_geo(ficha_depa, lineas, no_tiene)
        st.success(f"**Claim Checker:** {res_geo['gate_claim_checker']} | **Longitudes:** {res_geo['longitudes_validadas']}")
        st.json(res_geo["resultado"])

# --- TAB 7: FINANZAS & RFC ---
with tabs[6]:
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

# --- TAB 8: BITÁCORA DE AUDITORÍA ---
with tabs[7]:
    st.subheader("Registro Append-Only de Decisiones (`events` en SQLite)")
    conn = get_connection()
    try:
        df_events = pd.read_sql_query("SELECT * FROM events ORDER BY id DESC LIMIT 50", conn)
        st.dataframe(df_events, use_container_width=True, hide_index=True)
    except Exception:
        st.info("Aún no hay eventos registrados.")
    finally:
        conn.close()