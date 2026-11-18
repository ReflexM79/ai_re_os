import sqlite3
import csv
import os

def auditar_reservas_vs_pagos(ruta_payouts_csv: str = "data/payouts.csv") -> dict:
    # 1. Buscar el archivo CSV (por si acaso sigue en raw)
    if not os.path.exists(ruta_payouts_csv):
        ruta_payouts_csv = "data/raw/payouts.csv"
        
    # 2. Leer los pagos del CSV y guardarlos en un diccionario fácil de buscar
    pagos = {}
    if os.path.exists(ruta_payouts_csv):
        with open(ruta_payouts_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Limpiamos los espacios en blanco por si las dudas
                cod = row.get('reserva', '').strip()
                monto_str = row.get('monto_neto', '0').strip()
                if cod:
                    try:
                        pagos[cod] = float(monto_str)
                    except ValueError:
                        pagos[cod] = 0.0

    # 3. Buscar la base de datos (os.db o property_os.db)
    db_path = "data/property_os.db"
    if not os.path.exists(db_path):
        db_path = "data/os.db"

    reporte = []
    total_esperado = 0.0
    total_depositado = 0.0
    pendientes_cobro = 0

    # 4. Leer las reservas de la base de datos
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Asumimos que la tabla se llama 'reservations'
        cursor.execute("SELECT * FROM reservations")
        reservas = cursor.fetchall()
        
        for res in reservas:
            # Extraer datos de la reserva (ajustando los nombres de las columnas)
            cod = str(res["codigo_reserva"]).strip()
            huesped = res["huesped"]
            checkin = res["checkin"]
            neto_esperado = float(res["neto"]) if res["neto"] else 0.0
            
            # Magia: Buscar si hay un pago en el CSV que coincida con este código
            monto_real = pagos.get(cod, 0.0)
            diferencia = neto_esperado - monto_real
            
            if monto_real == 0:
                estado = "PENDIENTE_DEPOSITO"
                pendientes_cobro += 1
            elif diferencia > 1:
                estado = "PAGO_PARCIAL"
            elif diferencia < -1:
                estado = "SOBREPAGO"
            else:
                estado = "CONCILIADO"
                
            total_esperado += neto_esperado
            total_depositado += monto_real
            
            reporte.append({
                "codigo_reserva": cod,
                "huesped": huesped,
                "checkin": checkin,
                "neto_esperado": f"{neto_esperado:.2f}",
                "depositado_banco": f"{monto_real:.2f}",
                "diferencia": f"{diferencia:.2f}",
                "estado": estado
            })
        conn.close()

    return {
        "resumen": {
            "total_reservas_activas": len(reporte),
            "total_neto_esperado_mxn": f"{total_esperado:.2f}",
            "total_depositado_mxn": f"{total_depositado:.2f}",
            "saldo_por_cobrar_mxn": f"{total_esperado - total_depositado:.2f}",
            "reservas_pendientes_pago": pendientes_cobro
        },
        "detalle": reporte
    }