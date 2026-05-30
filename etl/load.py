"""
load.py — Carga por lotes a PostgreSQL usando COPY

Proyecto: Airline On-Time Performance (BTS) 2023-2024

Este script realiza la fase L del pipeline ETL:
1. Ejecuta sql/ddl_schema.sql para crear el esquema DW desde cero.
2. Carga dimensiones desde staging/transformed.
3. Carga fact_vuelo desde archivos Parquet mensuales.
4. Verifica conteo final por partición.

Uso:
    python etl/load.py

Nota:
    ddl_schema.sql contiene DROP SCHEMA IF EXISTS dw CASCADE,
    por lo tanto este script reconstruye el esquema dw al ejecutarse.
"""

import io
import os
import time
import logging
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import psycopg2


# ─── RUTAS DEL PROYECTO ───────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSFORMED_DIR = PROJECT_ROOT / "staging" / "transformed"
DDL_FILE = PROJECT_ROOT / "sql" / "ddl_schema.sql"
LOG_DIR = PROJECT_ROOT / "staging"
LOG_DIR.mkdir(parents=True, exist_ok=True)


# ─── CONFIGURACIÓN DE BASE DE DATOS ───────────────────────────────────────────
# Permite usar variables de entorno si se quiere probar otro puerto o base.
# Si no se definen, usa los valores por defecto del proyecto.

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "5433")),
    "dbname": os.getenv("DB_NAME", "airline_dw"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
}


CHUNK_SIZE = 50_000


# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "load.log", encoding="utf-8"),
    ],
)

log = logging.getLogger(__name__)


# ─── VALIDACIONES INICIALES ───────────────────────────────────────────────────

def validar_archivos():
    """
    Verifica que existan los archivos necesarios antes de intentar cargar.
    """
    if not DDL_FILE.exists():
        raise FileNotFoundError(f"No existe el archivo DDL: {DDL_FILE}")

    if not TRANSFORMED_DIR.exists():
        raise FileNotFoundError(
            f"No existe la carpeta transformada: {TRANSFORMED_DIR}. "
            "Ejecuta primero python etl/transform.py"
        )

    requeridos = [
        TRANSFORMED_DIR / "dim_tiempo.parquet",
        TRANSFORMED_DIR / "dim_aerolinea.parquet",
        TRANSFORMED_DIR / "dim_aeropuerto.parquet",
    ]

    for archivo in requeridos:
        if not archivo.exists():
            raise FileNotFoundError(
                f"Falta archivo requerido: {archivo}. "
                "Ejecuta primero python etl/transform.py"
            )

    fact_dir = TRANSFORMED_DIR / "fact_vuelo"
    if not fact_dir.exists() or not list(fact_dir.glob("*.parquet")):
        raise FileNotFoundError(
            f"No se encontraron archivos Parquet de fact_vuelo en: {fact_dir}. "
            "Ejecuta primero python etl/transform.py"
        )


# ─── EJECUCIÓN DEL DDL ────────────────────────────────────────────────────────

def ejecutar_ddl(conn):
    """
    Ejecuta sql/ddl_schema.sql desde Python.

    Esto permite cumplir con la consigna de que el proceso de carga cree
    el esquema, tablas, particiones, llaves e índices sin hacerlo manualmente.
    """
    log.info("\n[DDL] Ejecutando sql/ddl_schema.sql...")
    log.warning("Esto reconstruirá el esquema dw si ddl_schema.sql contiene DROP SCHEMA.")

    t0 = time.time()

    ddl_sql = DDL_FILE.read_text(encoding="utf-8")

    with conn.cursor() as cur:
        cur.execute(ddl_sql)

    conn.commit()

    log.info(f"[DDL] Esquema creado correctamente en {time.time() - t0:.1f}s")


# ─── COPY HELPER ──────────────────────────────────────────────────────────────

def copy_dataframe(conn, df: pd.DataFrame, table: str, schema: str = "dw"):
    """
    Carga un DataFrame a PostgreSQL usando COPY FROM STDIN.
    Es más rápido que hacer INSERT fila por fila.
    """
    buffer = io.StringIO()
    df.to_csv(buffer, index=False, header=False, na_rep="\\N")
    buffer.seek(0)

    full_table = f"{schema}.{table}"
    cols = ", ".join(df.columns.tolist())

    with conn.cursor() as cur:
        copy_sql = (
            f"COPY {full_table} ({cols}) "
            f"FROM STDIN WITH (FORMAT CSV, NULL '\\N')"
        )
        cur.copy_expert(copy_sql, buffer)

    conn.commit()


# ─── LOADERS DE DIMENSIONES ───────────────────────────────────────────────────

def load_dim_tiempo(conn):
    log.info("\n[1/4] Cargando dim_tiempo...")
    t0 = time.time()

    df = pd.read_parquet(TRANSFORMED_DIR / "dim_tiempo.parquet")
    copy_dataframe(conn, df, "dim_tiempo")

    log.info(f"  {len(df):,} filas cargadas en {time.time() - t0:.1f}s")


def load_dim_aerolinea(conn):
    log.info("\n[2/4] Cargando dim_aerolinea...")
    t0 = time.time()

    df = pd.read_parquet(TRANSFORMED_DIR / "dim_aerolinea.parquet")
    copy_dataframe(conn, df, "dim_aerolinea")

    log.info(f"  {len(df):,} filas cargadas en {time.time() - t0:.1f}s")


def load_dim_aeropuerto(conn):
    log.info("\n[3/4] Cargando dim_aeropuerto...")
    t0 = time.time()

    df = pd.read_parquet(TRANSFORMED_DIR / "dim_aeropuerto.parquet")
    copy_dataframe(conn, df, "dim_aeropuerto")

    log.info(f"  {len(df):,} filas cargadas en {time.time() - t0:.1f}s")


# ─── LOAD FACT_VUELO ──────────────────────────────────────────────────────────

def load_fact_vuelo(conn):
    """
    Carga fact_vuelo desde los archivos Parquet mensuales generados por transform.py.
    Se procesa por lotes para no saturar memoria.
    """
    log.info("\n[4/4] Cargando fact_vuelo...")

    fact_dir = TRANSFORMED_DIR / "fact_vuelo"
    parquets = sorted(fact_dir.glob("*.parquet"))

    log.info(f"  Archivos Parquet encontrados: {len(parquets)}")

    total_rows = 0
    t0_total = time.time()

    # Columnas en el orden del DDL, sin flight_sk porque es IDENTITY.
    FACT_COLS = [
        "tiempo_sk",
        "aerolinea_sk",
        "origen_sk",
        "destino_sk",
        "flight_date",
        "dep_delay",
        "arr_delay",
        "air_time",
        "distance",
        "cancelled",
        "cancellation_code",
        "diverted",
        "carrier_delay",
        "weather_delay",
        "nas_delay",
        "security_delay",
        "late_aircraft_delay",
        "taxi_out",
        "taxi_in",
    ]

    for parquet_file in parquets:
        log.info(f"  Cargando: {parquet_file.name}")

        t0_file = time.time()
        file_rows = 0

        parquet_obj = pq.ParquetFile(parquet_file)

        for batch in parquet_obj.iter_batches(batch_size=CHUNK_SIZE):
            chunk = batch.to_pandas()

            chunk = chunk[[c for c in FACT_COLS if c in chunk.columns]]

            chunk["flight_date"] = pd.to_datetime(chunk["flight_date"]).dt.date
            chunk["cancelled"] = chunk["cancelled"].astype(int)
            chunk["diverted"] = chunk["diverted"].astype(int)
            chunk["cancellation_code"] = chunk["cancellation_code"].fillna("N/A")

            copy_dataframe(conn, chunk, "fact_vuelo")

            file_rows += len(chunk)
            total_rows += len(chunk)

        elapsed = time.time() - t0_file
        velocidad = file_rows / elapsed if elapsed > 0 else 0

        log.info(
            f"    {file_rows:,} filas en {elapsed:.1f}s "
            f"({velocidad:,.0f} filas/seg)"
        )

    elapsed_total = time.time() - t0_total
    velocidad_total = total_rows / elapsed_total if elapsed_total > 0 else 0

    log.info(f"\n  TOTAL fact_vuelo: {total_rows:,} filas en {elapsed_total:.1f}s")
    log.info(f"  Velocidad promedio: {velocidad_total:,.0f} filas/seg")


# ─── VERIFICACIÓN POST-CARGA ──────────────────────────────────────────────────

def verificar_carga(conn):
    log.info("\n[Verificación] Conteo por tabla:")

    queries = {
        "dw.dim_tiempo": "SELECT COUNT(*) FROM dw.dim_tiempo",
        "dw.dim_aerolinea": "SELECT COUNT(*) FROM dw.dim_aerolinea",
        "dw.dim_aeropuerto": "SELECT COUNT(*) FROM dw.dim_aeropuerto",
        "dw.fact_vuelo": "SELECT COUNT(*) FROM dw.fact_vuelo",
    }

    with conn.cursor() as cur:
        for nombre, query in queries.items():
            cur.execute(query)
            filas = cur.fetchone()[0]
            log.info(f"  {nombre:<25} {filas:>12,} filas")

    log.info("\n[Verificación] Conteo por partición de fact_vuelo:")

    query_particiones = """
        SELECT tableoid::regclass AS particion, COUNT(*) AS filas
        FROM dw.fact_vuelo
        GROUP BY tableoid
        ORDER BY particion;
    """

    with conn.cursor() as cur:
        cur.execute(query_particiones)
        rows = cur.fetchall()

        total = 0
        for particion, filas in rows:
            log.info(f"  {str(particion):<40} {filas:>10,} filas")
            total += filas

        log.info(f"  {'TOTAL':<40} {total:>10,} filas")


# ─── PIPELINE PRINCIPAL ───────────────────────────────────────────────────────

def run():
    log.info("=" * 70)
    log.info("INICIO — Carga a PostgreSQL")
    log.info(
        f"Base de datos: {DB_CONFIG['dbname']} "
        f"en {DB_CONFIG['host']}:{DB_CONFIG['port']}"
    )
    log.info("=" * 70)

    t0_total = time.time()

    try:
        validar_archivos()
    except Exception as e:
        log.error(f"Validación fallida: {e}")
        return

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        log.info("Conexión a PostgreSQL exitosa")
    except Exception as e:
        log.error(f"No se pudo conectar a PostgreSQL: {e}")
        log.error("Verifica host, puerto, usuario y contraseña en DB_CONFIG")
        return

    try:
        ejecutar_ddl(conn)

        load_dim_tiempo(conn)
        load_dim_aerolinea(conn)
        load_dim_aeropuerto(conn)
        load_fact_vuelo(conn)

        verificar_carga(conn)

    except Exception as e:
        conn.rollback()
        log.error(f"Error durante la carga: {e}")
        raise

    finally:
        conn.close()

    elapsed = time.time() - t0_total

    log.info("\n" + "=" * 70)
    log.info("CARGA COMPLETA")
    log.info(f"Tiempo total: {elapsed / 60:.1f} minutos")
    log.info("Siguiente paso: ejecutar sql/queries_analyze.sql")
    log.info("=" * 70)


if __name__ == "__main__":
    run()
