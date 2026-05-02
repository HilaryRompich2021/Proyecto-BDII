"""
transform.py — Limpieza, construcción de dimensiones y tabla de hechos
Dataset: Airline On-Time Performance (BTS) 2023–2024
Uso: python etl/transform.py

Problemas de calidad documentados y resueltos:
  1. Columna 'Operating_Airline ' tiene espacio en el nombre → se renombra
  2. Columna 'Unnamed: 119' es artefacto del CSV → se elimina
  3. Columnas Div1–Div5 son casi 100% nulas → se eliminan, se agrega flag
  4. 'CancellationCode' es nulo cuando Cancelled=0 → se imputa con 'N/A'
  5. ArrDelay/DepDelay nulos en vuelos cancelados → se imputan con 0
  6. Tipos incorrectos: FlightDate viene como string → se convierte a date
"""

import os
import logging
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path

# ─── Configuración ────────────────────────────────────────────────────────────

EXTRACTED_DIR  = Path("staging/extracted")
TRANSFORMED_DIR = Path("staging/transformed")

CHUNK_SIZE = 200_000  # filas por chunk (control de memoria)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("staging/transform.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ─── Columnas a conservar del CSV original ────────────────────────────────────

COLS_KEEP = [
    # Fecha (columna de partición y dim_tiempo)
    "FlightDate",
    # Aerolínea
    "Marketing_Airline_Network",
    "IATA_Code_Marketing_Airline",
    # Aeropuerto origen
    "Origin",
    "OriginCityName",
    "OriginState",
    "OriginStateName",
    # Aeropuerto destino
    "Dest",
    "DestCityName",
    "DestState",
    "DestStateName",
    # Métricas de la tabla de hechos
    "DepDelay",
    "ArrDelay",
    "AirTime",
    "Distance",
    "Cancelled",
    "CancellationCode",
    "Diverted",
    "CarrierDelay",
    "WeatherDelay",
    "NASDelay",
    "SecurityDelay",
    "LateAircraftDelay",
    "TaxiOut",
    "TaxiIn",
]

# ─── Helpers ──────────────────────────────────────────────────────────────────

def limpiar_chunk(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aplica todas las transformaciones de calidad de datos a un chunk.
    Documenta 6 tipos de problemas resueltos.
    """

    # PROBLEMA 1: Columna con espacio en el nombre
    df.columns = df.columns.str.strip()

    # Seleccionar solo columnas relevantes
    cols_disponibles = [c for c in COLS_KEEP if c in df.columns]
    df = df[cols_disponibles].copy()

    # PROBLEMA 2: Unnamed/columnas fantasma — ya eliminadas al seleccionar cols

    # PROBLEMA 3: FlightDate como string → convertir a date
    df["FlightDate"] = pd.to_datetime(df["FlightDate"], errors="coerce").dt.date

    # PROBLEMA 4: ArrDelay y DepDelay nulos en vuelos cancelados → imputar con 0
    df["ArrDelay"]   = df["ArrDelay"].fillna(0.0)
    df["DepDelay"]   = df["DepDelay"].fillna(0.0)
    df["TaxiOut"]    = df["TaxiOut"].fillna(0.0)
    df["TaxiIn"]     = df["TaxiIn"].fillna(0.0)
    df["AirTime"]    = df["AirTime"].fillna(0.0)

    # PROBLEMA 5: CancellationCode nulo cuando Cancelled=0 → imputar con 'N/A'
    df["CancellationCode"] = df["CancellationCode"].fillna("N/A")

    # PROBLEMA 6: Columnas de causa de retraso nulas cuando no hay retraso → 0
    for col in ["CarrierDelay", "WeatherDelay", "NASDelay", "SecurityDelay", "LateAircraftDelay"]:
        if col in df.columns:
            df[col] = df[col].fillna(0.0)

    # Eliminar filas donde FlightDate no se pudo parsear
    df = df.dropna(subset=["FlightDate"])

    return df


def build_dim_tiempo(fechas: set) -> pd.DataFrame:
    """
    Construye dim_tiempo con granularidad de día.
    Columnas: fecha, dia, mes, nombre_mes, trimestre, anio, dia_semana, nombre_dia, es_fin_de_semana
    """
    fechas_dt = pd.to_datetime(sorted(fechas))
    dim = pd.DataFrame({"fecha": fechas_dt})

    dim["dia"]           = dim["fecha"].dt.day
    dim["mes"]           = dim["fecha"].dt.month
    dim["nombre_mes"]    = dim["fecha"].dt.strftime("%B")
    dim["trimestre"]     = dim["fecha"].dt.quarter
    dim["anio"]          = dim["fecha"].dt.year
    dim["dia_semana"]    = dim["fecha"].dt.dayofweek + 1  # 1=Lunes, 7=Domingo
    dim["nombre_dia"]    = dim["fecha"].dt.strftime("%A")
    dim["es_fin_semana"] = dim["dia_semana"].isin([6, 7])
    dim["fecha"]         = dim["fecha"].dt.date

    # Surrogate key generada en Python
    dim.insert(0, "tiempo_sk", range(1, len(dim) + 1))

    return dim


def build_dim_aerolinea(df: pd.DataFrame) -> pd.DataFrame:
    """
    Construye dim_aerolinea con surrogate key.
    """
    dim = (
        df[["IATA_Code_Marketing_Airline", "Marketing_Airline_Network"]]
        .drop_duplicates()
        .dropna()
        .reset_index(drop=True)
    )
    dim.columns = ["iata_code", "nombre_aerolinea"]
    dim.insert(0, "aerolinea_sk", range(1, len(dim) + 1))
    return dim


def build_dim_aeropuerto(df: pd.DataFrame) -> pd.DataFrame:
    """
    Construye dim_aeropuerto unificada para origen y destino.
    Una sola tabla usada dos veces en la fact (role-playing dimension).
    """
    origen = df[["Origin", "OriginCityName", "OriginState", "OriginStateName"]].copy()
    origen.columns = ["iata_code", "ciudad", "estado_codigo", "estado_nombre"]

    destino = df[["Dest", "DestCityName", "DestState", "DestStateName"]].copy()
    destino.columns = ["iata_code", "ciudad", "estado_codigo", "estado_nombre"]

    dim = (
        pd.concat([origen, destino])
        .drop_duplicates(subset=["iata_code"])
        .dropna(subset=["iata_code"])
        .reset_index(drop=True)
    )
    dim.insert(0, "aeropuerto_sk", range(1, len(dim) + 1))
    return dim


def build_fact(df: pd.DataFrame,
               dim_tiempo: pd.DataFrame,
               dim_aerolinea: pd.DataFrame,
               dim_aeropuerto: pd.DataFrame) -> pd.DataFrame:
    """
    Construye fact_vuelo con FKs a las dimensiones.
    """
    # Mapas de lookup para FKs
    tiempo_map     = dict(zip(dim_tiempo["fecha"], dim_tiempo["tiempo_sk"]))
    aerolinea_map  = dict(zip(dim_aerolinea["iata_code"], dim_aerolinea["aerolinea_sk"]))
    aeropuerto_map = dict(zip(dim_aeropuerto["iata_code"], dim_aeropuerto["aeropuerto_sk"]))

    fact = pd.DataFrame()
    fact["tiempo_sk"]     = df["FlightDate"].map(tiempo_map)
    fact["aerolinea_sk"]  = df["IATA_Code_Marketing_Airline"].map(aerolinea_map)
    fact["origen_sk"]     = df["Origin"].map(aeropuerto_map)
    fact["destino_sk"]    = df["Dest"].map(aeropuerto_map)
    fact["flight_date"]   = df["FlightDate"]   # columna de partición en PostgreSQL

    # Métricas
    fact["dep_delay"]          = df["DepDelay"].astype(float)
    fact["arr_delay"]          = df["ArrDelay"].astype(float)
    fact["air_time"]           = df["AirTime"].astype(float)
    fact["distance"]           = df["Distance"].astype(float)
    fact["cancelled"]          = df["Cancelled"].astype(int)
    fact["cancellation_code"]  = df["CancellationCode"]
    fact["diverted"]           = df["Diverted"].astype(int)
    fact["carrier_delay"]      = df["CarrierDelay"].astype(float)
    fact["weather_delay"]      = df["WeatherDelay"].astype(float)
    fact["nas_delay"]          = df["NASDelay"].astype(float)
    fact["security_delay"]     = df["SecurityDelay"].astype(float)
    fact["late_aircraft_delay"]= df["LateAircraftDelay"].astype(float)
    fact["taxi_out"]           = df["TaxiOut"].astype(float)
    fact["taxi_in"]            = df["TaxiIn"].astype(float)

    # Eliminar filas con FKs nulas (no se pudo hacer lookup)
    fact = fact.dropna(subset=["tiempo_sk", "aerolinea_sk", "origen_sk", "destino_sk"])

    return fact


# ─── Pipeline principal ───────────────────────────────────────────────────────

def run():
    log.info("=" * 60)
    log.info("INICIO — Transformación y construcción de dimensiones")
    log.info("=" * 60)

    TRANSFORMED_DIR.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(EXTRACTED_DIR.glob("*.csv"))
    if not csv_files:
        log.error(f"No se encontraron CSVs en {EXTRACTED_DIR}. Ejecuta extract.py primero.")
        return

    log.info(f"Archivos CSV encontrados: {len(csv_files)}")

    # ── PASADA 1: construir dimensiones acumulando SOLO las columnas necesarias ──
    # No se acumula la tabla completa — solo los valores únicos para cada dimensión.
    # Esto usa <50 MB de RAM independientemente del volumen total.
    log.info("\n[1/3] Pasada 1 — recolectando valores únicos para dimensiones...")

    fechas_set      = set()
    aerolinea_rows  = {}   # iata_code → nombre
    aeropuerto_rows = {}   # iata_code → {ciudad, estado_codigo, estado_nombre}
    total_rows      = 0

    for csv_file in csv_files:
        log.info(f"  Escaneando: {csv_file.name}")
        for chunk in pd.read_csv(csv_file, chunksize=CHUNK_SIZE, low_memory=False):
            chunk = limpiar_chunk(chunk)
            total_rows += len(chunk)

            # Fechas únicas
            fechas_set.update(chunk["FlightDate"].dropna().unique())

            # Aerolíneas únicas
            for _, row in chunk[["IATA_Code_Marketing_Airline", "Marketing_Airline_Network"]].drop_duplicates().iterrows():
                if pd.notna(row["IATA_Code_Marketing_Airline"]):
                    aerolinea_rows[row["IATA_Code_Marketing_Airline"]] = row["Marketing_Airline_Network"]

            # Aeropuertos únicos (origen + destino)
            for col_code, col_city, col_st, col_stname in [
                ("Origin", "OriginCityName", "OriginState", "OriginStateName"),
                ("Dest",   "DestCityName",   "DestState",   "DestStateName"),
            ]:
                sub = chunk[[col_code, col_city, col_st, col_stname]].drop_duplicates()
                for _, row in sub.iterrows():
                    code = row[col_code]
                    if pd.notna(code) and code not in aeropuerto_rows:
                        aeropuerto_rows[code] = {
                            "ciudad":        row[col_city],
                            "estado_codigo": row[col_st],
                            "estado_nombre": row[col_stname],
                        }

    log.info(f"  Total filas procesadas: {total_rows:,}")

    # ── Construir DataFrames de dimensiones ──────────────────────────────────
    log.info("\n[2/3] Construyendo tablas dimensionales...")

    dim_tiempo = build_dim_tiempo(fechas_set)

    dim_aerolinea = pd.DataFrame([
        {"iata_code": k, "nombre_aerolinea": v}
        for k, v in aerolinea_rows.items()
    ]).reset_index(drop=True)
    dim_aerolinea.insert(0, "aerolinea_sk", range(1, len(dim_aerolinea) + 1))

    dim_aeropuerto = pd.DataFrame([
        {"iata_code": k, **v}
        for k, v in aeropuerto_rows.items()
    ]).reset_index(drop=True)
    dim_aeropuerto.insert(0, "aeropuerto_sk", range(1, len(dim_aeropuerto) + 1))

    log.info(f"  dim_tiempo:     {len(dim_tiempo):,} filas")
    log.info(f"  dim_aerolinea:  {len(dim_aerolinea):,} filas")
    log.info(f"  dim_aeropuerto: {len(dim_aeropuerto):,} filas")

    dim_tiempo.to_parquet(TRANSFORMED_DIR / "dim_tiempo.parquet",       index=False)
    dim_aerolinea.to_parquet(TRANSFORMED_DIR / "dim_aerolinea.parquet",   index=False)
    dim_aeropuerto.to_parquet(TRANSFORMED_DIR / "dim_aeropuerto.parquet", index=False)
    log.info("  Dimensiones guardadas en staging/transformed/")

    # ── PASADA 2: construir fact_vuelo chunk a chunk, escribir Parquet incremental ──
    # Nunca se carga más de CHUNK_SIZE filas en RAM a la vez.
    log.info("\n[3/3] Pasada 2 — construyendo fact_vuelo chunk a chunk...")

    fact_dir = TRANSFORMED_DIR / "fact_vuelo"
    fact_dir.mkdir(exist_ok=True)

    tiempo_map     = dict(zip(dim_tiempo["fecha"],          dim_tiempo["tiempo_sk"]))
    aerolinea_map  = dict(zip(dim_aerolinea["iata_code"],   dim_aerolinea["aerolinea_sk"]))
    aeropuerto_map = dict(zip(dim_aeropuerto["iata_code"],  dim_aeropuerto["aeropuerto_sk"]))

    total_fact_rows = 0
    part_writers    = {}   # (anio, mes) → ParquetWriter

    for csv_file in csv_files:
        log.info(f"  Procesando: {csv_file.name}")
        for chunk in pd.read_csv(csv_file, chunksize=CHUNK_SIZE, low_memory=False):
            chunk = limpiar_chunk(chunk)
            fact  = build_fact(chunk, dim_tiempo, dim_aerolinea, dim_aeropuerto)

            if fact.empty:
                continue

            # Agrupar por año/mes y escribir cada grupo en su archivo Parquet
            fact["anio"] = pd.to_datetime(fact["flight_date"]).dt.year
            fact["mes"]  = pd.to_datetime(fact["flight_date"]).dt.month

            for (anio, mes), grupo in fact.groupby(["anio", "mes"]):
                grupo = grupo.drop(columns=["anio", "mes"])
                key   = (anio, mes)
                tabla = pa.Table.from_pandas(grupo, preserve_index=False)

                if key not in part_writers:
                    dest = fact_dir / f"fact_{anio}_{mes:02d}.parquet"
                    part_writers[key] = pq.ParquetWriter(str(dest), tabla.schema)

                part_writers[key].write_table(tabla)
                total_fact_rows += len(grupo)

    # Cerrar todos los writers
    for writer in part_writers.values():
        writer.close()

    log.info("\n" + "=" * 60)
    log.info("TRANSFORMACION COMPLETA")
    log.info(f"  Total registros en fact_vuelo: {total_fact_rows:,}")
    log.info(f"  Archivos Parquet generados:    {len(part_writers)}")
    log.info("  Siguiente paso: python etl/load.py")
    log.info("=" * 60)


if __name__ == "__main__":
    run()
