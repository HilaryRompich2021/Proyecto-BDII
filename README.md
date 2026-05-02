# Proyecto Final — Base de Datos II (031)
**Universidad Mariano Gálvez de Guatemala**  
Facultad de Ingeniería en Sistemas de Información y Ciencias de la Computación

---

## Dataset

**Fuente:** Airline On-Time Performance — Bureau of Transportation Statistics (BTS / U.S. DOT)  
**Años:** 2023 y 2024 (24 meses completos)  
**Volumen:** 14,825,707 registros en `fact_vuelo`  
**URL base de descarga:**
```
https://transtats.bts.gov/PREZIP/On_Time_Marketing_Carrier_On_Time_Performance_Beginning_January_2018_{year}_{month}.zip
```

---

## Preguntas de negocio del dashboard

> Definidas antes de construir el dashboard — requisito del proyecto

1. ¿Qué aerolínea tiene el mayor retraso promedio de llegada en 2023–2024?
2. ¿Cuál es la tendencia mensual de retrasos a lo largo de los dos años?
3. ¿Qué aeropuertos de origen concentran más cancelaciones?
4. ¿Qué causa de retraso (clima, aerolínea, NAS, aeronave tardía) es más frecuente por trimestre?

---

## Estructura del repositorio

```
PROYECTO-BDII/
├── docs/
│   ├── airline_dashboard.pdf     # capturas del dashboard como respaldo
│   ├── model_diagram.png         # diagrama dimensional del esquema estrella
│   ├── technical-decisions.md    # decisiones técnicas con evidencia EXPLAIN ANALYZE
│   └── dashboard-doc.md          # documentación de cada visualización del dashboard
├── etl/
│   ├── extract.py                # descarga 24 ZIPs de BTS automáticamente
│   ├── transform.py              # limpieza, dimensiones, surrogate keys → Parquet
│   └── load.py                   # ejecuta DDL + carga COPY + índices + FK
├── sql/
│   ├── ddl_schema.sql            # CREATE TABLE + 24 particiones (ejecutado por load.py)
│   └── queries_analyze.sql       # consultas EXPLAIN ANALYZE (ejecución manual en pgAdmin)
├── staging/                      # generado automáticamente por el pipeline
│   ├── raw/                      # ZIPs descargados por extract.py
│   ├── extracted/                # CSVs descomprimidos por extract.py
│   ├── transformed/              # Parquets generados por transform.py
│   │   ├── dim_aerolinea.parquet
│   │   ├── dim_aeropuerto.parquet
│   │   ├── dim_tiempo.parquet
│   │   └── fact_vuelo/           # 24 archivos fact_YYYY_MM.parquet
│   ├── extract.log               # log de descarga
│   ├── transform.log             # log de transformación
│   └── load.log                  # log de carga (incluye tiempo total)
├── airline_dashboard.twb         # dashboard Tableau (requiere PostgreSQL activo)
├── requirements.txt
└── README.md
```

---

## Requisitos

**Software necesario:**
- Python 3.9+
- PostgreSQL 14+ instalado localmente
- Tableau Desktop (para abrir `airline_dashboard.twb`)

**Instalar dependencias Python:**
```bash
pip install -r requirements.txt
```

**Contenido de `requirements.txt`:**
```
requests
pandas
pyarrow
psycopg2-binary
```

---

## Configuración antes de ejecutar

**Paso 1 — Crear la base de datos en PostgreSQL:**
```sql
CREATE DATABASE airline_dw;
```

**Paso 2 — Configurar credenciales en `etl/load.py`:**

Editar las primeras líneas de `load.py`:
```python
DB_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "airline_dw",
    "user":     "postgres",
    "password": "tu_contraseña",  # ← cambiar aquí
}
```

---

## Ejecución del pipeline completo

El pipeline se ejecuta en tres pasos en orden. Desde la raíz del proyecto:

```bash
python etl/extract.py
python etl/transform.py
python etl/load.py
```

O en una sola línea:
```bash
python etl/extract.py && python etl/transform.py && python etl/load.py
```

> **Importante:** El pipeline debe ejecutarse desde la carpeta raíz `PROYECTO-BDII/`, no desde dentro de `etl/`. Los scripts referencian rutas relativas como `staging/` y `sql/ddl_schema.sql`.

### ¿Esto es el pipeline ETL?

Sí. Los tres scripts constituyen el pipeline ETL completo:

- **`extract.py`** = fase de **Extracción** — descarga los datos de la fuente
- **`transform.py`** = fase de **Transformación** — limpia y modela los datos
- **`load.py`** = fase de **Carga** — carga a PostgreSQL y configura el DW

`load.py` además ejecuta automáticamente:
1. `sql/ddl_schema.sql` — crea el esquema, tablas y 24 particiones
2. Carga las 3 dimensiones con `COPY FROM STDIN`
3. Carga `fact_vuelo` (14.8M filas) con `COPY` por lotes de 50,000 filas
4. Crea los 3 índices (bulk build post-carga)
5. Crea las 4 FK (post-índices)
6. Verifica conteo por partición

### Tiempos estimados en máquina local estándar (8 GB RAM, SSD)

| Paso | Tiempo estimado |
|---|---|
| `extract.py` — descarga 24 ZIPs (~700 MB) | 30–60 min (depende de conexión) |
| `transform.py` — limpieza + Parquets | 15–25 min |
| `load.py` — DDL + COPY + índices + FK | 25–45 min |
| **Total pipeline** | **~70–130 min** |

> El tiempo exacto de carga queda registrado en `staging/load.log` al finalizar `load.py`.

---

## Modelo dimensional

Esquema estrella — 1 tabla de hechos, 3 dimensiones:

![Diagrama dimensional](docs/model_diagram.png)

| Tabla | Filas | Descripción |
|---|---|---|
| `fact_vuelo` | 14,825,707 | Particionada mensualmente por `flight_date` |
| `dim_tiempo` | 730 | Granularidad de día: fecha, dia, mes, trimestre, anio, dia_semana |
| `dim_aerolinea` | 10 | Aerolínea de marketing |
| `dim_aeropuerto` | 388 | Role-playing dimension: usada como origen y destino |

---

## Particionamiento e índices

**Particionamiento:** `PARTITION BY RANGE (flight_date)` — granularidad mensual, 24 particiones.

**Partition pruning demostrado:**
- Sin filtro: 24 particiones, 1,566 ms
- Con `WHERE flight_date BETWEEN '2024-01-01' AND '2024-03-31'`: 3 particiones, 220 ms → **86% más rápido**

**Índices creados automáticamente por `load.py`:**

| Índice | Tipo | Consulta que lo motiva |
|---|---|---|
| `idx_fact_aerolinea` | Simple | Retraso promedio por aerolínea |
| `idx_fact_fecha_aerolinea` | **Compuesto** | Tendencia mensual por aerolínea |
| `idx_fact_origen` | Simple | Aeropuertos con más cancelaciones |

Ver evidencia completa en `docs/technical-decisions.md`.

---

## Dashboard

**Archivo:** `airline_dashboard.twb`  
**Herramienta:** Tableau Desktop  
**Conexión:** Directamente a PostgreSQL — esquema `dw`, base de datos `airline_dw`

> Para abrir el dashboard PostgreSQL debe estar activo con los datos cargados.

**Visualizaciones:**
1. Tendencia mensual de retrasos (línea temporal 2023–2024)
2. Retraso promedio por aerolínea (barras comparativas ordenadas)
3. KPIs: total vuelos · retraso promedio · % cancelaciones
4. Distribución de causas de retraso por trimestre (barras apiladas)

**Filtro interactivo:** clic en cualquier punto de la tendencia mensual filtra todas las visualizaciones.

Ver documentación detallada en `docs/dashboard-doc.md`.

---

## Verificación post-carga

Ejecutar en pgAdmin para confirmar que todo está correcto:

```sql
-- Conteo por partición
SELECT tableoid::regclass AS particion, COUNT(*) AS filas
FROM dw.fact_vuelo
GROUP BY tableoid ORDER BY particion;

-- Totales por tabla
SELECT 'dim_tiempo'        AS tabla, COUNT(*) FROM dw.dim_tiempo    UNION ALL
SELECT 'dim_aerolinea',             COUNT(*) FROM dw.dim_aerolinea  UNION ALL
SELECT 'dim_aeropuerto',            COUNT(*) FROM dw.dim_aeropuerto UNION ALL
SELECT 'fact_vuelo (total)',         COUNT(*) FROM dw.fact_vuelo;

-- Verificar índices y FK activos
SELECT indexname FROM pg_indexes WHERE schemaname = 'dw';
SELECT conname FROM pg_constraint WHERE conrelid = 'dw.fact_vuelo'::regclass;
```

---

## Decisiones técnicas

Ver `docs/technical-decisions.md` para justificación completa de:
- Esquema estrella vs snowflake
- Estrategia de particionamiento mensual
- Justificación de cada índice con EXPLAIN ANALYZE real
- Código de exploración del dataset y problemas de calidad resueltos
- Distinción OLTP (sistema fuente BTS) vs OLAP (DW construido)
