# Dashboard — Documentación Técnica
> Airline On-Time Performance · BTS 2023–2024  
> Herramienta: Tableau Desktop  
> Conexión: PostgreSQL local · esquema `dw` · base de datos `airline_dw`

---

## Conexión a PostgreSQL

El dashboard se conecta **directamente a PostgreSQL** — no importa CSVs ni archivos intermedios.

Configuración de conexión en Tableau:
- Servidor: `localhost`
- Puerto: `5432`
- Base de datos: `airline_dw`
- Usuario: `postgres`
- Esquema: `dw`

---

## Modelo de datos en Tableau

Se definieron relaciones entre tablas directamente en la fuente de datos de Tableau, replicando el esquema estrella del Data Warehouse:

| Tabla izquierda | Campo | Tabla derecha | Campo |
|---|---|---|---|
| `fact_vuelo` | `aerolinea_sk` | `dim_aerolinea` | `aerolinea_sk` |
| `fact_vuelo` | `tiempo_sk` | `dim_tiempo` | `tiempo_sk` |
| `fact_vuelo` | `origen_sk` | `dim_aeropuerto` | `aeropuerto_sk` |
| `fact_vuelo` | `destino_sk` | `dim_aeropuerto1` | `aeropuerto_sk` |

> `dim_aeropuerto` se usa dos veces (role-playing dimension): una instancia para origen y otra para destino. Tableau las nombra `dim_aeropuerto` y `dim_aeropuerto1` internamente.

---

## Visualización 1 — Tendencia Mensual de Retrasos

**Pregunta de negocio que responde:** ¿Cuál es la tendencia mensual de retrasos a lo largo de 2023 y 2024?

**Tipo de gráfico:** Línea temporal

**Configuración en Tableau:**

| Zona | Campo | Tratamiento |
|---|---|---|
| Columnas | `Anio` (dim_tiempo) | Dimensión discreta |
| Columnas | `Mes` (dim_tiempo) | Dimensión discreta |
| Filas | `Arr Delay` (fact_vuelo) | Medida → Promedio |
| Marcas | Línea | — |

**Qué representa:** Cada punto en la línea es el retraso promedio de llegada (en minutos) de todos los vuelos de ese mes. El eje X muestra los 24 meses (enero 2023 a diciembre 2024) separados por año. El eje Y muestra minutos de retraso promedio.

**Hallazgo principal:** Julio es consistentemente el mes con más retrasos en ambos años (~15–17 minutos promedio), mientras que noviembre registra los menores retrasos. Esto refleja el efecto de la temporada de verano (mayor volumen de vuelos) sobre los retrasos.

**Rol en el dashboard:** También funciona como **filtro interactivo** — al hacer clic en cualquier punto de la línea, todas las demás visualizaciones del dashboard se filtran para mostrar solo los datos de ese mes.

---

## Visualización 2 — Retraso Promedio por Aerolínea

**Pregunta de negocio que responde:** ¿Qué aerolínea tiene el mayor retraso promedio de llegada en 2023–2024?

**Tipo de gráfico:** Barras horizontales ordenadas descendentemente

**Configuración en Tableau:**

| Zona | Campo | Tratamiento |
|---|---|---|
| Filas | `Nombre Aerolinea` (dim_aerolinea) | Dimensión |
| Columnas | `Arr Delay` (fact_vuelo) | Medida → Promedio |
| Color | `Arr Delay` (fact_vuelo) | Medida → Promedio (gradiente) |
| Etiqueta | `Arr Delay` (fact_vuelo) | Medida → Promedio |
| Marcas | Barra | Ordenadas descendentemente |

**Qué representa:** Cada barra es una aerolínea. La longitud representa el retraso promedio de llegada en minutos durante todo el período 2023–2024. El color refuerza la magnitud — azul oscuro indica mayor retraso.

**Hallazgo principal:** F9 (Frontier Airlines) lidera con 16.21 minutos de retraso promedio, seguida de B6 (JetBlue) con 14.52 minutos. DL (Delta Air Lines) tiene el mejor desempeño con 2.36 minutos promedio.

**Nota:** Los nombres muestran código IATA porque el campo `nombre_aerolinea` en `dim_aerolinea` almacena el código del sistema fuente BTS. La correspondencia es: F9=Frontier, B6=JetBlue, G4=Allegiant, NK=Spirit, AA=American, HA=Hawaiian, UA=United, WN=Southwest, AS=Alaska, DL=Delta.

---

## Visualización 3 — KPIs Agregados

**Pregunta de negocio que responde:** ¿Cuál es el desempeño general del sistema de aviación en 2023–2024?

**Tipo:** Tres métricas de texto (tarjetas KPI)

### KPI 1 — Total de Vuelos

| Zona | Campo | Tratamiento |
|---|---|---|
| Texto (Marcas) | `Flight Sk` (fact_vuelo) | Medida → Recuento |

**Valor:** 14,825,707 vuelos registrados en 2023–2024.

### KPI 2 — Retraso Promedio

| Zona | Campo | Tratamiento |
|---|---|---|
| Texto (Marcas) | `Arr Delay` (fact_vuelo) | Medida → Promedio |

**Valor:** ~6.7 minutos de retraso promedio de llegada sobre todos los vuelos del período.

### KPI 3 — Porcentaje de Cancelados

Campo calculado creado en Tableau:
```
AVG([Cancelled]) * 100
```

| Zona | Campo | Tratamiento |
|---|---|---|
| Texto (Marcas) | `%Cancelados` (calculado) | AGR (promedio agregado) |

**Valor:** 1.327% — aproximadamente 1 de cada 75 vuelos fue cancelado en el período.

---

## Visualización 4 — Causas de Retraso por Trimestre

**Pregunta de negocio que responde:** ¿Qué causa de retraso es más frecuente y cómo varía por trimestre?

**Tipo de gráfico:** Barras apiladas por trimestre

**Configuración en Tableau:**

| Zona | Campo | Tratamiento |
|---|---|---|
| Columnas | `Trimestre` (dim_tiempo) | Dimensión discreta |
| Filas | `Valores de medidas` | Automático |
| Color | `Nombres de medidas` | Filtrado a 4 causas |
| Marcas | Barra apilada | — |

**Medidas incluidas en el filtro:**
- `Prom. Carrier Delay` — retraso atribuible a la aerolínea
- `Prom. Late Aircraft Delay` — aeronave retrasada de vuelo anterior
- `Prom. Nas Delay` — sistema nacional de espacio aéreo (NAS)
- `Prom. Weather Delay` — condiciones climáticas

**Qué representa:** Cada barra es un trimestre (Q1–Q4). La altura total es la suma de los retrasos promedio por causa. Los colores muestran qué porción de los retrasos se atribuye a cada causa.

**Hallazgo principal:** `Carrier Delay` (naranja) es consistentemente la causa dominante en todos los trimestres, representando aproximadamente el 40–50% del retraso total. Q2 y Q3 (primavera-verano) muestran retrasos totales significativamente mayores que Q1 y Q4.

---

## Filtro Interactivo

**Implementación:** La visualización de Tendencia Mensual está configurada como **"Usar como filtro"** en el dashboard.

**Funcionamiento:** Al hacer clic en cualquier punto de la línea de tendencia (un mes específico), todas las demás visualizaciones se actualizan automáticamente para mostrar solo los datos de ese mes:
- Los KPIs muestran totales del mes seleccionado
- Las barras de aerolínea muestran retrasos de ese mes específico
- Las causas de retraso muestran solo el trimestre correspondiente

**Ejemplo documentado:** Al seleccionar julio 2023 (mes de mayor retraso):
- Total vuelos: 638,995
- Retraso promedio: 16.09 minutos
- Aerolínea con más retraso ese mes: B6 (JetBlue) con 42.09 minutos

---

## Queries de referencia

> Estas queries son de **referencia analítica** — se ejecutan manualmente en pgAdmin para verificación o análisis adicional. No son ejecutadas por el pipeline ETL.

**Tendencia mensual:**
```sql
SELECT t.anio, t.mes, t.nombre_mes,
       AVG(f.arr_delay) AS retraso_promedio,
       COUNT(*)          AS total_vuelos
FROM dw.fact_vuelo f
JOIN dw.dim_tiempo t ON f.tiempo_sk = t.tiempo_sk
GROUP BY t.anio, t.mes, t.nombre_mes
ORDER BY t.anio, t.mes;
```

**Retraso por aerolínea:**
```sql
SELECT a.iata_code, a.nombre_aerolinea,
       AVG(f.arr_delay)  AS retraso_promedio,
       COUNT(*)           AS total_vuelos,
       SUM(f.cancelled)   AS cancelaciones
FROM dw.fact_vuelo f
JOIN dw.dim_aerolinea a ON f.aerolinea_sk = a.aerolinea_sk
GROUP BY a.iata_code, a.nombre_aerolinea
ORDER BY retraso_promedio DESC;
```

**Causas de retraso por trimestre:**
```sql
SELECT t.anio, t.trimestre,
       ROUND(AVG(f.carrier_delay)::numeric, 2)        AS causa_aerolinea,
       ROUND(AVG(f.weather_delay)::numeric, 2)        AS causa_clima,
       ROUND(AVG(f.nas_delay)::numeric, 2)            AS causa_nas,
       ROUND(AVG(f.late_aircraft_delay)::numeric, 2)  AS causa_aeronave_tardía
FROM dw.fact_vuelo f
JOIN dw.dim_tiempo t ON f.tiempo_sk = t.tiempo_sk
WHERE f.cancelled = 0
GROUP BY t.anio, t.trimestre
ORDER BY t.anio, t.trimestre;
```

**KPIs generales:**
```sql
SELECT
    COUNT(*)                                              AS total_vuelos,
    ROUND(AVG(arr_delay)::numeric, 2)                    AS retraso_promedio_min,
    ROUND(100.0 * SUM(cancelled) / COUNT(*), 2)          AS pct_cancelados
FROM dw.fact_vuelo;
```

---

*Documento generado como parte de la documentación técnica del proyecto*  
*Ver también: `docs/technical-decisions.md` y `README.md`*
