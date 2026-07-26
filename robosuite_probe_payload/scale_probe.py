#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from pathlib import Path

from expert_demos.dataset import validate_dataset
from expert_demos.generate import GenerationConfig, generate_demonstrations
from expert_demos.replay import replay_demo
from expert_demos.robosuite_adapter import RobosuiteLiftAdapter

OUTPUT = Path("robosuite-expert-demo-generator/artifacts/real-physics/probe-25-demos.hdf5")
TARGET = 25
SEED = 1000

started = time.perf_counter()
factory = lambda seed: RobosuiteLiftAdapter(seed=seed, renderer=False)
generation = generate_demonstrations(
    factory,
    GenerationConfig(
        num_demos=TARGET,
        max_attempts=100,
        output=OUTPUT,
        seed=SEED,
        overwrite=True,
    ),
)
elapsed = time.perf_counter() - started
structure = validate_dataset(OUTPUT)
replayed = {}
for demo in ("demo_1", "demo_13", "demo_25"):
    result = replay_demo(OUTPUT, demo=demo, render=False)
    replayed[demo] = {
        "valid": result.valid,
        "steps": result.steps,
        "max_state_error": result.max_state_error,
        "final_success": result.final_success,
    }

report = {
    "target": TARGET,
    "generation": {
        "accepted": generation.accepted,
        "attempts": generation.attempts,
        "rejected": generation.rejected,
        "rejection_reasons": generation.rejection_reasons,
        "elapsed_seconds": elapsed,
        "demos_per_second": TARGET / elapsed,
    },
    "structure": {
        "valid": structure.valid,
        "demos": structure.num_demos,
        "transitions": structure.num_transitions,
        "errors": list(structure.errors),
    },
    "replays": replayed,
}
print(json.dumps(report, indent=2))
Path("robosuite-expert-demo-generator/artifacts/real-physics/scale-report.json").write_text(
    json.dumps(report, indent=2) + "\n"
)
valid = (
    generation.accepted == TARGET
    and structure.valid
    and structure.num_demos == TARGET
    and all(item["valid"] for item in replayed.values())
)
raise SystemExit(0 if valid else 1)
