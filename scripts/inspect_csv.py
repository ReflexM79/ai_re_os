"""Informe de estructura de un CSV SIN exponer datos personales.

Uso:   python scripts/inspect_csv.py data/raw/transacciones.csv

Pega el INFORME (no el CSV, no capturas) cuando pidas ayuda con el esquema.
Reglas de seguridad del informe:
  - columnas con nombre sospechoso de datos personales: no se imprime ningún valor;
  - columnas de texto: solo patrones enmascarados (letras -> a/A, dígitos -> 9);
  - valores literales solo en columnas de categoría de una lista blanca (tipo, moneda...);
  - si el archivo NO tiene encabezado, la primera fila no se imprime (podría ser un dato real).
"""
import csv
import io
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PII_HINTS = (
    "guest", "huésped", "huesped", "viajero", "traveler", "traveller", "cliente", "customer",
    "nombre", "name", "email", "correo", "phone", "tel", "contact", "address", "direcc",
    "dni", "passport", "pasaporte", "detail", "detalle", "note", "nota", "message", "mensaje",
    "reference", "referencia", "comment", "coment",
)
CATEGORY_OK = ("type", "tipo", "status", "estatus", "estado", "currency", "moneda", "channel", "canal")
DATE_FMTS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y", "%b %d, %Y", "%d %b %Y"]
NUM_RE = re.compile(r"^\(?[-+]?\s*[$€£]?\s*[-+]?\d[\d.,\s]*%?\)?$")


def decode(raw: bytes):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace"), "latin-1"


def parse_date(s: str, fmt: str):
    try:
        return datetime.strptime(s.strip(), fmt)
    except ValueError:
        return None


def mask(s: str) -> str:
    s = re.sub(r"\d", "9", s)
    s = re.sub(r"[A-ZÁÉÍÓÚÑÜ]", "A", s)
    s = re.sub(r"[a-záéíóúñü]", "a", s)
    return s[:30]


def to_float(s: str):
    t = re.sub(r"[^\d.,\-+()]", "", s)
    neg = t.startswith("(") or t.startswith("-")
    t = t.strip("()+-")
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        head, _, tail = t.rpartition(",")
        t = head.replace(",", "") + "." + tail if len(tail) in (1, 2) else t.replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def decimal_style(vals):
    c = Counter()
    for v in vals:
        m = re.search(r"([.,])(\d{1,2})\D*$", v.strip())
        if m:
            c["coma" if m.group(1) == "," else "punto"] += 1
    return dict(c)


def summarize(name: str, vals: list):
    present = [v.strip() for v in vals if v.strip()]
    empty = 100 * (len(vals) - len(present)) / len(vals) if vals else 0
    low = name.lower()
    if not present:
        return "vacía", empty, "—"
    if any(h in low for h in PII_HINTS):
        return "texto [PII]", empty, f"valores omitidos · {len(set(present))} distintos"

    fmts = [f for f in DATE_FMTS if all(parse_date(v, f) for v in present[:300])]
    if fmts:
        ds = sorted(d for d in (parse_date(v, fmts[0]) for v in present) if d)
        rng = f"{ds[0]:%Y-%m-%d} → {ds[-1]:%Y-%m-%d}"
        if {"%d/%m/%Y", "%m/%d/%Y"} <= set(fmts):
            return "fecha", empty, f"⚠ AMBIGUA dd/mm vs mm/dd (ambos parsean) · {rng} asumiendo dd/mm"
        return f"fecha {fmts[0]}", empty, rng

    if all(NUM_RE.match(v) for v in present):
        nums = [x for x in (to_float(v) for v in present) if x is not None]
        cur = sorted({c for v in present for c in re.findall(r"[$€£]", v)})
        rng = f"{min(nums):,.2f} … {max(nums):,.2f}" if nums else "?"
        return "número", empty, f"rango {rng} · decimal: {decimal_style(present) or 'enteros'} · símbolos: {cur or '—'}"

    distinct = Counter(present)
    if any(h in low for h in CATEGORY_OK) and len(distinct) <= 12:
        return "categoría", empty, ", ".join(f"{k}({c})" for k, c in distinct.most_common())
    pats = Counter(mask(v) for v in present).most_common(3)
    return "texto", empty, f"{len(distinct)} distintos · patrones: " + " | ".join(f"{p}×{c}" for p, c in pats)


def main(path: str) -> None:
    p = Path(path)
    raw = p.read_bytes()
    text, enc = decode(raw)
    bom = raw[:3] == b"\xef\xbb\xbf"
    try:
        delim = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|").delimiter
    except csv.Error:
        delim = ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    if len(rows) < 2:
        sys.exit("El archivo tiene menos de 2 filas útiles.")

    first = [c for c in rows[0] if c.strip()]
    datalike = sum(bool(NUM_RE.match(c.strip())) or any(parse_date(c, f) for f in DATE_FMTS) for c in first)
    headerless = bool(first) and datalike >= max(2, len(first) // 2)
    if headerless:
        header, body = [f"col_{i + 1}" for i in range(len(rows[0]))], rows
    else:
        header, body = [h.strip() for h in rows[0]], rows[1:]

    width = len(header)
    ragged = sum(1 for r in body if len(r) != width)
    dups = [h for h, c in Counter(header).items() if c > 1]

    print(f"# Informe de {p.name}")
    print(f"- codificación: {enc}{' (con BOM)' if bom else ''} · separador: {delim!r} "
          f"· filas de datos: {len(body)} · columnas: {width}")
    print("- encabezado: " + ("⚠ NO DETECTADO (la primera fila parece datos); columnas renombradas col_N"
                              if headerless else "sí"))
    if ragged:
        print(f"- ⚠ {ragged} filas con distinto número de columnas")
    if dups:
        print(f"- ⚠ encabezados duplicados: {dups}")
    print("\n| # | columna | tipo | % vacío | resumen |\n|---|---|---|---|---|")
    for i, name in enumerate(header):
        vals = [r[i] if i < len(r) else "" for r in body]
        typ, empty, info = summarize(name, vals)
        print(f"| {i + 1} | {name} | {typ} | {empty:.0f}% | {info} |")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: python scripts/inspect_csv.py ruta/al/archivo.csv")
    main(sys.argv[1])