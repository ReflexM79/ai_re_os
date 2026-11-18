"""Pre-flight: lista los modelos que TU clave puede llamar con generateContent.

Uso:   python scripts/list_models.py

Elige uno tipo 'flash' / 'flash-lite' que NO esté deprecado y ponlo en .env
como MODEL_ROUTER=... (no hardcodees nombres de modelo en el código).
Deprecaciones: https://ai.google.dev/gemini-api/docs/deprecations
"""
import os
import sys

from dotenv import load_dotenv
from google import genai

load_dotenv(override=True)  # el .env manda sobre variables viejas del sistema

key = os.getenv("GEMINI_API_KEY", "").strip()
if not key:
    sys.exit("Falta GEMINI_API_KEY en .env (en la raíz del proyecto).")

client = genai.Client(api_key=key)

names = []
for m in client.models.list():
    actions = getattr(m, "supported_actions", None) or []
    if "generateContent" in actions:
        names.append(m.name.removeprefix("models/"))

for name in sorted(names):
    print(name)

print(f"\n{len(names)} modelos con generateContent para tu clave.")
print("Un modelo que aparece aquí PUEDE estar deprecado: confírmalo en la página de deprecaciones.")