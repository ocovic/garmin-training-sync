# inspect_workout_deep.py

import inspect
import garminconnect.workout as workout

for name in dir(workout):
    obj = getattr(workout, name)

    if "repeat" in name.lower() or "step" in name.lower():
        print("------")
        print(name)
        print(type(obj))

        try:
            print(inspect.signature(obj))
        except Exception:
            pass