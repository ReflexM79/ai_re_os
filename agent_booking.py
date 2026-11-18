import os
import json
import time
from decimal import Decimal
from typing import Literal, Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from pricing import cargar_politicas, calcular_pisos_tarifa, margen_descuento_disponible
from calendar_engine import verificar_disponibilidad, detectar_huecos_huerfanos

load_dotenv()

class AnalisisMensaje(BaseModel):
    intencion: Literal["consulta_general", "solicitud_descuento", "cambio_horario", "riesgo_fiesta", "pago_externo"]
    checkin: Optional[str] = Field(default=None, description="Fecha de entrada en formato YYYY-MM-DD si se menciona, o null")
    checkout: Optional[str] = Field(default=None, description="Fecha de salida en formato YYYY-MM-DD si se menciona, o null")
    noches_estimadas: int = Field(default=2, ge=1)
    descuento_solicitado_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    senales_riesgo: list[str]
    resumen_pedido: str

def llamar_gemini_rapido(cliente: genai.Client, modelos: list[str], contents: str, system_instruction: str, schema=None):
    """Llama a Gemini con respaldo automático entre modelos."""
    ultimo_error = None
    for modelo in modelos:
        try:
            print(f"-> Consultando {modelo}...")
            config_args = {
                "system_instruction": system_instruction,
                "temperature": 0.2,
            }
            if schema is not None:
                config_args["response_mime_type"] = "application/json"
                config_args["response_schema"] = schema

            return cliente.models.generate_content(
                model=modelo,
                contents=contents,
                config=types.GenerateContentConfig(**config_args),
            )
        except Exception as e:
            ultimo_error = e
            print(f"[Aviso] {modelo} no respondió ({type(e).__name__}). Probando respaldo...")
            time.sleep(1)
    raise ultimo_error

def procesar_mensaje_huesped(mensaje: str, tarifa_actual_noche: Decimal) -> dict:
    api_key = os.environ["GEMINI_API_KEY"]
    modelo_principal = os.environ.get("MODEL_ROUTER", "gemini-4-hydrogen")
    modelos_fallback = list(dict.fromkeys([modelo_principal, "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash"]))

    cliente = genai.Client(api_key=api_key)
    politicas = cargar_politicas()

    # PASO A (LLM): Entender intención, fechas y riesgos del huésped
    resp_analisis = llamar_gemini_rapido(
        cliente,
        modelos_fallback,
        contents=mensaje,
        system_instruction=(
            "Eres un analista de seguridad y reservas de Airbnb (año actual: 2026). "
            "Extrae la intención del huésped, fechas de checkin y checkout en formato YYYY-MM-DD si las menciona, "
            "cuántas noches pide (calculadas de las fechas o 2 por defecto), qué % de descuento pide (0 si no pide) "
            "y detecta señales de riesgo (fiestas, invitados extra, pagar fuera de Airbnb, tono agresivo)."
        ),
        schema=AnalisisMensaje,
    )
    analisis: AnalisisMensaje = resp_analisis.parsed

    # PASO B (CALENDARIO DETERMINISTA): Verificar disponibilidad real en SQLite
    estado_calendario = {"verificado": False, "disponible": True, "detalle": "No especificó fechas exactas."}
    noches = analisis.noches_estimadas

    if analisis.checkin and analisis.checkout:
        disp = verificar_disponibilidad(analisis.checkin, analisis.checkout)
        estado_calendario = {
            "verificado": True,
            "checkin": analisis.checkin,
            "checkout": analisis.checkout,
            "disponible": disp["disponible"],
            "detalle": disp["motivo"],
            "conflictos": disp["conflictos"]
        }
        if disp.get("noches", 0) > 0:
            noches = disp["noches"]

    # PASO C (FINANZAS Y POLÍTICAS): Evaluar pisos y descuentos
    pisos = calcular_pisos_tarifa(noches=noches)
    descuento_max_seguro = margen_descuento_disponible(tarifa_actual_noche, noches=noches)
    pedido_pct = Decimal(str(analisis.descuento_solicitado_pct))
    huecos = detectar_huecos_huerfanos(max_noches_hueco=2)

    decision = "APROBADO"
    instruccion_redaccion = ""

    if estado_calendario["verificado"] and not estado_calendario["disponible"]:
        decision = "FECHAS_NO_DISPONIBLES"
        sugerencia_huecos = ""
        if huecos:
            h = huecos[0]
            sugerencia_huecos = (
                f"Como alternativa cercana, menciónale que tienes disponible del {h['inicio_libre']} "
                f"al {h['fin_libre']} ({h['noches_huerfanas']} noches)."
            )
        instruccion_redaccion = (
            f"Informa amablemente que las fechas del {analisis.checkin} al {analisis.checkout} ya están ocupadas. "
            f"{sugerencia_huecos} Invítalo a compartir otras fechas flexibles."
        )
    elif analisis.intencion == "pago_externo":
        decision = "BLOQUEADO_POLITICA"
        instruccion_redaccion = (
            "Rechaza amablemente cualquier pago o trato fuera de la plataforma Airbnb por políticas "
            "de seguridad y protección de ambas partes, invitándolo a completar su reserva aquí mismo."
        )
    elif analisis.intencion == "riesgo_fiesta" or len(analisis.senales_riesgo) > 0:
        decision = "REVISION_HUMANA_RIESGO"
        instruccion_redaccion = (
            "Responde con cortesía recordando que el departamento es una zona residencial tranquila, "
            "no se permiten fiestas ni invitados adicionales al registro, y pide confirmar el motivo de su viaje."
        )
    elif pedido_pct > 0:
        if pedido_pct <= descuento_max_seguro:
            decision = "DESCUENTO_APROBADO"
            tarifa_final = (tarifa_actual_noche * (Decimal("1") - pedido_pct / Decimal("100"))).quantize(Decimal("0.01"))
            instruccion_redaccion = (
                f"Confirma que las fechas están libres, aprueba con entusiasmo el descuento del {pedido_pct}% "
                f"para sus {noches} noches, dejando la tarifa en ${tarifa_final} MXN por noche (antes de impuestos), "
                f"e invítalo a reservar hoy."
            )
        else:
            decision = "CONTRAOFERTA_LIMITE"
            tarifa_final = (tarifa_actual_noche * (Decimal("1") - descuento_max_seguro / Decimal("100"))).quantize(Decimal("0.01"))
            instruccion_redaccion = (
                f"Confirma que las fechas están disponibles, explica amablemente que no es posible llegar al {pedido_pct}%, "
                f"pero que como atención especial le autorizas el descuento máximo del sistema que es {descuento_max_seguro}%, "
                f"quedando en ${tarifa_final} MXN por noche (antes de impuestos) si confirma hoy."
            )
    else:
        instruccion_redaccion = (
            f"Confirma disponibilidad en {politicas.get('property_name', 'la propiedad')} y la tarifa vigente "
            f"de ${tarifa_actual_noche} MXN por noche (antes de impuestos), destacando la comodidad del espacio."
        )

    # PASO D (LLM): Redactar respuesta final usando SOLO los datos validados
    resp_borrador = llamar_gemini_rapido(
        cliente,
        modelos_fallback,
        contents=f"Mensaje del huésped: '{mensaje}'\nInstrucción exacta a seguir: {instruccion_redaccion}",
        system_instruction=(
            "Eres un anfitrión estrella de Airbnb en Monterrey (Superhost). "
            "Redacta un mensaje breve, cálido, profesional y persuasivo en español. "
            "NUNCA inventes fechas, precios ni porcentajes distintos a los de la instrucción."
        ),
    )

    return {
        "propiedad": politicas.get("property_name"),
        "calendario": estado_calendario,
        "analisis_ia": analisis.model_dump(),
        "auditoria_matematica": {
            "tarifa_lista_noche": str(tarifa_actual_noche),
            "adr_objetivo_equilibrio": str(pisos["adr_objetivo_noche"]),
            "piso_marginal_absoluto": str(pisos["piso_marginal_noche"]),
            "descuento_max_permitido_pct": str(descuento_max_seguro),
            "decision_sistema": decision,
        },
        "borrador_respuesta": resp_borrador.text.strip()
    }

if __name__ == "__main__":
    # Probamos con una fecha que CHOCA con HM001 (15 al 20 dic 2026) para ver cómo protege el calendario
    mensaje_prueba = (
        "Hola! Busco hospedaje del 2026-12-18 al 2026-12-21 en Depa Las Villas. "
        "¿Tienen disponible y me hacen un 15% de descuento?"
    )
    print("Verificando calendario en SQLite, márgenes y redactando respuesta...\n")
    resultado = procesar_mensaje_huesped(mensaje_prueba, tarifa_actual_noche=Decimal("1300.00"))
    print(json.dumps(resultado, indent=2, ensure_ascii=False))