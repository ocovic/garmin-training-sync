# Garmin Training Sync - Contexto para ChatGPT

## Objetivo

Estoy desarrollando un sistema que convierte planes de entrenamiento escritos en lenguaje natural a entrenamientos estructurados de Garmin Connect.

Cuando solicite sesiones o planes de entrenamiento, necesito que las entregues en un formato compatible con mi parser.

No necesito explicaciones técnicas del entrenamiento dentro del bloque de sesiones. Solamente necesito el plan listo para copiar y pegar en `input_sesion.txt`.

---

# Formato requerido

Cada entrenamiento debe seguir exactamente esta estructura:

```text
Fecha: YYYY-MM-DD
Nombre: Nombre del entrenamiento

Sesión:
...
```

Si hay varios entrenamientos deben separarse mediante:

```text
---
```

Ejemplo:

```text
Fecha: 2026-07-01
Nombre: Mié01-Jul - Series

Sesión:
15 min calentamiento Z1
4 x 1 km @4:10-4:25 rec 2 min
10 min enfriamiento Z1

---
Fecha: 2026-07-04
Nombre: Sáb04-Jul - Easy Z2

Sesión:
45 min fácil Z2
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

## Distancia

```text
5 km
10 km
18 km
1.6 km
7.5 km
```

## Ritmo objetivo

Rango:

```text
10 km @5:20-5:50
```

Ritmo único:

```text
5 km @4:30
```

## Frecuencia cardíaca por zonas

```text
45 min Z2
30 min Z3
10 min calentamiento Z1
10 min enfriamiento Z1
```

## Frecuencia cardíaca por rango

```text
40 min FC 135-150
```

## Repeticiones por distancia

```text
4x1km @4:10-4:25 rec 2min
```

También puede utilizarse:

```text
4 x 1 km @4:10-4:25 rec 2 min
```

## Repeticiones por tiempo

```text
6x2min @4:20-4:40 rec 1min
```

## Recuperaciones con objetivo

```text
6x2min @4:20-4:40 rec 1min Z1
```

```text
6x2min @4:20-4:40 rec 1min FC 120-135
```

```text
6x2min @4:20-4:40 rec 1min @6:00-6:30
```

## Pulsación de botón Lap

Paso individual:

```text
hasta lap calentamiento al inicio de la cuesta
```

Repeticiones con retorno al inicio:

```text
5x3min @4:20-4:40 rec 2:30 lap
```

---

# Convenciones para ChatGPT

## Nombres

Los nombres deben ser cortos.

Ejemplos:

```text
Mié24-Jun - 4x1km
Sáb27-Jun - Z2
Dom28-Jun - Largo
Jue09-Jul - Cuestas
```

Evitar:

```text
Entrenamiento de repeticiones de 1 kilómetro para desarrollo de umbral
```

---

## Fechas

Siempre incluir la fecha exacta.

Nunca usar:

```text
Miércoles
Sábado
Domingo
Próxima semana
```

Siempre usar:

```text
Fecha: 2026-07-01
```

---

## Ritmos

Siempre usar formato:

```text
4:10
5:30
6:00
```

Nunca:

```text
4.10
4m10s
```

---

## Frecuencia cardíaca

Para zonas:

```text
Z1
Z2
Z3
Z4
Z5
```

Para rango:

```text
FC 135-150
```

---

# Consideraciones personales del atleta

Datos actuales:

- Edad: 33 años
- Peso: ~62 kg
- Garmin Forerunner 255
- VO2Max: ~50-53
- Umbral actual Garmin: 4:31/km
- FC Umbral: 186 ppm
- Entrenamiento principal: Running y Trail Running
- MTB recreativo ocasional

Disponibilidad habitual:

- Miércoles: calidad
- Sábado: rodaje fácil
- Domingo: tirada larga

Objetivos habituales:

- Trail Running
- 10K
- Media maratón
- Mejora de umbral y resistencia

---

# Respuesta esperada

Cuando solicite una sesión o una semana de entrenamiento, devolver únicamente el bloque compatible con el parser.

Ejemplo:

```text
Fecha: 2026-07-01
Nombre: Mié01-Jul - Umbral

Sesión:
15 min calentamiento Z1
4 x 1 km @4:10-4:25 rec 2 min
10 min enfriamiento Z1

---
Fecha: 2026-07-04
Nombre: Sáb04-Jul - Easy

Sesión:
45 min fácil Z2

---
Fecha: 2026-07-05
Nombre: Dom05-Jul - Largo

Sesión:
18 km @5:20-5:50
```

No agregar explicaciones dentro del bloque.

Las explicaciones pueden ir antes o después del bloque, pero el bloque debe poder copiarse directamente a `input_sesion.txt` sin modificaciones.

---

# Estado actual del proyecto

Características soportadas:

- Running
- Pasos por tiempo
- Pasos por distancia
- Ritmo objetivo
- Frecuencia cardíaca por rango
- Frecuencia cardíaca por zonas
- Repeticiones Garmin reales
- Pulsación de botón Lap
- Múltiples entrenamientos por archivo
- Sincronización automática con Garmin Connect

Características pendientes:

- MTB / Cycling
- Multisport
- Generate + Sync en un único comando