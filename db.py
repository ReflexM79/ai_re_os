import sqlite3
import os

DB_PATH = "data/property_os.db"

def get_connection():
    """Abre una conexión SQLite con soporte para WAL y foreign keys."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_db():
    """Crea las tablas principales del sistema si no existen."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reservations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo_reserva TEXT UNIQUE NOT NULL,
        checkin TEXT NOT NULL,
        checkout TEXT NOT NULL,
        precio_total TEXT NOT NULL,
        comision TEXT NOT NULL,
        neto TEXT NOT NULL,
        huesped TEXT NOT NULL,
        status TEXT DEFAULT 'confirmada',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT NOT NULL,
        reserva_codigo TEXT NOT NULL,
        codigo_payout TEXT UNIQUE NOT NULL,
        monto_neto TEXT NOT NULL,
        estado TEXT NOT NULL,
        FOREIGN KEY(reserva_codigo) REFERENCES reservations(codigo_reserva)
    )
    """)

    conn.commit()
    conn.close()
    print("[DB] Base de datos inicializada correctamente en modo WAL.")

if __name__ == "__main__":
    init_db()