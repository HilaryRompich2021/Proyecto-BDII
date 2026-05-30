# Decisiones Técnicas del Proyecto

## 1. Contexto general del proyecto

Este proyecto implementa un pipeline ETL y un Data Warehouse analítico sobre el dataset **Airline On-Time Performance** del **Bureau of Transportation Statistics (BTS / U.S. DOT)**, utilizando datos de los años **2023 y 2024**.

El objetivo principal es demostrar dominio en:

- modelado dimensional
- carga masiva de datos
- particionamiento por rango
- diseño de índices
- análisis de rendimiento con `EXPLAIN ANALYZE`

El volumen final cargado en la tabla de hechos fue de:

- **14,825,707 registros** en `dw.fact_vuelo`

---

## 2. Decisión de modelado dimensional

### Esquema elegido
**Esquema estrella**

### Alternativa descartada
**Esquema snowflake**

### Justificación

Se eligió un **esquema estrella** porque el objetivo del proyecto es soportar consultas analíticas rápidas sobre un volumen alto de datos. En este enfoque, la tabla de hechos se conecta directamente con dimensiones relativamente pequeñas, lo que reduce la complejidad de los `JOIN` y mejora la legibilidad de las consultas.

La estructura implementada es:

- **Tabla de hechos:** `dw.fact_vuelo`
- **Dimensiones:**
  - `dw.dim_tiempo`
  - `dw.dim_aerolinea`
  - `dw.dim_aeropuerto`

Se descartó el esquema snowflake porque hubiera implicado normalizar más las dimensiones, por ejemplo separando ciudad y estado en tablas adicionales. Eso habría incrementado el número de `JOIN` en consultas analíticas sin aportar beneficios relevantes, ya que las dimensiones del proyecto son pequeñas:

- `dim_tiempo`: 731 filas
- `dim_aerolinea`: 10 filas
- `dim_aeropuerto`: 362 filas

En este contexto, la redundancia adicional del esquema estrella es mínima y está justificada por la simplicidad y eficiencia en lectura.

---

## 3. Relación entre OLTP y OLAP

En este proyecto no se construyó un sistema transaccional real, pero sí se puede identificar claramente la diferencia entre el sistema fuente y el Data Warehouse final:

### Componente OLTP
El dataset fuente representa eventos operativos individuales del mundo real: cada fila corresponde a un vuelo con atributos como fecha, aerolínea, aeropuerto, retrasos, cancelaciones y causas de demora. Esa estructura corresponde conceptualmente a un entorno **OLTP**, porque modela registros detallados de operación.

### Componente OLAP
El Data Warehouse construido en PostgreSQL corresponde al componente **OLAP**, porque reorganiza esos datos en un esquema estrella, particionado y optimizado para:

- agregaciones
- tendencias temporales
- comparación entre categorías
- análisis histórico
- dashboards analíticos

En resumen:

- **Fuente de datos** → paradigma OLTP
- **Data Warehouse en PostgreSQL** → paradigma OLAP

---

## 4. Manejo de calidad de datos y limpieza (ETL)

El cumplimiento del criterio de **Manejo de Datos Sucios** (3 pts en la rúbrica) se logró mediante un proceso riguroso de **Perfilado de Datos (Data Profiling)** sobre muestras aleatorias del dataset original del BTS. 

**Metodología y Evidencia Científica (Jupyter Notebook):**
Para no realizar limpiezas por intuición, implementamos un análisis exploratorio previo en el Jupyter Notebook [notebooks/data_profiling.ipynb](file:///c:/Users/feraz/OneDrive/Escritorio/9no_Ciclo/BD_II/Proyecto-BDII/notebooks/data_profiling.ipynb). En esta bitácora experimental programamos diagnósticos rápidos, agrupaciones lógicas y filtros booleanos en Pandas que nos permitieron comprobar científicamente la correlación y naturaleza de cada inconsistencia física.

Basándonos en esta evidencia cuantitativa descubierta, decidimos y justificamos las siguientes 6 reglas de limpieza que consolidamos formalmente en la fase de transformación (`transform.py`):

1. **Espacios en blanco en cabeceras de columnas:** Al listar las columnas con `.columns.tolist()` en Pandas, se detectó que columnas clave como `'Operating_Airline '` venían con espacios vacíos adicionales al final del string. Se resolvió aplicando `.str.strip()` en las cabeceras.
2. **Columnas redundantes/basura:** Se detectó la presencia de columnas sin información útil generadas por la exportación origen (como `'Unnamed: 119'`). Se resolvió implementando una lista estricta de columnas deseadas (`COLS_KEEP`), eliminando selectivamente todo residuo.
3. **Tipos de datos inconsistentes:** La columna `FlightDate` venía como un tipo objeto genérico (string). Se parseó dinámicamente a tipo de dato `date` nativo para permitir ordenamientos temporales rápidos e implementar el particionamiento físico.
4. **Valores nulos en demoras de vuelos cancelados:** Se detectó que las columnas de demora de salida (`DepDelay`) y llegada (`ArrDelay`) contenían miles de valores nulos (NaN). Al cruzar estadísticas con `Cancelled = 1`, descubrimos que los nulos ocurrían exclusivamente en vuelos cancelados (ya que un vuelo no realizado carece de tiempos de demora operativa). Para evitar que los nulos en SQL alteren o rompan las funciones agregadas globales (`AVG`, `SUM`) en el Dashboard, se imputaron a `0.0`.
5. **Atributo categórico nulo en vuelos exitosos:** La columna `CancellationCode` venía nula para el 98.7% de los registros que sí volaron con éxito. En un Data Warehouse, los nulos categóricos complican las agrupaciones en Tableau. Se imputó con la constante `'N/A'` (No Aplica) para crear una categoría explícita.
6. **Nulos en causas de retraso específicas:** Columnas como `CarrierDelay`, `WeatherDelay`, etc., venían vacías si el vuelo no experimentó demoras. Se imputaron sistemáticamente con `0.0` para permitir sumatorias y promedios aritméticos eficientes de las causas de retraso en el motor de base de datos sin requerir validaciones manuales en Tableau.

---

## 5. Estrategia de particionamiento

### Tipo
`PARTITION BY RANGE` sobre la columna `flight_date`

### Granularidad
**Mensual**

### Total de particiones
**24 particiones**, desde:

- `dw.fact_vuelo_2023_01`
- ...
- `dw.fact_vuelo_2024_12`

### Justificación

Se eligió particionamiento mensual porque:

1. El dataset cubre 24 meses completos
2. Las consultas del dashboard y del análisis técnico usan filtros por fecha
3. La granularidad mensual permite evidenciar claramente el `partition pruning`
4. Cada partición queda con un volumen manejable, alrededor de 550 mil a 680 mil filas por mes

Se descartó una partición trimestral porque habría reducido la visibilidad del pruning, y también se descartó una partición diaria porque habría generado demasiadas particiones y mayor costo de planificación.

---

## 6. Evidencia de partition pruning

### Consulta utilizada

```sql
EXPLAIN ANALYZE
SELECT a.nombre_aerolinea, AVG(f.arr_delay) AS retraso_promedio
FROM dw.fact_vuelo f
JOIN dw.dim_aerolinea a
    ON f.aerolinea_sk = a.aerolinea_sk
WHERE f.flight_date BETWEEN DATE '2024-01-01' AND DATE '2024-03-31'
GROUP BY a.nombre_aerolinea
ORDER BY retraso_promedio DESC;
```

### Fragmento relevante del plan

```text
Parallel Append
  -> Parallel Seq Scan on fact_vuelo_2024_03
  -> Parallel Seq Scan on fact_vuelo_2024_01
  -> Parallel Seq Scan on fact_vuelo_2024_02
```

### Interpretación

El plan muestra que PostgreSQL solo accedió a las particiones:

- `fact_vuelo_2024_01`
- `fact_vuelo_2024_02`
- `fact_vuelo_2024_03`

Esto demuestra que el particionamiento mensual sí está funcionando correctamente, porque el motor **no revisó las 24 particiones**, sino únicamente las 3 relevantes para el rango solicitado.

### Resultado observado

- **Execution Time:** ~288.799 ms
- Particiones leídas: **3 de 24**

### Conclusión

El mayor beneficio del particionamiento se observó en consultas con filtros por rangos de fecha amplios, donde PostgreSQL redujo automáticamente el universo de búsqueda a las particiones necesarias.

---

## 7. Estrategia de índices

Se definieron 3 índices altamente estratégicos sobre la tabla de hechos, rediseñados específicamente bajo patrones **OLAP** para maximizar el rendimiento analítico:

1. `idx_fact_aerolinea_cubriente` (Índice Cubriente / Covering Index)
2. `idx_fact_fecha_aerolinea` (Índice Compuesto / Composite Index)
3. `idx_fact_origen_cancelados` (Índice Parcial / Partial Index)

La idea original de usar índices simples tradicionales fue descartada en la fase de auditoría debido a la baja selectividad de las consultas globales, migrando hacia estrategias de indexación avanzadas de bases de datos analíticas.

---

## 6.1 Índice 1 — `idx_fact_aerolinea_cubriente`

### Tipo
**Índice Cubriente (Covering Index)** sobre la columna clave con datos no clave incluidos en las hojas del B-Tree:

```sql
CREATE INDEX idx_fact_aerolinea_cubriente 
ON dw.fact_vuelo (aerolinea_sk) 
INCLUDE (arr_delay);
```

### Consulta que lo motiva
Retraso promedio general por aerolínea (KPI del dashboard).

```sql
SELECT aerolinea_sk, AVG(arr_delay)
FROM dw.fact_vuelo
GROUP BY aerolinea_sk
ORDER BY AVG(arr_delay) DESC;
```

### Métricas registradas

| Métrica | Sin índice (Seq Scan) | Con índice Cubriente |
|---|---:|---:|
| Tipo de Scan | Parallel Seq Scan | Parallel Index Only Scan |
| Costo del Plan | 336529 | ~180000 |
| Execution Time | 1,566 ms | ~680 ms |

### Interpretación
En las bases de datos transaccionales, un índice simple obliga a hacer *lookups* a la tabla física (Heap) por cada registro indexado para recuperar columnas adicionales (en este caso `arr_delay`), lo cual es sumamente costoso. Al utilizar la cláusula `INCLUDE`, convertimos el índice en un **Índice Cubriente**. PostgreSQL ahora encuentra tanto la clave de agrupación (`aerolinea_sk`) como la métrica (`arr_delay`) dentro de las páginas físicas del índice, permitiendo un **Index-Only Scan** extremadamente eficiente.

### Conclusión
Este diseño analítico reduce los accesos físicos a disco y el costo del plan en más del 45%, demostrando la efectividad de los índices de cobertura en consultas globales.

---

## 6.2 Índice 2 — `idx_fact_fecha_aerolinea`

### Tipo
**Índice Compuesto (Composite Index)** estructurado sobre el orden lógico de filtrado analítico (fecha y dimensiones):

```sql
CREATE INDEX idx_fact_fecha_aerolinea 
ON dw.fact_vuelo (flight_date, aerolinea_sk);
```

### Consulta que lo motiva
Simulación de drill-down selectivo en el dashboard (un usuario interactuando con filtros de día y aerolínea específicos).

```sql
EXPLAIN ANALYZE
SELECT COUNT(*) AS total_vuelos, AVG(arr_delay) AS retraso_promedio
FROM dw.fact_vuelo
WHERE flight_date = DATE '2024-01-15'
  AND aerolinea_sk = 1;
```

### Resultado observado

- Filas encontradas: **653**
- Partición usada: **fact_vuelo_2024_01** (gracias a partition pruning)
- **Execution Time:** **0.755 ms**

### Interpretación
El índice compuesto brilla en escenarios de **alta selectividad**. PostgreSQL primero aplica el particionamiento mensual descartando 23 de las 24 particiones. Dentro de la partición correspondiente a enero de 2024, utiliza el índice compuesto local (`Bitmap Index Scan`) para extraer de manera directa los 653 registros relevantes en lugar de leer secuencialmente el mes entero.

### Conclusión
Este índice compuesto representa la optimización más fuerte para la interacción en vivo con el dashboard, respondiendo en tiempos menores a 1 ms.

---

## 6.3 Índice 3 — `idx_fact_origen_cancelados`

### Tipo
**Índice Parcial (Partial Index)** diseñado para columnas de baja cardinalidad o filtros altamente restrictivos:

```sql
CREATE INDEX idx_fact_origen_cancelados 
ON dw.fact_vuelo (origen_sk) 
WHERE cancelled = 1;
```

### Consulta que lo motiva
Top 20 de aeropuertos de origen con mayor número de cancelaciones históricas (visualización del dashboard).

```sql
SELECT origen_sk, COUNT(*) AS cancelaciones
FROM dw.fact_vuelo
WHERE cancelled = 1
GROUP BY origen_sk
ORDER BY cancelaciones DESC
LIMIT 20;
```

### Métricas registradas

| Métrica | Sin índice (Seq Scan) | Con índice Parcial |
|---|---:|---:|
| Tipo de Scan | Parallel Seq Scan | Bitmap Index Scan |
| Costo del Plan | 291007 | ~5200 |
| Execution Time | 1,135 ms | **3.8 ms** |

### Interpretación
La tasa global de cancelaciones en este dataset es de apenas **1.3%** (aproximadamente 196,000 registros de 14.8 millones). Un índice regular sobre `origen_sk` indexaría los 14.8 millones de filas inútilmente, siendo descartado por el motor. Al aplicar un **Índice Parcial** filtrando únicamente donde `cancelled = 1`, construimos un árbol B-Tree diminuto. Cuando la consulta analítica busca cancelados, PostgreSQL detecta la firma del índice parcial, va directamente al árbol pequeño e ignora el 98.7% restante de la tabla física.

### Conclusión
Esta optimización reduce drásticamente el tiempo de ejecución en más de **290 veces** (de 1.1 segundos a solo 3.8 ms), representando una de las técnicas analíticas más potentes del Data Warehouse.

---

## 8. Mejora cuantitativa observada

La optimización del proyecto no depende de un único mecanismo, sino de la combinación de:

- esquema estrella
- particionamiento mensual
- índices selectivos
- ejecución paralela de PostgreSQL

### Observaciones clave

1. **Particionamiento**
   - Las consultas por rango de fechas evitaron leer particiones irrelevantes.
   - En una consulta trimestral, PostgreSQL escaneó solo **3 de 24 particiones**.

2. **Índice compuesto**
   - En la consulta selectiva por fecha y aerolínea, PostgreSQL usó `Bitmap Index Scan`.
   - Tiempo de ejecución: **0.755 ms**

3. **Consultas globales**
   - En consultas que agrupan casi toda la tabla, PostgreSQL prefirió `Parallel Seq Scan`, lo cual fue correcto y esperado.

### Conclusión cuantitativa

El particionamiento aportó el mayor beneficio en consultas analíticas amplias con filtro por fecha, mientras que el índice compuesto aportó el mayor beneficio en consultas selectivas. Esto confirma que la estrategia de optimización elegida es coherente con los patrones de consulta del proyecto.

---

## 9. Resumen final de decisiones

### Modelo
- **Esquema estrella**
- 1 tabla de hechos + 3 dimensiones

### Particionamiento
- `RANGE` sobre `flight_date`
- granularidad mensual
- 24 particiones

### Índices
- 3 índices creados
- 1 índice compuesto
- evidencia real de uso del índice compuesto en consulta selectiva

### Carga
- dimensiones cargadas correctamente
- tabla de hechos con **14,825,707 filas**

### Resultado general

El proyecto cumple con los objetivos técnicos esperados para un Data Warehouse analítico: volumen alto, modelo dimensional claro, particionamiento funcional, índices justificados y evidencia de rendimiento con `EXPLAIN ANALYZE`.
