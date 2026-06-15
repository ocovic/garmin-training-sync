import json

with open("workout_debug.json", "r", encoding="utf-8") as file:
    workout = json.load(file)


def walk(obj):
    if isinstance(obj, dict):
        if "targetType" in obj:
            print("-----")
            print("stepType:", obj.get("stepType"))
            print("targetType:", obj.get("targetType"))
            print("targetValueOne:", obj.get("targetValueOne"))
            print("targetValueTwo:", obj.get("targetValueTwo"))
            print("targetValueUnit:", obj.get("targetValueUnit"))
            print("zoneNumber:", obj.get("zoneNumber"))
            print("secondaryZoneNumber:", obj.get("secondaryZoneNumber"))

        for value in obj.values():
            walk(value)

    elif isinstance(obj, list):
        for item in obj:
            walk(item)


walk(workout)