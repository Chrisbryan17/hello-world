#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import robosuite

DATASET = Path("robosuite-expert-demo-generator/artifacts/real-physics/probe-demo.hdf5")

with h5py.File(DATASET, "r") as file:
    data = file["data"]
    env_info = json.loads(data.attrs["env_info"])
    group = data["demo_1"]
    model_xml = str(group.attrs["model_file"])
    states = np.asarray(group["states"], dtype=np.float64)
    next_states = np.asarray(group["next_states"], dtype=np.float64)
    actions = np.asarray(group["actions"], dtype=np.float32)

continuity = np.linalg.norm(next_states[:-1] - states[1:], axis=1)
print("DIAGNOSTIC dataset_shapes", states.shape, next_states.shape, actions.shape)
print("DIAGNOSTIC continuity_min_mean_max", float(continuity.min()), float(continuity.mean()), float(continuity.max()))

env = robosuite.make(
    **env_info,
    has_renderer=False,
    has_offscreen_renderer=False,
    ignore_done=True,
    use_camera_obs=False,
    reward_shaping=True,
    control_freq=20,
    lite_physics=True,
)
try:
    env.reset()
    xml = env.edit_model_xml(model_xml)
    env.reset_from_xml_string(xml)
    env.sim.reset()
    env.sim.set_state_from_flattened(states[0])
    env.sim.forward()

    rows = []
    for index, action in enumerate(actions):
        before = np.asarray(env.sim.get_state().flatten(), dtype=np.float64)
        pre_delta = before - states[index]
        pre_error = float(np.linalg.norm(pre_delta))
        env.step(action)
        after = np.asarray(env.sim.get_state().flatten(), dtype=np.float64)
        post_delta = after - next_states[index]
        post_error = float(np.linalg.norm(post_delta))
        rows.append((index, pre_error, post_error, float(before[0]), float(states[index, 0]), float(after[0]), float(next_states[index, 0])))

        if index < 12 or index >= len(actions) - 5 or pre_error > 1e-5 or post_error > 1e-5:
            top_pre = np.argsort(np.abs(pre_delta))[::-1][:8]
            top_post = np.argsort(np.abs(post_delta))[::-1][:8]
            print("DIAGNOSTIC step", index, "pre_error", pre_error, "post_error", post_error,
                  "time", before[0], states[index, 0], after[0], next_states[index, 0])
            print("DIAGNOSTIC top_pre", [(int(i), float(pre_delta[i])) for i in top_pre if abs(pre_delta[i]) > 1e-12])
            print("DIAGNOSTIC top_post", [(int(i), float(post_delta[i])) for i in top_post if abs(post_delta[i]) > 1e-12])

    print("DIAGNOSTIC max_pre", max(row[1] for row in rows), "at", max(rows, key=lambda row: row[1])[0])
    print("DIAGNOSTIC max_post", max(row[2] for row in rows), "at", max(rows, key=lambda row: row[2])[0])
    print("DIAGNOSTIC final_success", bool(env._check_success()))
finally:
    env.close()
