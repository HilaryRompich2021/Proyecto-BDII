# Documentación del Dashboard — Airline On-Time Performance

## 1. Objetivo del dashboard

El dashboard tiene como objetivo presentar de forma visual los principales resultados del Data Warehouse construido para el análisis de vuelos de aerolíneas en Estados Unidos, utilizando el dataset **Airline On-Time Performance (BTS)** para los años **2023 y 2024**.

El dashboard no es el producto central del proyecto, sino una evidencia de que el Data Warehouse puede ser consultado directamente desde una herramienta BI y que responde preguntas de negocio definidas previamente.

---

## 2. Fuente de datos

El dashboard se conecta directamente a la base de datos PostgreSQL donde se encuentra cargado el Data Warehouse.

### Datos de conexión utilizados

- **Servidor:** `127.0.0.1`
- **Puerto:** `5433`
- **Base de datos:** `airline_dw`
- **Usuario:** `postgres`
- **Contraseña:** `postgres`
- **Esquema:** `dw`

> Importante: PostgreSQL debe estar activo en Docker antes de abrir el dashboard en Tableau.

Comando de referencia para validar el contenedor:

```powershell
docker ps
```

Debe observarse un contenedor PostgreSQL con un puerto similar a:

```text
0.0.0.0:5433->5432/tcp   airline-dw
```

---

## 3. Tablas utilizadas en Tableau

El dashboard utiliza las tablas directas del modelo dimensional, no archivos CSV ni Parquet importados manualmente.

Tablas utilizadas:

- `dw.fact_vuelo`
- `dw.dim_tiempo`
- `dw.dim_aerolinea`
- `dw.dim_aeropuerto`
- `dw.dim_aeropuerto` reutilizada como segunda relación para destino

En Tableau, la dimensión aeropuerto puede aparecer duplicada visualmente como:

- `dim_aeropuerto` → aeropuerto de origen
- `dim_aeropuerto1` → aeropuerto de destino

Esto es correcto, porque en el modelo dimensional la misma tabla `dim_aeropuerto` se reutiliza dos veces: una para representar el aeropuerto de origen y otra para representar el aeropuerto de destino.

---

## 4. Relaciones utilizadas

Las relaciones del dashboard corresponden al esquema estrella del Data Warehouse:

| Tabla de hechos | Dimensión | Relación |
|---|---|---|
| `fact_vuelo` | `dim_tiempo` | `fact_vuelo.tiempo_sk = dim_tiempo.tiempo_sk` |
| `fact_vuelo` | `dim_aerolinea` | `fact_vuelo.aerolinea_sk = dim_aerolinea.aerolinea_sk` |
| `fact_vuelo` | `dim_aeropuerto` | `fact_vuelo.origen_sk = dim_aeropuerto.aeropuerto_sk` |
| `fact_vuelo` | `dim_aeropuerto` | `fact_vuelo.destino_sk = dim_aeropuerto.aeropuerto_sk` |

---

## 5. Preguntas de negocio respondidas

El dashboard responde las siguientes preguntas de negocio:

1. ¿Cómo se comportan los retrasos promedio de llegada a lo largo del tiempo?
2. ¿Qué aerolíneas presentan mayor retraso promedio?
3. ¿Cuál es el total de vuelos registrados en el Data Warehouse?
4. ¿Cuál es el porcentaje de vuelos cancelados?
5. ¿Cómo se distribuyen las principales causas de retraso por trimestre?

---

## 6. Visualizaciones del dashboard

### 6.1 Tendencia mensual de retrasos

Muestra el comportamiento del retraso promedio de llegada por mes durante 2023 y 2024.

**Campos principales:**

- `flight_date` o `fecha`
- `arr_delay`

**Tipo de visualización:** línea temporal.

**Valor analítico:** permite identificar meses con mayor o menor retraso promedio.

---

### 6.2 Retraso promedio por aerolínea

Compara el retraso promedio de llegada entre aerolíneas.

**Campos principales:**

- `nombre_aerolinea`
- `arr_delay`

**Tipo de visualización:** barras comparativas.

**Valor analítico:** permite identificar qué aerolíneas presentan mayores retrasos promedio.

---

### 6.3 Indicadores KPI

Incluye indicadores agregados para resumir el comportamiento general del Data Warehouse.

**KPIs utilizados:**

- Total de vuelos
- Retraso promedio
- Porcentaje de vuelos cancelados

**Campos principales:**

- `flight_sk` o conteo de registros
- `arr_delay`
- `cancelled`

**Valor analítico:** permite visualizar rápidamente el tamaño del dataset y el comportamiento general de retrasos y cancelaciones.

---

### 6.4 Distribución de causas de retraso por trimestre

Muestra cómo se distribuyen las principales causas de retraso a lo largo de los trimestres.

**Campos principales:**

- `trimestre`
- `carrier_delay`
- `weather_delay`
- `nas_delay`
- `security_delay`
- `late_aircraft_delay`

**Tipo de visualización:** barras apiladas o comparativas.

**Valor analítico:** permite observar qué tipo de causa aporta más minutos de retraso en cada trimestre.

> Esta visualización funciona como distribución porque muestra la composición de las causas de retraso por periodo.

---

## 7. Filtro interactivo

El dashboard incluye al menos un filtro interactivo funcional.

La interacción principal consiste en seleccionar un punto, mes o rango dentro de la tendencia mensual para filtrar el resto de visualizaciones del dashboard.

Al aplicar el filtro, cambian los KPIs, la comparación por aerolínea y la distribución de causas de retraso.

Esto permite analizar subconjuntos específicos de tiempo sin cambiar la conexión ni recargar los datos.

---

## 8. Validación de conexión

Antes de abrir Tableau, se recomienda validar que PostgreSQL esté activo y que la tabla de hechos tenga los registros esperados.

Consulta de validación:

```sql
SELECT COUNT(*) AS total_vuelos
FROM dw.fact_vuelo;
```

Resultado esperado:

```text
14,825,707
```

También puede validarse la carga general con:

```sql
SELECT 'dim_tiempo' AS tabla, COUNT(*) FROM dw.dim_tiempo
UNION ALL
SELECT 'dim_aerolinea', COUNT(*) FROM dw.dim_aerolinea
UNION ALL
SELECT 'dim_aeropuerto', COUNT(*) FROM dw.dim_aeropuerto
UNION ALL
SELECT 'fact_vuelo', COUNT(*) FROM dw.fact_vuelo;
```

Resultado esperado:

```text
dim_tiempo       731
dim_aerolinea    10
dim_aeropuerto   362
fact_vuelo       14825707
```

---

## 9. Consideraciones para la demo

Para presentar el dashboard correctamente:

1. Encender Docker Desktop.
2. Verificar que el contenedor `airline-dw` esté activo.
3. Confirmar que el puerto usado sea `5433`.
4. Abrir Tableau Desktop.
5. Abrir el archivo del dashboard.
6. Validar que la conexión apunte a PostgreSQL y no a archivos locales.
7. Probar el filtro interactivo antes de la exposición.

---

## 10. Conclusión

El dashboard demuestra que el Data Warehouse construido en PostgreSQL puede ser consultado directamente desde Tableau. Las visualizaciones permiten analizar retrasos por tiempo, aerolínea y causas, además de mostrar indicadores agregados del volumen de vuelos y cancelaciones.

El dashboard complementa la parte técnica del proyecto, pero la base principal del trabajo sigue siendo el Data Warehouse optimizado con modelo dimensional, particionamiento, índices y evidencia mediante `EXPLAIN ANALYZE`.
