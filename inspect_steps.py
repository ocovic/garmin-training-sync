# inspect_steps.py

import inspect
from garminconnect.workout import (
    create_interval_step,
    create_recovery_step,
    create_warmup_step,
    create_cooldown_step,
)

functions = [
    create_warmup_step,
    create_interval_step,
    create_recovery_step,
    create_cooldown_step,
]

for fn in functions:
    print(fn.__name__)
    print(inspect.signature(fn))
    print()