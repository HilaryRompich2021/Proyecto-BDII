"""
load.py — Carga por lotes a PostgreSQL usando COPY
Dataset: Airline On-Time Performance (BTS) 2023-2024
Uso: python etl/load.py

Requisitos en requirements.txt:
    psycopg2-binary
    pandas
    pyarrow

Configura tus credenciales de PostgreSQL en la sección CONFIGURACION.
"""

import io
import time
import logging
import pandas as pd
import pyarrow.parquet as pq
import psycopg2
from psycopg2 import sql
from pathlib import Path

# ─── CONFIGURACION ────────────────────────────────────────────────────────────
# Ajusta estos valores a tu instalación local de PostgreSQL

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5433,
    "dbname": "airline_dw",
    "user": "postgres",
    "password": "postgres"
}

TRANSFORMED_DIR = Path("staging/transformed")
CHUNK_SIZE      = 50_000   # filas por batch en COPY — balance velocidad/memoria

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("staging/load.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ─── COPY helper ──────────────────────────────────────────────────────────────

def copy_dataframe(conn, df: pd.DataFrame, table: str, schema: str = "dw"):
    """
    Carga un DataFrame a PostgreSQL usando COPY FROM STDIN.
    Mucho más rápido que INSERT fila por fila o execute_values.
    """
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, header=False, na_rep="\\N")
    buffer.seek(0)

    full_table = f"{schema}.{table}"
    cols = ", ".join(df.columns.tolist())

    with conn.cursor() as cur:
        copy_sql = f"COPY {full_table} ({cols}) FROM STDIN WITH (FORMAT CSV, NULL '\\N')"
        cur.copy_expert(copy_sql, buffer)
    conn.commit()


# ─── Loaders por tabla ────────────────────────────────────────────────────────

def load_dim_tiempo(conn):
    log.info("\n[1/4] Cargando dim_tiempo...")
    t0  = time.time()
    df  = pd.read_parquet(TRANSFORMED_DIR / "dim_tiempo.parquet")
    copy_dataframe(conn, df, "dim_tiempo")
    log.info(f"  {len(df):,} filas cargadas en {time.time()-t0:.1f}s")


def load_dim_aerolinea(conn):
    log.info("\n[2/4] Cargando dim_aerolinea...")
    t0  = time.time()
    df  = pd.read_parquet(TRANSFORMED_DIR / "dim_aerolinea.parquet")
    copy_dataframe(conn, df, "dim_aerolinea")
    log.info(f"  {len(df):,} filas cargadas en {time.time()-t0:.1f}s")


def load_dim_aeropuerto(conn):
    log.info("\n[3/4] Cargando dim_aeropuerto...")
    t0  = time.time()
    df  = pd.read_parquet(TRANSFORMED_DIR / "dim_aeropuerto.parquet")
    copy_dataframe(conn, df, "dim_aeropuerto")
    log.info(f"  {len(df):,} filas cargadas en {time.time()-t0:.1f}s")


def load_fact_vuelo(conn):
    """
    Carga fact_vuelo desde los 24 Parquets mensuales generados por transform.py.
    Procesa chunk a chunk para no saturar RAM.
    """
    log.info("\n[4/4] Cargando fact_vuelo...")
    fact_dir   = TRANSFORMED_DIR / "fact_vuelo"
    parquets   = sorted(fact_dir.glob("*.parquet"))

    if not parquets:
        log.error(f"No se encontraron Parquets en {fact_dir}. Ejecuta transform.py primero.")
        return

    log.info(f"  Archivos Parquet encontrados: {len(parquets)}")

    total_rows = 0
    t0_total   = time.time()

    # Columnas en el orden exacto del DDL (sin flight_sk que es IDENTITY)
    FACT_COLS = [
        "tiempo_sk", "aerolinea_sk", "origen_sk", "destino_sk",
        "flight_date",
        "dep_delay", "arr_delay", "air_time", "distance",
        "cancelled", "cancellation_code", "diverted",
        "carrier_delay", "weather_delay", "nas_delay",
        "security_delay", "late_aircraft_delay",
        "taxi_out", "taxi_in",
    ]

    for parquet_file in parquets:
        log.info(f"  Cargando: {parquet_file.name}")
        t0_file = time.time()
        file_rows = 0

        # Leer el Parquet en chunks para no saturar RAM
        parquet_obj = pq.ParquetFile(parquet_file)
        for batch in parquet_obj.iter_batches(batch_size=CHUNK_SIZE):
            chunk = batch.to_pandas()

            # Asegurar orden y tipos de columnas
            chunk = chunk[[c for c in FACT_COLS if c in chunk.columns]]
            chunk["flight_date"]      = pd.to_datetime(chunk["flight_date"]).dt.date
            chunk["cancelled"]        = chunk["cancelled"].astype(int)
            chunk["diverted"]         = chunk["diverted"].astype(int)
            chunk["cancellation_code"]= chunk["cancellation_code"].fillna("N/A")

            copy_dataframe(conn, chunk, "fact_vuelo")
            file_rows  += len(chunk)
            total_rows += len(chunk)

        elapsed = time.time() - t0_file
        log.info(f"    {file_rows:,} filas en {elapsed:.1f}s "
                 f"({file_rows/elapsed:,.0f} filas/seg)")

    elapsed_total = time.time() - t0_total
    log.info(f"\n  TOTAL fact_vuelo: {total_rows:,} filas en {elapsed_total:.1f}s")
    log.info(f"  Velocidad promedio: {total_rows/elapsed_total:,.0f} filas/seg")


# ─── Post-carga: FK e índices ─────────────────────────────────────────────────

def apply_fk_and_indexes(conn):
    """
    FK e índices se crean DESPUÉS de la carga por dos razones:
    1. Cargar con índices activos es 3-5x más lento (PostgreSQL mantiene el índice en cada INSERT)
    2. Crear el índice de una vez sobre datos ya cargados usa bulk index build — más eficiente
    Esta decisión se documenta en technical-decisions.md
    """
    log.info("\n[Post-carga] Creando FK e índices...")
    t0 = time.time()

    statements = [
        # FK
        """ALTER TABLE dw.fact_vuelo
           ADD CONSTRAINT fk_fact_tiempo
           FOREIGN KEY (tiempo_sk) REFERENCES dw.dim_tiempo(tiempo_sk)""",

        """ALTER TABLE dw.fact_vuelo
           ADD CONSTRAINT fk_fact_aerolinea
           FOREIGN KEY (aerolinea_sk) REFERENCES dw.dim_aerolinea(aerolinea_sk)""",

        """ALTER TABLE dw.fact_vuelo
           ADD CONSTRAINT fk_fact_origen
           FOREIGN KEY (origen_sk) REFERENCES dw.dim_aeropuerto(aeropuerto_sk)""",

        """ALTER TABLE dw.fact_vuelo
           ADD CONSTRAINT fk_fact_destino
           FOREIGN KEY (destino_sk) REFERENCES dw.dim_aeropuerto(aeropuerto_sk)""",

        # Índice 1 — simple sobre aerolinea_sk
        # Motiva consulta: retraso promedio por aerolínea (KPI del dashboard)
        "CREATE INDEX idx_fact_aerolinea ON dw.fact_vuelo (aerolinea_sk)",

        # Índice 2 — compuesto flight_date + aerolinea_sk (requisito: al menos 1 compuesto)
        # Motiva consulta: tendencia mensual de retrasos por aerolínea
        "CREATE INDEX idx_fact_fecha_aerolinea ON dw.fact_vuelo (flight_date, aerolinea_sk)",

        # Índice 3 — simple sobre origen_sk
        # Motiva consulta: aeropuertos con más cancelaciones
        "CREATE INDEX idx_fact_origen ON dw.fact_vuelo (origen_sk)",
    ]

    with conn.cursor() as cur:
        for stmt in statements:
            nombre = stmt.strip().split("\n")[0][:60]
            log.info(f"  Ejecutando: {nombre}...")
            t_stmt = time.time()
            cur.execute(stmt)
            conn.commit()
            log.info(f"    Listo en {time.time()-t_stmt:.1f}s")

    log.info(f"  FK e índices creados en {time.time()-t0:.1f}s total")


# ─── Verificación post-carga ──────────────────────────────────────────────────

def verificar_carga(conn):
    log.info("\n[Verificación] Conteo por partición:")
    query = """
        SELECT tableoid::regclass AS particion,
               COUNT(*)           AS filas
        FROM dw.fact_vuelo
        GROUP BY tableoid
        ORDER BY particion;
    """
    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()
        total = 0
        for particion, filas in rows:
            log.info(f"  {particion:<40} {filas:>10,} filas")
            total += filas
        log.info(f"  {'TOTAL':<40} {total:>10,} filas")


# ─── Pipeline principal ───────────────────────────────────────────────────────

def run():
    log.info("=" * 60)
    log.info("INICIO — Carga a PostgreSQL")
    log.info(f"Base de datos: {DB_CONFIG['dbname']} en {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    log.info("=" * 60)

    t0_total = time.time()

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        log.info("Conexion a PostgreSQL exitosa")
    except Exception as e:
        log.error(f"No se pudo conectar a PostgreSQL: {e}")
        log.error("Verifica host, puerto, usuario y contraseña en DB_CONFIG")
        return

    try:
        load_dim_tiempo(conn)
        load_dim_aerolinea(conn)
        load_dim_aeropuerto(conn)
        load_fact_vuelo(conn)
        apply_fk_and_indexes(conn)
        verificar_carga(conn)

    except Exception as e:
        conn.rollback()
        log.error(f"Error durante la carga: {e}")
        raise
    finally:
        conn.close()

    elapsed = time.time() - t0_total
    log.info("\n" + "=" * 60)
    log.info("CARGA COMPLETA")
    log.info(f"Tiempo total: {elapsed/60:.1f} minutos")
    log.info("Siguiente paso: ejecutar queries_analyze.sql en pgAdmin")
    log.info("=" * 60)


if __name__ == "__main__":
    run()
