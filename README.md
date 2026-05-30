# Proyecto Final — Base de Datos II (031)

**Universidad Mariano Gálvez de Guatemala**  
**Facultad de Ingeniería en Sistemas de Información y Ciencias de la Computación**

---

## Descripción general

Este proyecto implementa un pipeline ETL y un Data Warehouse analítico sobre el dataset **Airline On-Time Performance** del **Bureau of Transportation Statistics (BTS / U.S. DOT)**.

El flujo completo incluye:

1. **Extracción** automática de archivos mensuales 2023–2024.
2. **Transformación** y limpieza de datos.
3. **Construcción de dimensiones y tabla de hechos**.
4. **Carga automática a PostgreSQL**, ejecutando el DDL desde Python.
5. **Optimización** con particionamiento e índices.
6. **Análisis técnico** con `EXPLAIN ANALYZE`.
7. **Dashboard** conectado directamente a PostgreSQL.

El objetivo principal del proyecto es construir un **Data Warehouse optimizado**, no únicamente un dashboard visual.

---

## Dataset

**Fuente:** Airline On-Time Performance — Bureau of Transportation Statistics (BTS / U.S. DOT)  
**Años:** 2023 y 2024, 24 meses completos  
**Volumen final cargado:** **14,825,707 registros** en `dw.fact_vuelo`

**URL base de descarga:**

```text
https://transtats.bts.gov/PREZIP/On_Time_Marketing_Carrier_On_Time_Performance_Beginning_January_2018_{year}_{month}.zip
```

---

## Preguntas de negocio

Las preguntas de negocio definidas antes de construir el dashboard son:

1. ¿Qué aerolínea tiene el mayor retraso promedio de llegada en 2023–2024?
2. ¿Cuál es la tendencia mensual de retrasos a lo largo de los dos años?
3. ¿Qué aeropuertos de origen concentran más cancelaciones?
4. ¿Cómo se distribuyen los retrasos de llegada en el período analizado?

---

## Estructura del repositorio

```text
PROYECTO-BDII/
├── docs/
│   ├── airline_dashboard.pdf
│   ├── dashboard-doc.md
│   ├── model_diagram.png
│   └── technical-decisions.md
├── etl/
│   ├── extract.py
│   ├── transform.py
│   └── load.py
├── notebooks/
│   └── data_profiling.ipynb
├── sql/
│   ├── ddl_schema.sql
│   └── queries_analyze.sql
├── staging/
│   ├── raw/
│   ├── extracted/
│   ├── transformed/
│   ├── extract.log
│   ├── transform.log
│   └── load.log
├── airline_dashboard.twb
├── requirements.txt
└── README.md
```

---

## Requisitos

### Software necesario

- Python 3.9 o superior
- Docker Desktop
- PostgreSQL ejecutándose en contenedor Docker
- Tableau Desktop o Power BI Desktop

### Dependencias Python

Desde la raíz del proyecto:

```bash
pip install -r requirements.txt
```

Contenido esperado de `requirements.txt`:

```text
requests
pandas
pyarrow
psycopg2-binary
```

---

## Configuración inicial

### 1. Levantar PostgreSQL en Docker

En PowerShell:

```powershell
docker run --name airline-dw `
  -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=airline_dw `
  -p 5433:5432 `
  -d postgres:17
```

Verificar que el contenedor esté activo:

```powershell
docker ps
```

Debe aparecer el contenedor `airline-dw` usando el puerto `5433`.

---

## Configuración de conexión

El script `etl/load.py` usa por defecto estos valores:

```python
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5433,
    "dbname": "airline_dw",
    "user": "postgres",
    "password": "postgres"
}
```

También se pueden usar variables de entorno para cambiar la conexión sin modificar el código:

```powershell
$env:DB_HOST="127.0.0.1"
$env:DB_PORT="5433"
$env:DB_NAME="airline_dw"
$env:DB_USER="postgres"
$env:DB_PASSWORD="postgres"
```

---

## Ejecución del pipeline ETL

El pipeline completo se ejecuta desde la raíz del proyecto:

```powershell
python etl\extract.py
python etl\transform.py
python etl\load.py
```

O en una sola línea:

```powershell
python etl\extract.py; python etl\transform.py; python etl\load.py
```

> **Importante:** los scripts deben ejecutarse desde la carpeta raíz del proyecto, no desde dentro de `etl/`.

---

## Qué hace cada script

### `extract.py`

Descarga automáticamente los 24 archivos ZIP del dataset, correspondientes a los meses de 2023 y 2024, y extrae los CSV en `staging/extracted`.

### `transform.py`

Limpia los datos, resuelve problemas de calidad y construye los archivos Parquet transformados:

- `dim_tiempo.parquet`
- `dim_aerolinea.parquet`
- `dim_aeropuerto.parquet`
- archivos mensuales de `fact_vuelo`

Estos archivos se guardan en `staging/transformed`.

### `load.py`

Realiza la carga a PostgreSQL usando `COPY FROM STDIN` por lotes.

El script `load.py` ejecuta automáticamente:

```text
sql/ddl_schema.sql
```

Esto permite que el pipeline sea reproducible desde una base limpia, sin crear tablas manualmente.

El script `load.py` se encarga de:

1. Asegurar la existencia de la base de datos `airline_dw` en el motor.
2. Ejecutar el DDL de creación de estructuras.
3. Crear el esquema `dw`.
4. Crear las tablas dimensionales vacías.
5. Crear la tabla de hechos `fact_vuelo` y sus 24 particiones mensuales vacías.
6. Cargar masivamente las dimensiones y hechos a alta velocidad con `COPY`.
7. Crear las llaves foráneas.
8. Crear los índices analíticos optimizados.
9. Verificar conteos finales de la carga.

> **Nota:** `ddl_schema.sql` reconstruye el esquema `dw`. Si el esquema ya existe, se elimina y se vuelve a crear para garantizar una carga limpia.

---

## Resultados de carga obtenidos

Tras la ejecución del pipeline, se obtiene el siguiente volumen de datos en el Data Warehouse:

| Tabla | Filas | Descripción |
|---|---:|---|
| `dw.dim_tiempo` | 731 | Dimensión de tiempo con granularidad diaria |
| `dw.dim_aerolinea` | 10 | Aerolíneas de marketing |
| `dw.dim_aeropuerto` | 362 | Dimensión de aeropuertos |
| `dw.fact_vuelo` | 14,825,707 | Tabla de hechos particionada por `flight_date` |

---

## Modelo dimensional

Se utilizó un **esquema estrella**.

El modelo contiene:

- **Tabla de hechos:** `dw.fact_vuelo`
- **Dimensiones:**
  - `dw.dim_tiempo`
  - `dw.dim_aerolinea`
  - `dw.dim_aeropuerto`

La dimensión `dim_aeropuerto` se reutiliza dos veces en la tabla de hechos:

- `origen_sk`
- `destino_sk`

Esto permite analizar vuelos por aeropuerto de origen y por aeropuerto de destino usando una sola dimensión.

![Diagrama dimensional](docs/model_diagram.png)

---

## Particionamiento

La tabla `dw.fact_vuelo` está particionada por rango sobre la columna:

```sql
flight_date
```

La granularidad elegida fue **mensual**.

Total de particiones:

```text
24 particiones mensuales
```

Desde:

```text
dw.fact_vuelo_2023_01
```

hasta:

```text
dw.fact_vuelo_2024_12
```

Esta estrategia permite que PostgreSQL lea solo las particiones necesarias cuando una consulta filtra por fecha.

---

## Índices

Se crearon 3 índices sobre la tabla de hechos:

### 1. `idx_fact_aerolinea_cubriente`

```sql
CREATE INDEX idx_fact_aerolinea_cubriente
ON dw.fact_vuelo (aerolinea_sk)
INCLUDE (arr_delay);
```

Índice cubriente (Covering Index) optimizado para OLAP. Motiva consultas de promedios globales de retraso por aerolínea sin requerir lecturas físicas a la tabla principal (Index-Only Scan).

### 2. `idx_fact_fecha_aerolinea`

```sql
CREATE INDEX idx_fact_fecha_aerolinea
ON dw.fact_vuelo (flight_date, aerolinea_sk);
```

Índice compuesto. Motiva consultas selectivas de filtros simultáneos por fecha y aerolínea en el dashboard.

### 3. `idx_fact_origen_cancelados`

```sql
CREATE INDEX idx_fact_origen_cancelados
ON dw.fact_vuelo (origen_sk)
WHERE cancelled = 1;
```

Índice parcial (Partial Index) altamente selectivo. Motiva consultas analíticas sobre cancelaciones de aeropuertos de origen filtrando únicamente el ~1.3% de registros históricos cancelados (reducción masiva del tiempo de ejecución).

---

## Llaves foráneas

La tabla `dw.fact_vuelo` contiene las siguientes llaves foráneas:

- `fk_fact_tiempo`
- `fk_fact_aerolinea`
- `fk_fact_origen`
- `fk_fact_destino`

Estas relaciones conectan la tabla de hechos con las dimensiones del esquema estrella.

---

## Evidencia técnica

El Data Warehouse fue validado mediante `EXPLAIN ANALYZE`.

La evidencia técnica incluye:

- demostración de partition pruning en consultas con filtro por fecha;
- uso del índice compuesto `idx_fact_fecha_aerolinea` en consultas selectivas;
- uso del índice `idx_fact_aerolinea` mediante `Index Only Scan`;
- uso del índice `idx_fact_origen` combinado con filtro por fecha;
- comparación de costos y tiempos antes/después de índices;
- explicación OLTP vs OLAP.

Archivos relacionados:

```text
docs/technical-decisions.md
sql/queries_analyze.sql
```

---

## Dashboard

**Archivo:** `airline_dashboard.twb`  
**Herramienta:** Tableau Desktop  
**Conexión:** PostgreSQL, base `airline_dw`, esquema `dw`

El dashboard se conecta directamente a PostgreSQL, no importa CSV ni archivos locales.

### Visualizaciones

1. **Tendencia temporal:** retraso promedio mensual 2023–2024.
2. **Comparativa de categorías:** retraso promedio por aerolínea.
3. **KPI agregado:** total de vuelos, retraso promedio general y porcentaje de cancelaciones.
4. **Distribución:** distribución de retrasos de llegada.

### Filtros interactivos

- Rango de fechas.
- Aerolínea.
- Aeropuerto de origen.

> Para abrir el dashboard, el contenedor `airline-dw` debe estar activo y la base debe estar cargada.

---

## Verificación post-carga

Después de ejecutar `load.py`, se pueden correr estas consultas en DBeaver o psql.

### Conteo de tablas

```sql
SELECT 'dim_tiempo' AS tabla, COUNT(*) FROM dw.dim_tiempo
UNION ALL
SELECT 'dim_aerolinea', COUNT(*) FROM dw.dim_aerolinea
UNION ALL
SELECT 'dim_aeropuerto', COUNT(*) FROM dw.dim_aeropuerto
UNION ALL
SELECT 'fact_vuelo', COUNT(*) FROM dw.fact_vuelo;
```

### Validar índices

```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'dw'
  AND tablename = 'fact_vuelo'
ORDER BY indexname;
```

### Validar llaves foráneas

```sql
SELECT conname
FROM pg_constraint
WHERE conrelid = 'dw.fact_vuelo'::regclass
  AND contype = 'f'
ORDER BY conname;
```

### Validar particiones

```sql
SELECT
    inhparent::regclass AS tabla_padre,
    inhrelid::regclass AS particion
FROM pg_inherits
WHERE inhparent = 'dw.fact_vuelo'::regclass
ORDER BY particion;
```

### Consulta analítica de prueba

```sql
SELECT
    a.nombre_aerolinea,
    ROUND(AVG(f.arr_delay), 2) AS retraso_promedio
FROM dw.fact_vuelo f
JOIN dw.dim_aerolinea a
    ON f.aerolinea_sk = a.aerolinea_sk
GROUP BY a.nombre_aerolinea
ORDER BY retraso_promedio DESC
LIMIT 10;
```

---

## Tiempos estimados de ejecución

Los tiempos pueden variar según conexión a internet, disco y memoria disponible.

| Paso | Tiempo estimado |
|---|---:|
| `extract.py` | 30–60 minutos |
| `transform.py` | 15–25 minutos |
| `load.py` | 25–45 minutos |
| Pipeline completo | 70–130 minutos |

---

## Notas de ejecución

- En Windows, `extract.py` puede mostrar advertencias de codificación en consola por símbolos especiales, pero la descarga puede completarse correctamente.
- El proyecto usa el puerto `5433` para evitar conflictos con otros servicios PostgreSQL locales.
- Si se elimina el contenedor Docker, la base puede reconstruirse ejecutando nuevamente el pipeline.
- `load.py` reconstruye el esquema `dw`, por lo que no es necesario crear las tablas manualmente.
- No se debe ejecutar `load.py` contra una base que se quiera conservar sin respaldo, porque el DDL reconstruye el esquema `dw`.

---

## Reproducibilidad desde cero

En una máquina limpia, el flujo esperado es:

```powershell
git clone https://github.com/HilaryRompich2021/Proyecto-BDII.git
cd Proyecto-BDII
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

docker run --name airline-dw `
  -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=airline_dw `
  -p 5433:5432 `
  -d postgres:17

python etl\extract.py
python etl\transform.py
python etl\load.py
```

Al finalizar, se espera obtener:

```text
dw.fact_vuelo = 14,825,707 registros
```

---

## Autores

Proyecto desarrollado para el curso **Base de Datos II (031)**.
