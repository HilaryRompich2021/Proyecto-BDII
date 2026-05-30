# Documentación del Dashboard — Airline On-Time Performance

## 1. Objetivo del dashboard

El dashboard permite consultar y analizar el Data Warehouse construido en PostgreSQL a partir del dataset **Airline On-Time Performance (BTS)** para los años **2023–2024**.

Su objetivo principal es mostrar que el Data Warehouse es consultable desde una herramienta BI y que puede responder preguntas analíticas sobre retrasos, cancelaciones, aerolíneas, aeropuertos y causas de retraso.

> El dashboard es un entregable de soporte. El producto central del proyecto es el Data Warehouse optimizado en PostgreSQL.

---

## 2. Fuente de datos

**Herramienta BI:** Tableau Desktop  
**Conexión:** Directa a PostgreSQL  
**Base de datos:** `airline_dw`  
**Esquema:** `dw`  
**Modo de conexión:** En tiempo real  
**Servidor:**  `localhost`  
**Puerto:** `5433`  
**Usuario:** `postgres`  
**Contraseña:** `postgres`

> Para abrir correctamente el dashboard, el contenedor Docker de PostgreSQL debe estar encendido y exponiendo el puerto `5433`.

Comando recomendado para verificar que el contenedor esté activo:

```powershell
docker ps
```

Debe observarse una salida similar a:

```text
0.0.0.0:5433->5432/tcp   airline-dw
```

También puede validarse la conexión ejecutando:

```powershell
docker exec airline-dw psql -U postgres -d airline_dw -c "SELECT COUNT(*) FROM dw.fact_vuelo;"
```

Resultado esperado:

```text
14825707
```

---

## 3. Tablas utilizadas en Tableau

El dashboard se construyó usando las tablas del modelo dimensional directamente desde PostgreSQL:

- `dw.fact_vuelo`
- `dw.dim_tiempo`
- `dw.dim_aerolinea`
- `dw.dim_aeropuerto`

En Tableau, `dim_aeropuerto` se utiliza dos veces:

- una vez para representar el **aeropuerto de origen**;
- otra vez para representar el **aeropuerto de destino**.

Esto se debe a que `dim_aeropuerto` es una dimensión reutilizada o *role-playing dimension*.

---

## 4. Relaciones utilizadas

Las relaciones principales del modelo en Tableau son:

| Tabla principal | Campo | Tabla relacionada | Campo relacionado | Propósito |
|---|---|---|---|---|
| `fact_vuelo` | `tiempo_sk` | `dim_tiempo` | `tiempo_sk` | Analizar vuelos por fecha, mes, trimestre y año |
| `fact_vuelo` | `aerolinea_sk` | `dim_aerolinea` | `aerolinea_sk` | Analizar vuelos por aerolínea |
| `fact_vuelo` | `origen_sk` | `dim_aeropuerto` | `aeropuerto_sk` | Analizar aeropuerto de origen |
| `fact_vuelo` | `destino_sk` | `dim_aeropuerto` | `aeropuerto_sk` | Analizar aeropuerto de destino |

---

## 5. Preguntas de negocio respondidas

El dashboard responde las siguientes preguntas de negocio:

1. ¿Qué aerolínea tiene el mayor retraso promedio de llegada?
2. ¿Cuál es la tendencia mensual de retrasos durante 2023–2024?
3. ¿Cuál es el total de vuelos analizados?
4. ¿Cuál es el retraso promedio general?
5. ¿Qué porcentaje de vuelos fue cancelado?
6. ¿Cómo se distribuyen las principales causas de retraso por trimestre?

---

## 6. Visualizaciones del dashboard

### 6.1 Tendencia mensual de retrasos

**Tipo:** Gráfico de línea  
**Campos principales:**

- `anio`
- `mes`
- `arr_delay`

**Propósito:**  
Muestra cómo cambia el retraso promedio de llegada a lo largo del tiempo.

Esta visualización permite identificar meses con mayor o menor retraso promedio y observar patrones temporales entre 2023 y 2024.

---

### 6.2 Retraso promedio por aerolínea

**Tipo:** Barras horizontales  
**Campos principales:**

- `nombre_aerolinea`
- `arr_delay`

**Propósito:**  
Compara el retraso promedio de llegada entre aerolíneas.

Permite identificar qué aerolíneas presentan mayores retrasos promedio y cuáles tienen mejor desempeño relativo.

---

### 6.3 KPI: total de vuelos

**Tipo:** Indicador agregado  
**Campo principal:**

- `COUNT(flight_sk)` o conteo de registros de `fact_vuelo`

**Propósito:**  
Muestra el volumen total de vuelos disponibles para el análisis.

Valor esperado del Data Warehouse:

```text
14,825,707 vuelos
```

---

### 6.4 KPI: retraso promedio

**Tipo:** Indicador agregado  
**Campo principal:**

- `AVG(arr_delay)`

**Propósito:**  
Muestra el retraso promedio de llegada considerando los vuelos del periodo analizado.

---

### 6.5 KPI: porcentaje de cancelados

**Tipo:** Indicador agregado  
**Campo principal:**

- `cancelled`

**Propósito:**  
Muestra el porcentaje de vuelos cancelados dentro del total de vuelos analizados.

Una forma de calcularlo es:

```text
SUM(cancelled) / COUNT(flight_sk)
```

---

### 6.6 Distribución de causas de retraso por trimestre

**Tipo:** Barras apiladas  
**Campos principales:**

- `trimestre`
- `carrier_delay`
- `weather_delay`
- `nas_delay`
- `late_aircraft_delay`

**Propósito:**  
Muestra cómo se distribuyen las principales causas de retraso por trimestre.

Esta visualización permite comparar si los retrasos se deben principalmente a la aerolínea, al clima, al sistema aéreo NAS o a la llegada tardía de aeronaves.

---

## 7. Filtro interactivo

El dashboard incluye interacción entre visualizaciones.

La tendencia mensual puede utilizarse como filtro para afectar las demás visualizaciones del dashboard. Al seleccionar un mes o punto temporal, las visualizaciones relacionadas se actualizan para mostrar los datos correspondientes a ese periodo.

Esto permite analizar el comportamiento de aerolíneas, KPIs y causas de retraso según el periodo seleccionado.

---

## 8. Validaciones realizadas

Antes de usar Tableau, se validó en PostgreSQL que el Data Warehouse estuviera correctamente cargado.

### Conteo final de la tabla de hechos

```sql
SELECT COUNT(*) FROM dw.fact_vuelo;
```

Resultado esperado:

```text
14,825,707
```

### Conteo por tablas principales

```sql
SELECT 'dim_tiempo' AS tabla, COUNT(*) FROM dw.dim_tiempo
UNION ALL
SELECT 'dim_aerolinea', COUNT(*) FROM dw.dim_aerolinea
UNION ALL
SELECT 'dim_aeropuerto', COUNT(*) FROM dw.dim_aeropuerto
UNION ALL
SELECT 'fact_vuelo', COUNT(*) FROM dw.fact_vuelo;
```

Resultados esperados:

| Tabla | Registros |
|---|---:|
| `dim_tiempo` | 731 |
| `dim_aerolinea` | 10 |
| `dim_aeropuerto` | 362 |
| `fact_vuelo` | 14,825,707 |

---

## 9. Consideraciones para la demo

Antes de abrir Tableau, ejecutar:

```powershell
docker start airline-dw
```

Luego verificar:

```powershell
docker ps
```

La conexión debe mostrar:

```text
0.0.0.0:5433->5432/tcp
```

Si Tableau muestra error de conexión, revisar:

1. que Docker Desktop esté abierto;
2. que el contenedor `airline-dw` esté encendido;
3. que el puerto sea `5433`;
4. que la base de datos sea `airline_dw`;
5. que el usuario y contraseña sean `postgres`.

---

## 10. Relación con los requisitos del proyecto

El dashboard cumple con los requisitos funcionales solicitados para la capa BI:

- conexión directa a PostgreSQL;
- mínimo 4 visualizaciones analíticas;
- tendencia temporal;
- comparativa por categoría;
- KPIs agregados;
- distribución de causas de retraso;
- filtro interactivo funcional.

El dashboard no reemplaza la evidencia técnica del Data Warehouse; sirve como demostración visual de que el modelo dimensional es consultable y útil para análisis.
<!-- actualización documentación dashboard -->