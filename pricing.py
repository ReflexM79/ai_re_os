import os
import yaml
from decimal import Decimal, ROUND_HALF_UP

# --- CONFIGURACIÓN FISCAL MÉXICO (Airbnb) ---
COMISION_AIRBNB = Decimal("0.1856")  # 15.5% comisión + 16% IVA sobre la comisión = ~18.56%
TASA_IVA = Decimal("0.16")           # IVA general 16%
TASA_IVA_RETENIDO = Decimal("0.08")  # Retención de IVA = 8%
TASA_ISR_RETENIDO = Decimal("0.04")  # Retención de ISR = 4%

def r(valor: Decimal) -> float:
    """Redondea a 2 decimales para mostrarlo en pantalla."""
    return float(valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def cargar_politicas() -> dict:
    """Lee el archivo policies.yaml (necesario para app.py)."""
    ruta = "policies.yaml"
    if not os.path.exists(ruta):
        ruta = os.path.join("config", "policies.yaml")
        
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Error leyendo {ruta}: {e}")
    return {}

def calcular_pago_neto(subtotal_hospedaje: Decimal) -> dict:
    """Calcula el desglose exacto de lo que deposita Airbnb."""
    subtotal_hospedaje = Decimal(str(subtotal_hospedaje))
    
    # 1. Cálculos de impuestos y comisiones
    comision_airbnb_total = subtotal_hospedaje * COMISION_AIRBNB
    iva_trasladado = subtotal_hospedaje * TASA_IVA
    iva_retenido = subtotal_hospedaje * TASA_IVA_RETENIDO
    isr_retenido = subtotal_hospedaje * TASA_ISR_RETENIDO
    
    # 2. El dinero real que llega a tu banco (CORREGIDO)
    neto_banco = subtotal_hospedaje - comision_airbnb_total - iva_retenido - isr_retenido

    return {
        "subtotal_hospedaje": r(subtotal_hospedaje),
        "comision_airbnb_total": r(comision_airbnb_total),
        "iva_trasladado": r(iva_trasladado),
        "iva_retenido": r(iva_retenido),
        "isr_retenido": r(isr_retenido),
        "tu_ganas_neto": r(neto_banco)
    }

def calcular_pisos_tarifa(noches: int, fixed_month: Decimal = Decimal("18000"), days: int = 30, occ: Decimal = Decimal("0.60"), cv_night: Decimal = Decimal("150"), cv_stay: Decimal = Decimal("600"), fee: Decimal = Decimal("0.16")) -> dict:
    """
    Calcula el Punto de Equilibrio (ADR objetivo) y el Piso Marginal por venta.
    """
    noches = Decimal(str(max(1, noches)))
    
    politicas = cargar_politicas()
    if politicas:
        try:
            fixed_month = Decimal(str(politicas.get("fixed_month", fixed_month)))
            cv_night = Decimal(str(politicas.get("cv_night", cv_night)))
            cv_stay = Decimal(str(politicas.get("cv_stay", cv_stay)))
            fee = Decimal(str(politicas.get("fee", fee)))
        except:
            pass

    fixed_per_occ_night = fixed_month / (Decimal(str(days)) * occ)
    cost_stay = noches * (fixed_per_occ_night + cv_night) + cv_stay
    adr_objetivo = cost_stay / (noches * (1 - fee))
    
    var_cost_stay = (noches * cv_night + cv_stay) * Decimal("1.15")
    piso_marginal = var_cost_stay / (noches * (1 - fee))

    return {
        "adr_objetivo_noche": r(adr_objetivo),
        "piso_marginal_noche": r(piso_marginal)
    }

# --- FUNCIÓN RECUPERADA (La que faltaba) ---
def margen_descuento_disponible(precio_actual: float, piso_marginal: float, max_pct: float = 0.20) -> float:
    """
    Calcula el porcentaje máximo de descuento seguro.
    Basado en la fórmula de Claude: min(max_pct, max(0, 1 - floor / price))
    """
    precio_actual = Decimal(str(precio_actual))
    piso_marginal = Decimal(str(piso_marginal))
    max_pct = Decimal(str(max_pct))

    if precio_actual <= 0:
        return 0.0

    margen_teorico = Decimal("1") - (piso_marginal / precio_actual)
    descuento_seguro = max(Decimal("0"), min(max_pct, margen_teorico))
    
    return float(descuento_seguro)

if __name__ == "__main__":
    print("--- PRUEBA MOTOR FINANCIERO (CON RFC) ---")
    subtotal = Decimal("10000.00")
    resultado = calcular_pago_neto(subtotal)
    for k, v in resultado.items():
        print(f"{k}: ${v}")