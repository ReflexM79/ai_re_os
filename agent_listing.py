import os
import json
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field

from agent_booking import llamar_gemini_rapido

load_dotenv(override=True)

class AnuncioMulticanalGEO(BaseModel):
    titulo_airbnb: str = Field(description="Máximo 50 caracteres, cercano y atractivo")
    descripcion_airbnb: str = Field(description="Tono cercano, experiencial, enfocado en ubicación y comodidad")
    titulo_booking: str = Field(description="Máximo 70 caracteres, estilo hotelero, técnico y directo")
    descripcion_booking: str = Field(description="Enfocado en equipamiento, conectividad, facturación y distancias")
    titulo_vrbo: str = Field(description="Máximo 70 caracteres, enfocado en familias, seguridad y amplitud")
    descripcion_vrbo: str = Field(description="Enfocado en equipamiento de cocina, tranquilidad y estacionamiento")
    palabras_clave_geo: list[str] = Field(description="Beneficios reales y términos de búsqueda local en Nuevo León para motores de IA")

def verificar_afirmaciones(texto: str, amenidades_prohibidas: list[str]) -> list[str]:
    texto_lower = texto.lower()
    return [item for item in amenidades_prohibidas if item.lower() in texto_lower]

def generar_anuncios_y_geo(
    ficha_real: dict,
    resenas_y_preguntas: list[str] | None = None,
    amenidades_que_no_tiene: list[str] | None = None
) -> dict:
    api_key = os.environ["GEMINI_API_KEY"]
    modelo_principal = os.environ.get("MODEL_ROUTER", "gemini-4-hydrogen")
    modelos_fallback = list(dict.fromkeys([modelo_principal, "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash"]))
    cliente = genai.Client(api_key=api_key)

    resenas_limpias = [r.strip() for r in (resenas_y_preguntas or []) if r.strip()]
    prohibidas = amenidades_que_no_tiene or []

    if resenas_limpias:
        bloque_contexto = (
            "RESEÑAS Y PREGUNTAS FRECUENTES DE HUÉSPEDES:\n"
            + "\n".join(f"- {r}" for r in resenas_limpias)
        )
    else:
        bloque_contexto = (
            "PROPIEDAD EN LANZAMIENTO (SIN RESEÑAS PREVIAS):\n"
            "- Deduce los atractivos del entorno y perfiles de viajero en Nuevo León únicamente a partir de la ubicación y características verificadas en la ficha."
        )

    prompt = (
        f"FICHA REAL VERIFICADA DE LA PROPIEDAD:\n{json.dumps(ficha_real, ensure_ascii=False)}\n\n"
        f"{bloque_contexto}\n\n"
        "Genera versiones nativas optimizadas para Airbnb, Booking.com y Vrbo, "
        "y extrae las palabras clave GEO reales para buscadores impulsados por IA en Nuevo León."
    )

    resp = llamar_gemini_rapido(
        cliente,
        modelos_fallback,
        contents=prompt,
        system_instruction=(
            "Eres un Director Creativo Inmobiliario y especialista en Generative Engine Optimization (GEO) en Nuevo León, México. "
            "REGLA ABSOLUTA: Jamás menciones una amenidad, servicio o atributo interno que no esté explícitamente en la ficha real verificada."
        ),
        schema=AnuncioMulticanalGEO,
    )

    anuncio: AnuncioMulticanalGEO = resp.parsed
    anuncio.titulo_airbnb = anuncio.titulo_airbnb[:50]
    anuncio.titulo_booking = anuncio.titulo_booking[:70]
    anuncio.titulo_vrbo = anuncio.titulo_vrbo[:70]

    todo_el_texto = (
        f"{anuncio.titulo_airbnb} {anuncio.descripcion_airbnb} "
        f"{anuncio.titulo_booking} {anuncio.descripcion_booking} "
        f"{anuncio.titulo_vrbo} {anuncio.descripcion_vrbo}"
    )
    alucinaciones = verificar_afirmaciones(todo_el_texto, prohibidas)

    return {
        "gate_claim_checker": "PASS (0 alucinaciones)" if not alucinaciones else f"FAIL: mencionó {alucinaciones}",
        "longitudes_validadas": {
            "airbnb": f"{len(anuncio.titulo_airbnb)}/50",
            "booking": f"{len(anuncio.titulo_booking)}/70",
            "vrbo": f"{len(anuncio.titulo_vrbo)}/70"
        },
        "resultado": anuncio.model_dump()
    }