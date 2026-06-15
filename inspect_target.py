import inspect
from garminconnect.workout import (
    create_interval_step,
    ExecutableStep,
)

print("create_interval_step:")
print(inspect.getsource(create_interval_step))

print()
print("ExecutableStep:")
print(inspect.signature(ExecutableStep))