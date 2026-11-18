from decimal import Decimal, ROUND_CEILING
from datetime import datetime
from db import get_connection
from calendar_engine import listar_reservas_activas, parse_fecha

def calcular_net_parity(neto_deseado: Decimal, paso_redondeo: Decimal = Decimal("10")) -> dict:
    """
    Calcula qué precio público publicar en cada canal para recibir exactamente
    `neto_deseado` libre de comisión de plataforma (redondeado hacia arriba).
    """
    comisiones = {
        "canal_directo": Decimal("0.00"),
        "vrbo": Decimal("0.08"),
        "booking_com": Decimal("0.15"),
        "airbnb_host_only_con_iva": Decimal("0.1856"),  # 16% + 16% IVA sobre comisión
    }

    precios = {}
    for canal, fee in comisiones.items():
        bruto = neto_deseado / (Decimal("1") - fee)
        publicado = (bruto / paso_redondeo).to_integral_value(rounding=ROUND_CEILING) * paso_redondeo
        neto_real = (publicado * (Decimal("1") - fee)).quantize(Decimal("0.01"))
        precios[canal] = {
            "precio_publico_mxn": str(publicado),
            "comision_efectiva_pct": str((fee * 100).quantize(Decimal("0.01"))),
            "neto_recibido_mxn": str(neto_real)
        }
    return precios

def generar_plan_limpieza_y_turnovers() -> list[dict]:
    """
    Escanea todas las reservas activas, genera la orden de limpieza por cada check-out
    y detecta 'Back-to-Backs' (cuando sale un huésped y entra otro el mismo día).
    """
    reservas = [r for r in listar_reservas_activas() if r["status"] != "cancelada"]
    checkins_por_fecha = {r["checkin"]: r for r in reservas}

    ordenes = []
    for res in reservas:
        fecha_salida = res["checkout"]
        siguiente_reserva = checkins_por_fecha.get(fecha_salida)

        es_back_to_back = siguiente_reserva is not None
        prioridad = "CRÍTICA (BACK-TO-BACK)" if es_back_to_back else "ESTÁNDAR"
        ventana_horaria = (
            "11:00 AM - 3:00 PM ESTRICTO (Prohibido Late Check-out / Early Check-in)"
            if es_back_to_back
            else "11:00 AM - 4:00 PM Flexible"
        )

        ordenes.append({
            "fecha_limpieza": fecha_salida,
            "reserva_saliente": res["codigo_reserva"],
            "huesped_saliente": res["huesped"],
            "es_back_to_back": es_back_to_back,
            "reserva_entrante": siguiente_reserva["codigo_reserva"] if es_back_to_back else "Ninguna ese día",
            "prioridad": prioridad,
            "ventana_operativa": ventana_horaria
        })

    return ordenes

if __name__ == "__main__":
    import json
    print("--- 1. ÓRDENES DE LIMPIEZA Y DETECCIÓN BACK-TO-BACK ---")
    print(json.dumps(generar_plan_limpieza_y_turnovers(), indent=2, ensure_ascii=False))

    print("\n--- 2. CALCULADORA NET-PARITY (Meta: recibir $1,000.00 MXN netos/noche) ---")
    print(json.dumps(calcular_net_parity(Decimal("1000.00")), indent=2, ensure_ascii=False))