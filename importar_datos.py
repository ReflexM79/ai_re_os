import sqlite3
import csv
import os

DB_PATH = "data/property_os.db"

def importar_csv_a_db():
    if not os.path.exists(DB_PATH):
        print("[Error] La base de datos no existe. Ejecuta primero db.py")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Importar Reservas
    reservas_path = "data/raw/reservas.csv"
    if os.path.exists(reservas_path):
        with open(reservas_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                try:
                    cursor.execute("""
                    INSERT OR IGNORE INTO reservations
                    (codigo_reserva, checkin, checkout, precio_total, comision, neto, huesped)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row['codigo_reserva'],
                        row['checkin'],
                        row['checkout'],
                        row['precio_total'],
                        row['comision_airbnb'],
                        row['neto'],
                        row['huesped']
                    ))
                    count += 1
                except Exception as e:
                    print(f"Error insertando reserva {row.get('codigo_reserva')}: {e}")
        conn.commit()
        print(f"[DB] Se procesaron {count} registros en la tabla 'reservations'.")
    else:
        print(f"[Aviso] No se encontró el archivo {reservas_path}")

    # 2. Importar Payouts
    payouts_path = "data/raw/payouts.csv"
    if os.path.exists(payouts_path):
        with open(payouts_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                try:
                    cursor.execute("""
                    INSERT OR IGNORE INTO payouts
                    (fecha, reserva_codigo, codigo_payout, monto_neto, estado)
                    VALUES (?, ?, ?, ?, ?)
                    """, (
                        row['fecha'],
                        row['reserva'],
                        row['codigo'],
                        row['monto_neto'],
                        row['estado']
                    ))
                    count += 1
                except Exception as e:
                    print(f"Error insertando payout {row.get('codigo')}: {e}")
        conn.commit()
        print(f"[DB] Se procesaron {count} registros en la tabla 'payouts'.")
    else:
        print(f"[Aviso] No se encontró el archivo {payouts_path}")

    conn.close()

if __name__ == "__main__":
    importar_csv_a_db()