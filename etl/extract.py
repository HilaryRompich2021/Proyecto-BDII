"""
extract.py — Descarga automatizada del dataset Airline On-Time Performance (BTS)
Dataset: Marketing Carrier On-Time Performance (desde enero 2018)
Fuente: https://transtats.bts.gov/PREZIP/
Uso: python etl/extract.py
"""

import os
import zipfile
import requests
import time
import logging
from pathlib import Path

# ─── Configuración ────────────────────────────────────────────────────────────

# Años y meses a descargar (2 años = ~12–14M registros, nivel "Recomendado")
YEARS  = [2023, 2024]
MONTHS = list(range(1, 13))  # 1 a 12

# Directorios de salida
RAW_DIR     = Path("staging/raw")       # ZIPs descargados
EXTRACT_DIR = Path("staging/extracted") # CSVs descomprimidos

# URL base del BTS (patrón verificado)
BASE_URL = (
    "https://transtats.bts.gov/PREZIP/"
    "On_Time_Marketing_Carrier_On_Time_Performance_"
    "Beginning_January_2018_{year}_{month}.zip"
)

# Reintentos en caso de fallo de red
MAX_RETRIES = 3
RETRY_DELAY = 5  # segundos entre reintentos

# ─── Logging ──────────────────────────────────────────────────────────────────

# Asegurar que el directorio del log exista antes de configurarlo
Path("staging").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("staging/extract.log"),
    ],
)
log = logging.getLogger(__name__)

# ─── Funciones ────────────────────────────────────────────────────────────────

def setup_dirs():
    """Crea los directorios necesarios si no existen."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    log.info(f"Directorios listos: {RAW_DIR}, {EXTRACT_DIR}")


def download_zip(year: int, month: int) -> Path | None:
    """
    Descarga el ZIP de un mes/año específico.
    Retorna la ruta al archivo descargado, o None si falló.
    Omite la descarga si el archivo ya existe (reanudable).
    """
    url      = BASE_URL.format(year=year, month=month)
    filename = f"ontime_{year}_{month:02d}.zip"
    dest     = RAW_DIR / filename

    if dest.exists():
        log.info(f"  Ya existe, omitiendo: {filename}")
        return dest

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log.info(f"  Descargando {year}-{month:02d} (intento {attempt})...")
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()

            with open(dest, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            size_mb = dest.stat().st_size / (1024 ** 2)
            log.info(f"  ✓ Descargado: {filename} ({size_mb:.1f} MB)")
            return dest

        except requests.RequestException as e:
            log.warning(f"  Intento {attempt} fallido: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                log.error(f"  ✗ No se pudo descargar {filename} tras {MAX_RETRIES} intentos")
                return None


def extract_zip(zip_path: Path) -> list[Path]:
    """
    Descomprime un ZIP en EXTRACT_DIR.
    Retorna lista de rutas a los CSVs extraídos.
    Omite si el CSV ya existe.
    """
    extracted = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if not member.endswith(".csv"):
                continue  # ignorar readme.txt y otros

            dest_csv = EXTRACT_DIR / Path(member).name

            if dest_csv.exists():
                log.info(f"  CSV ya existe, omitiendo: {dest_csv.name}")
                extracted.append(dest_csv)
                continue

            log.info(f"  Extrayendo: {member}")
            zf.extract(member, EXTRACT_DIR)

            # Mover al nivel raíz de EXTRACT_DIR si quedó en subcarpeta
            extracted_path = EXTRACT_DIR / member
            if extracted_path != dest_csv and extracted_path.exists():
                extracted_path.rename(dest_csv)

            extracted.append(dest_csv)

    return extracted


def run():
    """Pipeline principal de extracción."""
    log.info("=" * 60)
    log.info("INICIO — Extracción Airline On-Time Performance (BTS)")
    log.info(f"Años: {YEARS}  |  Meses: 1–12")
    log.info("=" * 60)

    setup_dirs()

    total_files  = 0
    failed_files = []
    all_csvs     = []

    for year in YEARS:
        for month in MONTHS:
            log.info(f"\n[{year}-{month:02d}]")

            zip_path = download_zip(year, month)
            if zip_path is None:
                failed_files.append(f"{year}-{month:02d}")
                continue

            csvs = extract_zip(zip_path)
            all_csvs.extend(csvs)
            total_files += 1

    # ─── Resumen ──────────────────────────────────────────────────────────────
    log.info("\n" + "=" * 60)
    log.info("RESUMEN DE EXTRACCIÓN")
    log.info(f"  Archivos descargados y extraídos: {total_files}")
    log.info(f"  CSVs disponibles en staging:      {len(all_csvs)}")

    if failed_files:
        log.warning(f"  Meses fallidos ({len(failed_files)}): {', '.join(failed_files)}")
    else:
        log.info("  Sin errores de descarga ✓")

    log.info(f"\nCSVs listos para transform.py en: {EXTRACT_DIR.resolve()}")
    log.info("=" * 60)

    # Guardar lista de CSVs para que transform.py los lea fácilmente
    manifest = RAW_DIR / "manifest.txt"
    with open(manifest, "w") as f:
        for csv_path in sorted(all_csvs):
            f.write(str(csv_path.resolve()) + "\n")
    log.info(f"Manifiesto de archivos guardado en: {manifest}")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run()
