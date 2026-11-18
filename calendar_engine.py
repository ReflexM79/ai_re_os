from datetime import datetime, timedelta
from db import get_connection

def parse_fecha(fecha_str: str) -> datetime.date:
    return datetime.strptime(fecha_str.strip(), "%Y-%m-%d").date()

def verificar_disponibilidad(checkin_str: str, checkout_str: str) -> dict:
    """
    Verifica en SQLite si el rango [checkin, checkout) está libre,
    aplicando la regla estándar hotelera donde checkout == checkin el mismo día NO choca.
    """
    checkin = parse_fecha(checkin_str)
    checkout = parse_fecha(checkout_str)

    if checkout <= checkin:
        return {
            "disponible": False,
            "motivo": "La fecha de salida debe ser posterior a la fecha de entrada.",
            "conflictos": []
        }

    conn = get_connection()
    cursor = conn.cursor()

    # Una reserva existente choca si: existente.checkin < nuevo.checkout AND existente.checkout > nuevo.checkin
    cursor.execute("""
        SELECT codigo_reserva, checkin, checkout, huesped, status
        FROM reservations
        WHERE status != 'cancelada'
          AND checkin < ?
          AND checkout > ?
        ORDER BY checkin ASC
    """, (checkout_str, checkin_str))

    filas = cursor.fetchall()
    conn.close()

    conflictos = [dict(f) for f in filas]
    noches = (checkout - checkin).days

    if conflictos:
        return {
            "disponible": False,
            "noches": noches,
            "motivo": f"Choca con {len(conflictos)} reserva(s) existente(s).",
            "conflictos": conflictos
        }

    return {
        "disponible": True,
        "noches": noches,
        "motivo": "Fechas 100% libres en calendario.",
        "conflictos": []
    }

def detectar_huecos_huerfanos(max_noches_hueco: int = 2) -> list[dict]:
    """
    Escanea las reservas confirmadas en SQLite y detecta huecos libres
    de 1 a max_noches_hueco entre reservas consecutivas (días huérfanos).
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT codigo_reserva, checkin, checkout
        FROM reservations
        WHERE status != 'cancelada'
        ORDER BY checkin ASC
    """)
    reservas = [dict(r) for r in cursor.fetchall()]
    conn.close()

    huecos = []
    for i in range(len(reservas) - 1):
        salida_actual = parse_fecha(reservas[i]["checkout"])
        entrada_siguiente = parse_fecha(reservas[i + 1]["checkin"])
        dias_libres = (entrada_siguiente - salida_actual).days

        if 1 <= dias_libres <= max_noches_hueco:
            huecos.append({
                "inicio_libre": reservas[i]["checkout"],
                "fin_libre": reservas[i + 1]["checkin"],
                "noches_huerfanas": dias_libres,
                "entre_reservas": f"{reservas[i]['codigo_reserva']} y {reservas[i + 1]['codigo_reserva']}"
            })

    return huecos

def listar_reservas_activas() -> list[dict]:
    """Devuelve todas las reservas cargadas en la base de datos."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT codigo_reserva, checkin, checkout, neto, huesped, status
        FROM reservations
        ORDER BY checkin ASC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

if __name__ == "__main__":
    print("--- 1. RESERVAS ACTUALES EN BASE DE DATOS ---")
    for r in listar_reservas_activas():
        print(f"• {r['codigo_reserva']} | {r['checkin']} al {r['checkout']} | {r['huesped']} | Neto: ${r['neto']}")

    print("\n--- 2. PRUEBA ANTI-OVERBOOKING (Choque con HM001: 2026-12-18 al 2026-12-21) ---")
    print(verificar_disponibilidad("2026-12-18", "2026-12-21"))

    print("\n--- 3. PRUEBA FECHA LIBRE (2026-12-20 al 2026-12-22) ---")
    print(verificar_disponibilidad("2026-12-20", "2026-12-22"))

    print("\n--- 4. DETECCIÓN DE DÍAS HUÉRFANOS (<= 2 noches) ---")
    huecos = detectar_huecos_huerfanos(max_noches_hueco=2)
    print(huecos if huecos else "No hay huecos cortos entre las reservas actuales.")