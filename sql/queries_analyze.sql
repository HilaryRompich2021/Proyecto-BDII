-- queries_analyze.sql
-- Proyecto Final — Base de Datos II (031)
-- Consultas usadas para EXPLAIN ANALYZE documentadas en technical-decisions.md
-- Ejecutar manualmente en pgAdmin contra la base de datos airline_dw
-- NO son ejecutadas por el pipeline ETL

SET search_path = dw;

-- =============================================================================
-- SECCIÓN 1: PARTITION PRUNING
-- Demuestra que PostgreSQL descarta particiones automáticamente con filtro de fecha
-- =============================================================================

-- 1A. Sin filtro de fecha — escanea las 24 particiones (baseline)
EXPLAIN ANALYZE
SELECT aerolinea_sk, AVG(arr_delay)
FROM dw.fact_vuelo
GROUP BY aerolinea_sk
ORDER BY AVG(arr_delay) DESC;

-- Resultado documentado:
-- Partitions scanned: 24 de 24
-- Execution Time: 1,566 ms

-- 1B. Con filtro de fecha Q1 2024 — demuestra partition pruning
EXPLAIN ANALYZE
SELECT aerolinea_sk, AVG(arr_delay)
FROM dw.fact_vuelo
WHERE flight_date BETWEEN '2024-01-01' AND '2024-03-31'
GROUP BY aerolinea_sk;

-- Resultado documentado:
-- Partitions scanned: 3 de 24 (fact_vuelo_2024_01, _02, _03)
-- Execution Time: 220 ms
-- Mejora: 86% más rápido, 88% menos filas examinadas

-- =============================================================================
-- SECCIÓN 2: EVIDENCIA DE ÍNDICES — ANTES Y DESPUÉS
-- Para cada índice: ejecutar DROP, medir, recrear, medir de nuevo
-- =============================================================================

-- ── ÍNDICE 1: idx_fact_aerolinea_cubriente (cubriente sobre aerolinea_sk) ─────
-- Consulta que lo motiva: retraso promedio por aerolínea (KPI del dashboard)

-- ANTES (sin índice):
DROP INDEX IF EXISTS dw.idx_fact_aerolinea_cubriente;

EXPLAIN ANALYZE
SELECT aerolinea_sk, AVG(arr_delay)
FROM dw.fact_vuelo
GROUP BY aerolinea_sk
ORDER BY AVG(arr_delay) DESC;

-- DESPUÉS (con índice cubriente):
CREATE INDEX idx_fact_aerolinea_cubriente ON dw.fact_vuelo (aerolinea_sk) INCLUDE (arr_delay);

EXPLAIN ANALYZE
SELECT aerolinea_sk, AVG(arr_delay)
FROM dw.fact_vuelo
GROUP BY aerolinea_sk
ORDER BY AVG(arr_delay) DESC;

-- Resultado esperado:
-- Sin índice: ~1,560 ms | Con índice: ~600-800 ms
-- Análisis: Al incluir arr_delay en el índice, PostgreSQL puede hacer un 
-- Parallel Index Only Scan, evitando por completo leer la tabla principal (Heap).
-- Esto reduce significativamente los accesos a disco.

-- ── ÍNDICE 2: idx_fact_fecha_aerolinea (compuesto: flight_date, aerolinea_sk) ─
-- Consulta que lo motiva: drill-down selectivo en el dashboard por fecha Y aerolínea

-- ANTES (sin índice):
DROP INDEX IF EXISTS dw.idx_fact_fecha_aerolinea;

EXPLAIN ANALYZE
SELECT COUNT(*) AS total_vuelos, AVG(arr_delay) AS retraso_promedio
FROM dw.fact_vuelo
WHERE flight_date = '2024-01-15'
  AND aerolinea_sk = 1;

-- DESPUÉS (con índice compuesto):
CREATE INDEX idx_fact_fecha_aerolinea ON dw.fact_vuelo (flight_date, aerolinea_sk);

EXPLAIN ANALYZE
SELECT COUNT(*) AS total_vuelos, AVG(arr_delay) AS retraso_promedio
FROM dw.fact_vuelo
WHERE flight_date = '2024-01-15'
  AND aerolinea_sk = 1;

-- Resultado esperado:
-- Sin índice: ~100-200 ms | Con índice compuesto: < 1 ms (ej. 0.75 ms)
-- Análisis: La consulta filtra por un día específico y aerolínea (alta selectividad).
-- El motor aplica partition pruning (va directo a fact_vuelo_2024_01) y dentro de 
-- esa partición usa el índice compuesto mediante Bitmap Index Scan, ubicando las
-- filas exactas al instante en lugar de escanear toda la partición.

-- ── ÍNDICE 3: idx_fact_origen_cancelados (parcial sobre origen_sk) ───────────
-- Consulta que lo motiva: aeropuertos con más cancelaciones (dashboard)

-- ANTES (sin índice):
DROP INDEX IF EXISTS dw.idx_fact_origen_cancelados;

EXPLAIN ANALYZE
SELECT origen_sk, COUNT(*) AS cancelaciones
FROM dw.fact_vuelo
WHERE cancelled = 1
GROUP BY origen_sk
ORDER BY cancelaciones DESC
LIMIT 20;

-- DESPUÉS (con índice parcial):
CREATE INDEX idx_fact_origen_cancelados 
    ON dw.fact_vuelo (origen_sk) 
    WHERE cancelled = 1;

EXPLAIN ANALYZE
SELECT origen_sk, COUNT(*) AS cancelaciones
FROM dw.fact_vuelo
WHERE cancelled = 1
GROUP BY origen_sk
ORDER BY cancelaciones DESC
LIMIT 20;

-- Resultado esperado:
-- Sin índice: ~1,100 ms | Con índice parcial: < 5 ms
-- Análisis: Como solo el ~1.3% de los vuelos son cancelados, el índice parcial 
-- sólo almacena las llaves de esos registros. Al buscar con WHERE cancelled = 1,
-- PostgreSQL usa el índice parcial (Bitmap Index Scan) y accede únicamente a las 
-- filas necesarias en lugar de escanear secuencialmente los 14.8 millones de registros.

-- =============================================================================
-- SECCIÓN 3: VERIFICACIÓN POST-CARGA
-- =============================================================================

-- Conteo total y por partición
SELECT tableoid::regclass AS particion,
       COUNT(*)           AS filas
FROM dw.fact_vuelo
GROUP BY tableoid
ORDER BY particion;

-- Totales por tabla
SELECT 'dim_tiempo'      AS tabla, COUNT(*) AS filas FROM dw.dim_tiempo
UNION ALL
SELECT 'dim_aerolinea',           COUNT(*)           FROM dw.dim_aerolinea
UNION ALL
SELECT 'dim_aeropuerto',          COUNT(*)           FROM dw.dim_aeropuerto
UNION ALL
SELECT 'fact_vuelo (total)',       COUNT(*)           FROM dw.fact_vuelo;

-- Verificar FK activas
SELECT conname AS constraint_name, contype AS tipo
FROM pg_constraint
WHERE conrelid = 'dw.fact_vuelo'::regclass;

-- Verificar índices creados
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'dw'
ORDER BY indexname;

-- Muestra de datos con JOIN completo
SELECT f.flight_date,
       a.nombre_aerolinea,
       o.iata_code  AS origen,
       d.iata_code  AS destino,
       f.arr_delay,
       f.cancelled
FROM dw.fact_vuelo f
JOIN dw.dim_aerolinea  a ON f.aerolinea_sk  = a.aerolinea_sk
JOIN dw.dim_aeropuerto o ON f.origen_sk     = o.aeropuerto_sk
JOIN dw.dim_aeropuerto d ON f.destino_sk    = d.aeropuerto_sk
JOIN dw.dim_tiempo     t ON f.tiempo_sk     = t.tiempo_sk
LIMIT 20;
