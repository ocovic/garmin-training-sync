from garminconnect import Garmin
import inspect

print("get_scheduled_workouts:")
print(inspect.signature(Garmin.get_scheduled_workouts))
print()

print(inspect.getsource(Garmin.get_scheduled_workouts))