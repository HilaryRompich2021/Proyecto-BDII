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

-- ── ÍNDICE 1: idx_fact_aerolinea (simple sobre aerolinea_sk) ─────────────────
-- Consulta que lo motiva: retraso promedio por aerolínea (KPI del dashboard)

-- ANTES (sin índice):
DROP INDEX IF EXISTS dw.idx_fact_aerolinea;

EXPLAIN ANALYZE
SELECT aerolinea_sk, AVG(arr_delay)
FROM dw.fact_vuelo
GROUP BY aerolinea_sk
ORDER BY AVG(arr_delay) DESC;

-- DESPUÉS (con índice):
CREATE INDEX idx_fact_aerolinea ON dw.fact_vuelo (aerolinea_sk);

EXPLAIN ANALYZE
SELECT aerolinea_sk, AVG(arr_delay)
FROM dw.fact_vuelo
GROUP BY aerolinea_sk
ORDER BY AVG(arr_delay) DESC;

-- Resultado documentado:
-- Sin índice: 1,566 ms | Con índice: 1,592 ms
-- Análisis: Para GROUP BY sobre toda la tabla PostgreSQL elige correctamente
-- Parallel Seq Scan sobre Index Scan (selectividad baja = todas las filas).
-- El índice beneficia queries con WHERE aerolinea_sk = N (selectividad alta).

-- ── ÍNDICE 2: idx_fact_fecha_aerolinea (compuesto: flight_date, aerolinea_sk) ─
-- Consulta que lo motiva: tendencia mensual de retrasos por aerolínea (dashboard)

-- ANTES (sin índice):
DROP INDEX IF EXISTS dw.idx_fact_fecha_aerolinea;

EXPLAIN ANALYZE
SELECT flight_date, aerolinea_sk, AVG(arr_delay)
FROM dw.fact_vuelo
WHERE flight_date BETWEEN '2024-01-01' AND '2024-03-31'
GROUP BY flight_date, aerolinea_sk
ORDER BY flight_date;

-- DESPUÉS (con índice):
CREATE INDEX idx_fact_fecha_aerolinea ON dw.fact_vuelo (flight_date, aerolinea_sk);

EXPLAIN ANALYZE
SELECT flight_date, aerolinea_sk, AVG(arr_delay)
FROM dw.fact_vuelo
WHERE flight_date BETWEEN '2024-01-01' AND '2024-03-31'
GROUP BY flight_date, aerolinea_sk
ORDER BY flight_date;

-- Resultado documentado:
-- Sin índice: 241 ms | Con índice: 277 ms
-- Análisis: El particionamiento ya elimina 21 particiones.
-- El índice compuesto maximiza su beneficio en queries con filtro simultáneo
-- de fecha Y aerolínea específica: WHERE flight_date BETWEEN ... AND aerolinea_sk = N

-- ── ÍNDICE 3: idx_fact_origen (simple sobre origen_sk) ───────────────────────
-- Consulta que lo motiva: aeropuertos con más cancelaciones (dashboard)

-- ANTES (sin índice):
DROP INDEX IF EXISTS dw.idx_fact_origen;

EXPLAIN ANALYZE
SELECT origen_sk, COUNT(*) AS cancelaciones
FROM dw.fact_vuelo
WHERE cancelled = 1
GROUP BY origen_sk
ORDER BY cancelaciones DESC
LIMIT 20;

-- DESPUÉS (con índice):
CREATE INDEX idx_fact_origen ON dw.fact_vuelo (origen_sk);

EXPLAIN ANALYZE
SELECT origen_sk, COUNT(*) AS cancelaciones
FROM dw.fact_vuelo
WHERE cancelled = 1
GROUP BY origen_sk
ORDER BY cancelaciones DESC
LIMIT 20;

-- Resultado documentado:
-- Sin índice: 1,135 ms | Con índice: 1,108 ms
-- Análisis: El filtro WHERE cancelled = 1 (sin índice propio) fuerza full scan.
-- Mejora marginal de 27 ms. Optimización identificada: índice parcial
-- CREATE INDEX idx_fact_cancelados ON dw.fact_vuelo (origen_sk) WHERE cancelled = 1

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
