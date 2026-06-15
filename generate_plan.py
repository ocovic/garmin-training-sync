import json
import re


INPUT_FILE = "input_sesion.txt"
OUTPUT_FILE = "plan_semana.json"


def normalize(text: str) -> str:
    return (
        text.strip()
        .lower()
        .replace(",", ".")
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )


def parse_duration(text: str) -> int:
    text = normalize(text)

    match = re.match(r"(\d+)\s*(min|mins|minutos?)", text)
    if match:
        return int(match.group(1)) * 60

    match = re.match(r"(\d+)\s*(s|seg|segs|segundos?)", text)
    if match:
        return int(match.group(1))

    raise ValueError(f"No pude interpretar duración: {text}")


def parse_distance_meters(text: str) -> int:
    text = normalize(text)

    match = re.match(r"(\d+(?:\.\d+)?)\s*(km|kms|kilometros?)", text)
    if match:
        return int(float(match.group(1)) * 1000)

    match = re.match(r"(\d+)\s*(m|mts|metros?)", text)
    if match:
        return int(match.group(1))

    raise ValueError(f"No pude interpretar distancia: {text}")


def target_pace(min_pace: str, max_pace: str | None = None) -> dict:
    return {
        "type": "pace",
        "min": min_pace,
        "max": max_pace or min_pace,
    }


def target_hr_zone(zone: int) -> dict:
    return {
        "type": "hr_zone",
        "zone": zone,
    }


def target_hr_range(min_hr: int, max_hr: int) -> dict:
    return {
        "type": "heart_rate",
        "min": min_hr,
        "max": max_hr,
    }


def extract_target(line: str) -> dict | None:
    text = normalize(line)

    pace_range = re.search(r"@(\d+:\d{2})\s*-\s*(\d+:\d{2})", text)
    if pace_range:
        return target_pace(pace_range.group(1), pace_range.group(2))

    pace_single = re.search(r"@(\d+:\d{2})", text)
    if pace_single:
        return target_pace(pace_single.group(1))

    zone_match = re.search(r"\bz\s*(\d)\b", text)
    if zone_match:
        return target_hr_zone(int(zone_match.group(1)))

    hr_match = re.search(r"\bfc\s*(\d+)\s*-\s*(\d+)", text)
    if hr_match:
        return target_hr_range(int(hr_match.group(1)), int(hr_match.group(2)))

    return None


def build_basic_step(line: str, step_type: str = "run") -> dict:
    original = line
    text = normalize(line)

    step = {"type": step_type}

    duration_match = re.match(
        r"(\d+)\s*(min|mins|minutos?|s|seg|segs|segundos?)",
        text,
    )

    distance_match = re.match(
        r"(\d+(?:\.\d+)?)\s*(km|kms|kilometros?|m|mts|metros?)",
        text,
    )

    if duration_match:
        step["duration_seconds"] = parse_duration(duration_match.group(0))
    elif distance_match:
        step["distance_meters"] = parse_distance_meters(distance_match.group(0))
    else:
        raise ValueError(f"No pude interpretar paso: {original}")

    target = extract_target(text)
    if target:
        step["target"] = target

    return step


def parse_recovery_target(recovery_extra: str) -> dict | None:
    text = normalize(recovery_extra)

    zone_match = re.search(r"\bz\s*(\d)\b", text)
    if zone_match:
        return target_hr_zone(int(zone_match.group(1)))

    hr_match = re.search(r"\bfc\s*(\d+)\s*-\s*(\d+)", text)
    if hr_match:
        return target_hr_range(int(hr_match.group(1)), int(hr_match.group(2)))

    pace_range = re.search(r"@?(\d+:\d{2})\s*-\s*(\d+:\d{2})", text)
    if pace_range:
        return target_pace(pace_range.group(1), pace_range.group(2))

    pace_single = re.search(r"@?(\d+:\d{2})", text)
    if pace_single:
        return target_pace(pace_single.group(1))

    return None

def parse_lap_flag(text: str) -> bool:
    text = normalize(text)
    return bool(
        re.search(r"(\+?\s*hasta\s+lap|\+?\s*lap\b|\+?\s*pulsar\s+lap)", text)
    )


def parse_repeat(line: str) -> dict | None:
    text = normalize(line)
    add_lap_step = parse_lap_flag(text)

    text = re.sub(r"\+?\s*hasta\s+lap.*$", "", text).strip()
    text = re.sub(r"\+?\s*pulsar\s+lap.*$", "", text).strip()
    text = re.sub(r"\+?\s*lap\b.*$", "", text).strip()

    pattern = (
        r"^(\d+)\s*x\s*"
        r"(\d+(?:\.\d+)?)\s*"
        r"(km|kms|kilometros?|m|mts|metros?|min|mins|minutos?|s|seg|segs|segundos?)"
        r"(?:\s*@\s*(\d+:\d{2})(?:\s*-\s*(\d+:\d{2}))?)?"
        r"\s+rec\s+"
        r"(\d+(?::\d{2})?)\s*"
        r"(min|mins|minutos?|s|seg|segs|segundos?)?"
        r"(.*)$"
    )

    match = re.match(pattern, text)

    if not match:
        return None

    count = int(match.group(1))
    amount = match.group(2)
    unit = match.group(3)
    pace_min = match.group(4)
    pace_max = match.group(5)
    recovery_amount = match.group(6)
    recovery_unit = match.group(7)
    recovery_extra = match.group(8) or ""

    work_line = f"{amount} {unit}"
    work_step = build_basic_step(work_line)

    if pace_min:
        work_step["target"] = target_pace(pace_min, pace_max)

    if ":" in recovery_amount:
        minutes, seconds = map(int, recovery_amount.split(":"))
        recovery_seconds = minutes * 60 + seconds
    else:
        recovery_seconds = parse_duration(
            f"{recovery_amount} {recovery_unit or 'min'}"
        )

    recovery_step = {
        "type": "recovery",
        "duration_seconds": recovery_seconds,
    }

    recovery_target = parse_recovery_target(recovery_extra)
    if recovery_target:
        recovery_step["target"] = recovery_target

    repeat_steps = [
        work_step,
        recovery_step,
    ]

    if add_lap_step:
        repeat_steps.append(
            {
                "type": "run",
                "until_lap": True,
                "estimated_duration_seconds": 300,
            }
        )

    return {
        "type": "repeat",
        "count": count,
        "steps": repeat_steps,
    }


def infer_step_type(line: str, index: int, total: int) -> str:
    text = normalize(line)

    if "calentamiento" in text or "warmup" in text:
        return "warmup"

    if "enfriamiento" in text or "cooldown" in text:
        return "cooldown"

    if total == 1:
        return "run"

    if index == 0 and any(word in text for word in ["suave", "suaves", "facil", "faciles", "easy"]):
        return "warmup"

    if index == total - 1 and any(word in text for word in ["suave", "suaves", "facil", "faciles", "easy"]):
        return "cooldown"

    return "run"


def parse_until_lap_step(line: str, step_type: str = "run") -> dict | None:
    text = normalize(line)

    if not (
        text.startswith("hasta lap")
        or text.startswith("lap")
        or text.startswith("pulsar lap")
    ):
        return None

    if "calentamiento" in text or "warmup" in text:
        step_type = "warmup"
    elif "enfriamiento" in text or "cooldown" in text:
        step_type = "cooldown"

    target = extract_target(text)

    step = {
        "type": step_type,
        "until_lap": True,
        "estimated_duration_seconds": 300,
    }

    if target:
        step["target"] = target

    return step


def parse_session_lines(lines: list[str]) -> list[dict]:
    steps = []
    clean_lines = [line.strip() for line in lines if line.strip()]

    for index, line in enumerate(clean_lines):
        lap_step = parse_until_lap_step(line)

        if lap_step:
            steps.append(lap_step)
            continue

        repeat = parse_repeat(line)

        if repeat:
            steps.append(repeat)
            continue

        step_type = infer_step_type(line, index, len(clean_lines))
        steps.append(build_basic_step(line, step_type=step_type))

    return steps


def parse_block(block: str) -> dict:
    lines = [line.rstrip() for line in block.splitlines() if line.strip()]

    date = None
    name = None
    session_lines = []
    in_session = False

    for line in lines:
        normalized = normalize(line)

        if normalized.startswith("fecha:"):
            date = line.split(":", 1)[1].strip()

        elif normalized.startswith("nombre:"):
            name = line.split(":", 1)[1].strip()

        elif normalized.startswith("sesion:"):
            in_session = True

        elif in_session:
            session_lines.append(line.strip())

    if not date:
        raise ValueError("Falta Fecha en un bloque")

    if not name:
        raise ValueError("Falta Nombre en un bloque")

    if not session_lines:
        raise ValueError(f"Falta Sesión en bloque {name}")

    return {
        "date": date,
        "name": name,
        "description": "Generado desde lenguaje natural",
        "steps": parse_session_lines(session_lines),
    }


def parse_input(text: str) -> dict:
    blocks = [block.strip() for block in text.split("---") if block.strip()]
    workouts = [parse_block(block) for block in blocks]

    return {"workouts": workouts}


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as file:
        text = file.read()

    plan = parse_input(text)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(plan, file, indent=2, ensure_ascii=False)

    print(f"OK: generado {OUTPUT_FILE}")
    print(f"Workouts: {len(plan['workouts'])}")

    for workout in plan["workouts"]:
        print(f"- {workout['date']} | {workout['name']}")


if __name__ == "__main__":
    main()