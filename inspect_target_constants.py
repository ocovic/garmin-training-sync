import garminconnect.workout as workout

print("TargetType values:")
for name in dir(workout.TargetType):
    if name.isupper():
        print(name, getattr(workout.TargetType, name))