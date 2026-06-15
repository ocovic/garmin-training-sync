from garminconnect.workout import (
    create_warmup_step,
    create_cooldown_step
)

import inspect

print("Warmup:")
print(inspect.signature(create_warmup_step))

print()

print("Cooldown:")
print(inspect.signature(create_cooldown_step))