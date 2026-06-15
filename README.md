# Garmin Training Sync

Proyecto personal para convertir sesiones de entrenamiento escritas en lenguaje natural a entrenamientos estructurados de Garmin Connect.

El flujo actual es:

```text
input_sesion.txt → generate_plan.py → plan_semana.json → sync_week.py → Garmin Connect
```

## Objetivo

Unir running y desarrollo para automatizar la creación y agendamiento de entrenamientos en Garmin Connect.

Permite escribir sesiones como:

```text
Fecha: 2026-07-09
Nombre: Jue09-Jul - Cuestas Lap Natural

Sesión:
hasta lap calentamiento al inicio de la cuesta
5x3min @4:20-4:40 rec 2:30 lap
10 min enfriamiento Z1
```

Y convertirlas automáticamente en un workout Garmin con:

- Calentamiento hasta pulsar Lap
- Repeticiones reales Garmin
- Objetivos de ritmo
- Objetivos de frecuencia cardíaca
- Recuperaciones
- Enfriamiento
- Agendamiento automático en calendario

---

# Arquitectura

```text
input_sesion.txt
        │
        ▼
generate_plan.py
        │
        ▼
plan_semana.json
        │
        ▼
sync_week.py
        │
        ▼
Garmin Connect
```

---

# Archivos principales

## input_sesion.txt

Archivo donde se escriben los entrenamientos en lenguaje natural.

Puede contener una o varias sesiones.

---

## generate_plan.py

Convierte lenguaje natural en JSON estructurado.

Ejecutar:

```bash
python generate_plan.py
```

Genera:

```text
plan_semana.json
```

---

## plan_semana.json

Representación estructurada de los entrenamientos.

Normalmente no se edita manualmente.

---

## sync_week.py

Sincroniza los entrenamientos con Garmin Connect.

Modo preview:

```bash
python sync_week.py --preview
```

Sincronización real:

```bash
python sync_week.py
```

---

# Formato básico

Cada entrenamiento debe tener:

```text
Fecha: YYYY-MM-DD
Nombre: Nombre del entrenamiento

Sesión:
...
```

Ejemplo:

```text
Fecha: 2026-07-01
Nombre: Mié01-Jul - Series

Sesión:
15 min calentamiento Z1
4 x 1 km @4:10-4:25 rec 2 min
10 min enfriamiento Z1
```

---

# Múltiples entrenamientos

Separar usando:

```text
---
```

Ejemplo:

```text
Fecha: 2026-07-01
Nombre: Mié01-Jul - Series

Sesión:
15 min calentamiento Z1
4x1km @4:10-4:25 rec 2min
10 min enfriamiento Z1

---
Fecha: 2026-07-04
Nombre: Sáb04-Jul - Easy Z2

Sesión:
45 min fácil Z2

---
Fecha: 2026-07-05
Nombre: Dom05-Jul - Largo

Sesión:
18 km @5:20-5:50
```

---

# Sintaxis soportada

## Tiempo

```text
45 min
30 min suave
45 min fácil
45 min easy
```

---

## Distancia

```text
10 km
5 km
1.6 km
7.5 km
```

---

## Ritmo objetivo

Rango:

```text
10 km @5:20-5:50
```

Ritmo único:

```text
5 km @4:30
```

---

## Frecuencia cardíaca por zonas

```text
45 min Z2
30 min Z3
10 min calentamiento Z1
```

---

## Frecuencia cardíaca por rango

```text
40 min FC 135-150
```

---

## Calentamiento

```text
15 min calentamiento
15 min calentamiento Z1
```

---

## Enfriamiento

```text
10 min enfriamiento
10 min enfriamiento Z1
```

---

# Repeticiones

Por distancia:

```text
4x1km @4:10-4:25 rec 2min
```

También:

```text
4 x 1 km @4:10-4:25 rec 2 min
```

---

Por tiempo:

```text
6x2min @4:20-4:40 rec 1min
```

---

# Recuperaciones con objetivo

Zona cardíaca:

```text
6x2min @4:20-4:40 rec 1min Z1
```

FC por rango:

```text
6x2min @4:20-4:40 rec 1min FC 120-135
```

Ritmo:

```text
6x2min @4:20-4:40 rec 1min @6:00-6:30
```

---

# Pulsación de botón Lap

## Paso individual

```text
hasta lap calentamiento al inicio de la cuesta
```

Genera:

```text
warmup
└─ hasta pulsar Lap
```

---

## Dentro de repeticiones

```text
5x3min @4:20-4:40 rec 2:30 lap
```

Genera:

```text
repeat x5
├─ run 3:00
├─ recovery 2:30
└─ run hasta pulsar Lap
```

Ideal para:

- Cuestas
- Trail running
- Segmentos con distancia variable
- Regreso al inicio de una cuesta

---

# Ejemplos completos

## Rodaje Z2

```text
Fecha: 2026-07-04
Nombre: Sáb04-Jul - Easy Z2

Sesión:
45 min fácil Z2
```

---

## Series 4x1km

```text
Fecha: 2026-07-01
Nombre: Mié01-Jul - 4x1km

Sesión:
15 min calentamiento Z1
4 x 1 km @4:10-4:25 rec 2 min
10 min enfriamiento Z1
```

---

## Tempo

```text
Fecha: 2026-07-05
Nombre: Dom05-Jul - Tempo

Sesión:
10 min suaves
5 km @4:30
10 min suaves
```

---

## Largo

```text
Fecha: 2026-07-06
Nombre: Dom06-Jul - Largo

Sesión:
18 km @5:20-5:50
```

---

## Cuestas

```text
Fecha: 2026-07-09
Nombre: Jue09-Jul - Cuestas

Sesión:
hasta lap calentamiento al inicio de la cuesta
5x3min @4:20-4:40 rec 2:30 lap
10 min enfriamiento Z1
```

---

# Flujo recomendado

1. Crear o actualizar `input_sesion.txt`

2. Generar JSON

```bash
python generate_plan.py
```

3. Revisar preview

```bash
python sync_week.py --preview
```

4. Sincronizar con Garmin

```bash
python sync_week.py
```

5. Verificar calendario en Garmin Connect

---

# Características implementadas

- Creación automática de workouts
- Agendamiento automático
- Prevención de duplicados
- Modo preview
- Pasos por tiempo
- Pasos por distancia
- Objetivos de ritmo
- Objetivos de frecuencia cardíaca
- Objetivos por zonas cardíacas Garmin
- Repeticiones reales Garmin
- Pasos hasta pulsar Lap
- Parser de lenguaje natural
- Múltiples entrenamientos en un archivo

---

# Futuras mejoras

- Ciclismo / MTB
- Soporte multi-deporte
- Comando único generate + sync
- Mejor interpretación de lenguaje natural
- Descripciones personalizadas por paso
- Exportación de planes completos
- Integración directa con ChatGPT