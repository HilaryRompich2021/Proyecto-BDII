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

## 4. Estrategia de particionamiento

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

## 5. Evidencia de partition pruning

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

## 6. Estrategia de índices

Se definieron 3 índices sobre la tabla de hechos:

1. `idx_fact_aerolinea`
2. `idx_fact_fecha_aerolinea`
3. `idx_fact_origen`

La idea fue alinear cada índice con patrones de consulta esperados en el dashboard y en el análisis técnico.

---

## 6.1 Índice 1 — `idx_fact_aerolinea`

### Tipo
Índice simple sobre:

```sql
(aerolinea_sk)
```

### Consulta que lo motiva

```sql
SELECT aerolinea_sk, AVG(arr_delay)
FROM dw.fact_vuelo
GROUP BY aerolinea_sk
ORDER BY AVG(arr_delay) DESC;
```

### Métricas registradas

| Métrica | Sin índice | Con índice |
|---|---:|---:|
| Costo estimado | 336529–336581 | 336529–336581 |
| Execution Time | 1566 ms | 1592 ms |

### Interpretación

En esta consulta PostgreSQL eligió correctamente `Parallel Seq Scan`, porque la operación requiere procesar prácticamente toda la tabla para agrupar por aerolínea.

### Conclusión

Este índice no aporta una mejora significativa en consultas de agregación global sobre toda la tabla, pero sí puede ser útil en consultas más selectivas del tipo:

```sql
WHERE aerolinea_sk = N
```

---

## 6.2 Índice 2 — `idx_fact_fecha_aerolinea`

### Tipo
Índice compuesto sobre:

```sql
(flight_date, aerolinea_sk)
```

### Consulta que lo motiva

```sql
EXPLAIN ANALYZE
SELECT COUNT(*) AS total_vuelos, AVG(arr_delay) AS retraso_promedio
FROM dw.fact_vuelo
WHERE flight_date = DATE '2024-01-15'
  AND aerolinea_sk = 1;
```

### Fragmento relevante del plan

```text
Bitmap Heap Scan on fact_vuelo_2024_01 fact_vuelo
  Recheck Cond: ((flight_date = '2024-01-15'::date) AND (aerolinea_sk = 1))
  -> Bitmap Index Scan on fact_vuelo_2024_01_flight_date_aerolinea_sk_idx
       Index Cond: ((flight_date = '2024-01-15'::date) AND (aerolinea_sk = 1))
```

### Resultado observado

- Filas encontradas: **653**
- Partición usada: **fact_vuelo_2024_01**
- **Execution Time:** **0.755 ms**

### Interpretación

Aquí sí se observa claramente el valor del índice compuesto. PostgreSQL:

1. aplicó primero el particionamiento, usando solo la partición de enero 2024
2. dentro de esa partición utilizó el índice compuesto para localizar las filas exactas
3. evitó recorrer secuencialmente toda la partición

### Conclusión

Este índice compuesto sí aporta valor en consultas **altamente selectivas** que filtran simultáneamente por:

- fecha específica
- aerolínea específica

Por eso es el índice más fuerte para defender técnicamente en este proyecto.

---

## 6.3 Índice 3 — `idx_fact_origen`

### Tipo
Índice simple sobre:

```sql
(origen_sk)
```

### Consulta que lo motiva

```sql
SELECT origen_sk, COUNT(*) AS cancelaciones
FROM dw.fact_vuelo
WHERE cancelled = 1
GROUP BY origen_sk
ORDER BY cancelaciones DESC
LIMIT 20;
```

### Métricas registradas

| Métrica | Sin índice | Con índice |
|---|---:|---:|
| Costo estimado | 291007–291064 | 291007–291064 |
| Execution Time | 1135 ms | 1108 ms |

### Interpretación

La mejora fue pequeña. El motivo es que la consulta filtra por `cancelled = 1`, pero no existe un índice específico sobre ese predicado. Por ello, el índice en `origen_sk` por sí solo no logra una optimización fuerte.

### Conclusión

El índice cumple como parte del diseño solicitado, pero una mejora futura más efectiva sería usar un índice parcial, por ejemplo:

```sql
CREATE INDEX idx_fact_origen_cancelled
ON dw.fact_vuelo (origen_sk)
WHERE cancelled = 1;
```

---

## 7. Mejora cuantitativa observada

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

## 8. Resumen final de decisiones

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
