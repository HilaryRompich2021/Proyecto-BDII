# technical-decisions.md
> Proyecto Final — Base de Datos II (031)  
> Universidad Mariano Gálvez de Guatemala  
> Dataset: Airline On-Time Performance (BTS / U.S. DOT)  
> Años: 2023 + 2024 | **14,825,707 registros cargados y verificados**  
> Estado: PROYECTO COMPLETO — pipeline ETL funcional, DW cargado, dashboard entregado

---

## 1. Dataset elegido

**Fuente:** Bureau of Transportation Statistics (BTS) — U.S. Department of Transportation  
**Nombre oficial:** Marketing Carrier On-Time Performance (Beginning January 2018)  
**URL base de descarga automatizada:**
```
https://transtats.bts.gov/PREZIP/On_Time_Marketing_Carrier_On_Time_Performance_Beginning_January_2018_{year}_{month}.zip
```

**Justificación:**
- Columna `FlightDate` (fecha de evento) bien definida → cumple requisito de dimensión temporal y particionamiento por rango
- 14,825,707 registros verificados en `fact_vuelo` → nivel "Recomendado" del proyecto (10M–20M)
- Descarga 100% automatizada por URL directa, un ZIP por mes, sin intervención manual
- Problemas de calidad de datos reales y documentables (ver sección 6)
- Dimensiones naturales: tiempo, aerolínea, aeropuerto origen, aeropuerto destino

**Años: 2023 y 2024** — 24 meses completos, 24 particiones mensuales uniformes  
2025 descartado: diciembre 2025 no publicado por BTS al momento del proyecto  
2022 descartado: agregar un tercer año no justifica el costo operacional vs beneficio evaluativo

---

## 2. Modelo dimensional: Esquema Estrella

### Decisión y justificación

**Esquema elegido:** Estrella  
**Alternativa descartada:** Snowflake

El esquema snowflake normaliza las dimensiones en subtablas (ej. `dim_aeropuerto → dim_ciudad → dim_estado`), lo que requiere JOINs encadenados en cada consulta analítica. Sobre 14.8 millones de filas ese costo es medible y contraproducente para un sistema OLAP cuyo objetivo es velocidad de lectura.

Las dimensiones de este dataset son pequeñas (~20 aerolíneas, ~500 aeropuertos), por lo que la redundancia en el esquema estrella es mínima y no justifica la complejidad del snowflake. Kimball & Ross (The Data Warehouse Toolkit, 3rd ed.) recomiendan el esquema estrella como diseño por defecto para Data Warehouses OLAP por esta razón.

### Tablas del modelo

| Tabla | Tipo | Filas cargadas | Descripción |
|---|---|---|---|
| `fact_vuelo` | Hechos | 14,825,707 | Una fila por vuelo. Particionada por rango mensual |
| `dim_tiempo` | Dimensión | 730 | Granularidad de día |
| `dim_aerolinea` | Dimensión | 10 | Aerolínea de marketing |
| `dim_aeropuerto` | Dimensión | 388 | Role-playing: origen y destino |

### Surrogate keys

Todas las dimensiones usan `INTEGER GENERATED ALWAYS AS IDENTITY` — convención estándar de Kimball que desacopla las claves del DW de los identificadores del sistema fuente. Generadas en Python durante `transform.py` antes de la carga.

---

## 3. Estrategia de particionamiento

**Tipo:** `PARTITION BY RANGE` sobre `flight_date`  
**Granularidad:** Mensual  
**Particiones:** 24 (2023-01 a 2024-12)

**Justificación:**
- ~600K filas por partición → tamaño óptimo para partition pruning visible y medible
- El dashboard filtra por rangos de fecha → pruning elimina particiones irrelevantes automáticamente
- Granularidad trimestral (8 particiones) sería insuficiente para pruning significativo
- Granularidad diaria (~730 particiones) generaría overhead de planificación contraproducente

---

## 4. Evidencia de Partition Pruning

### Consulta ejecutada

```sql
EXPLAIN ANALYZE
SELECT aerolinea_sk, AVG(arr_delay)
FROM dw.fact_vuelo
WHERE flight_date BETWEEN '2024-01-01' AND '2024-03-31'
GROUP BY aerolinea_sk;
```

### Resultado

PostgreSQL escaneó únicamente 3 particiones (`fact_vuelo_2024_01`, `_02`, `_03`).
Las 21 restantes fueron descartadas automáticamente por el planificador.

### Comparación cuantitativa

| Escenario | Particiones escaneadas | Filas examinadas | Tiempo |
|---|---|---|---|
| Sin filtro de fecha | 24 de 24 | 14,825,707 | 1,566 ms |
| Con filtro Q1 2024 | 3 de 24 | ~1,763,902 | 220 ms |
| **Mejora** | **87.5% menos** | **88% menos** | **86% más rápido** |

### Fragmento del EXPLAIN ANALYZE

```
Parallel Append (actual time=0.177..117.262 rows=587967 loops=3)
  -> Parallel Seq Scan on fact_vuelo_2024_01
       Filter: ((flight_date >= '2024-01-01') AND (flight_date <= '2024-03-31'))
  -> Parallel Seq Scan on fact_vuelo_2024_02
       Filter: ((flight_date >= '2024-01-01') AND (flight_date <= '2024-03-31'))
  -> Parallel Seq Scan on fact_vuelo_2024_03
       Filter: ((flight_date >= '2024-01-01') AND (flight_date <= '2024-03-31'))
Planning Time: 0.270 ms | Execution Time: 220.349 ms
```

---

## 5. Índices estratégicos — evidencia cuantitativa

### Índice 1: `idx_fact_aerolinea` — simple sobre `aerolinea_sk`

**Consulta que lo motiva:**
```sql
SELECT aerolinea_sk, AVG(arr_delay)
FROM dw.fact_vuelo
GROUP BY aerolinea_sk
ORDER BY AVG(arr_delay) DESC;
```

| Métrica | Sin índice | Con índice |
|---|---|---|
| Costo estimado | 336,529–336,581 | 336,529–336,581 |
| Execution Time | 1,566 ms | 1,592 ms |

**Análisis:** Para GROUP BY sobre toda la tabla PostgreSQL elige correctamente Parallel Seq Scan sobre Index Scan — la selectividad es baja (se procesan todas las filas). El índice beneficia queries con `WHERE aerolinea_sk = N` que retornan una fracción pequeña de filas.

---

### Índice 2: `idx_fact_fecha_aerolinea` — compuesto `(flight_date, aerolinea_sk)`

**Consulta que lo motiva:**
```sql
SELECT flight_date, aerolinea_sk, AVG(arr_delay)
FROM dw.fact_vuelo
WHERE flight_date BETWEEN '2024-01-01' AND '2024-03-31'
GROUP BY flight_date, aerolinea_sk
ORDER BY flight_date;
```

| Métrica | Sin índice | Con índice |
|---|---|---|
| Costo estimado | 100,574–111,208 | 100,574–111,208 |
| Execution Time | 241 ms | 277 ms |
| Particiones escaneadas | 3 de 24 | 3 de 24 |

**Análisis:** El particionamiento ya elimina 21 particiones. El índice compuesto maximiza su valor en queries que filtran simultáneamente por rango de fecha Y aerolínea específica (`WHERE flight_date BETWEEN ... AND aerolinea_sk = N`).

---

### Índice 3: `idx_fact_origen` — simple sobre `origen_sk`

**Consulta que lo motiva:**
```sql
SELECT origen_sk, COUNT(*) AS cancelaciones
FROM dw.fact_vuelo
WHERE cancelled = 1
GROUP BY origen_sk
ORDER BY cancelaciones DESC LIMIT 20;
```

| Métrica | Sin índice | Con índice |
|---|---|---|
| Costo estimado | 291,007–291,064 | 291,007–291,064 |
| Execution Time | 1,135 ms | 1,108 ms |

**Análisis:** El filtro `WHERE cancelled = 1` sin índice propio fuerza full scan. Mejora marginal de 27 ms. Optimización identificada: un índice parcial `CREATE INDEX ON dw.fact_vuelo (origen_sk) WHERE cancelled = 1` sería más eficiente.

---

## 6. Calidad de datos — exploración y correcciones

### Código de exploración ejecutado

El siguiente código fue ejecutado para identificar los problemas del dataset antes de implementar las correcciones en `transform.py`:

```python
import pandas as pd

# Leer muestra del primer CSV para exploración
df = pd.read_csv(
    'staging/extracted/On_Time_Marketing_Carrier_On_Time_Performance_(Beginning_January_2018)_2023_1.csv',
    nrows=500,
    low_memory=False
)

# 1. Revisar nombres de columnas (detectó el espacio en Operating_Airline)
print(df.columns.tolist())
# Output incluía: 'Operating_Airline ' ← espacio al final detectado

# 2. Contar nulos por columna (ordenados de mayor a menor)
print(df.isnull().sum().sort_values(ascending=False).head(15))
# Output mostró columnas Div1-Div5 y Originally_Scheduled con 500/500 nulos

# 3. Revisar tipos de datos
print(df.dtypes)
# Output mostró FlightDate como object (string) en lugar de datetime
# Output mostró Duplicate como str en lugar de numérico

# 4. Verificar columna fantasma
print([c for c in df.columns if 'Unnamed' in c])
# Output: ['Unnamed: 119'] ← columna artefacto del CSV
```

### Problemas identificados y soluciones aplicadas en `transform.py`

| # | Problema detectado | Columna(s) | Solución implementada |
|---|---|---|---|
| 1 | Nombre de columna con espacio al final | `Operating_Airline ` | `df.columns.str.strip()` al cargar cada chunk |
| 2 | Columna fantasma sin datos | `Unnamed: 119` | Eliminada al seleccionar solo columnas del modelo |
| 3 | Tipo incorrecto — fecha como string | `FlightDate` | `pd.to_datetime()` → tipo `date` nativo |
| 4 | Nulos en métricas de vuelos cancelados | `ArrDelay`, `DepDelay`, `TaxiOut`, `TaxiIn`, `AirTime` | `fillna(0.0)` — vuelo cancelado = 0 min operación |
| 5 | Nulos en código de cancelación | `CancellationCode` nulo cuando `Cancelled=0` | `fillna("N/A")` |
| 6 | Columnas de vuelos desviados 100% nulas | `Div1Airport` a `Div5TailNum` (50+ columnas) | Descartadas — no aportan al modelo dimensional |

---

## 7. Distinción OLTP vs OLAP

**Sistema fuente (OLTP):** Los sistemas operacionales de aerolíneas y la FAA registran cada vuelo en tiempo real — inserciones individuales por evento, optimizados para escritura concurrente, esquemas en 3FN, transacciones ACID individuales.

**Data Warehouse construido (OLAP):** Carga por lotes desde staging con `COPY` de PostgreSQL, optimizado para lectura analítica, esquema dimensional desnormalizado (estrella), con particionamiento e índices orientados a consultas agregadas.

> El dataset BTS proviene de un sistema que operó históricamente bajo modelo OLTP. El DW construido es el componente OLAP que permite análisis retrospectivo de ese historial.

---

## 8. Preguntas de negocio del dashboard

1. ¿Qué aerolínea tiene el mayor retraso promedio de llegada en 2023–2024?
2. ¿Cuál es la tendencia mensual de retrasos a lo largo de los dos años?
3. ¿Qué aeropuertos de origen concentran más cancelaciones?
4. ¿Qué causa de retraso es más frecuente por trimestre?

---

## 9. Decisiones tecnológicas

| Componente | Decisión | Justificación |
|---|---|---|
| ETL | Python 3.9+ scripts `.py` | Requisito del proyecto |
| Staging | Parquet por mes en disco local | Compresión nativa, más eficiente que CSV |
| Base de datos | PostgreSQL local (instalación nativa) | Requisito del proyecto |
| Carga masiva | `COPY FROM STDIN` vía psycopg2 | Requisito explícito para datasets >1M filas |
| DDL | Ejecutado automáticamente por `load.py` | Requisito: "ejecutarse desde Python en el proceso de carga" |
| Índices | Creados post-carga (bulk build) | 3–5x más rápido que mantenerlos durante COPY |
| FK | Creadas post-índices por `load.py` | Soportadas desde PostgreSQL 12; validación usa índices como apoyo |
| Dashboard | Tableau Desktop | Conector nativo a PostgreSQL sin configuración ODBC adicional |

---

## 10. Resumen de mejoras cuantitativas

| Optimización | Antes | Después | Mejora |
|---|---|---|---|
| Partition pruning Q1 2024 | 1,566 ms / 24 particiones | 220 ms / 3 particiones | **86% más rápido** |
| Filas examinadas | 14,825,707 | 1,763,902 | **88% menos filas** |
| Carga COPY vs INSERT individual | ~14.8M ops individuales | COPY por lotes de 50K | **~10–50x más rápido** |

---
*Proyecto completado — semanas 3–8*  
*Pipeline verificado: 14,825,707 registros cargados, 24 particiones, 3 índices, 4 FK, dashboard funcional*
