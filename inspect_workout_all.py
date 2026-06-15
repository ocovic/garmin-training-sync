import garminconnect.workout as workout

methods = [m for m in dir(workout) if "step" in m.lower() or "workout" in m.lower()]

for m in methods:
    print(m)