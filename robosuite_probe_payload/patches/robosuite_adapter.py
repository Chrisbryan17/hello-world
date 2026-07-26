from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np


@dataclass(frozen=True)
class PreparedEpisode:
    observation: Mapping[str, Any]
    model_xml: str
    initial_state: np.ndarray


def prepare_deterministic_episode(env: Any) -> PreparedEpisode:
    """Prepare controller state for deterministic open-loop action playback.

    robosuite's controllers carry goal state that is not part of MuJoCo's
    flattened state vector. Rebuilding the simulation from the episode XML
    before action collection initializes those controller goals exactly as
    they will be initialized during playback. This mirrors robosuite's own
    action-playback test and DataCollectionWrapper.
    """
    env.reset()
    model_xml = str(env.sim.model.get_xml())
    initial_state = np.asarray(env.sim.get_state().flatten(), dtype=np.float64).copy()

    if hasattr(env, "get_ep_meta") and hasattr(env, "set_ep_meta"):
        env.set_ep_meta(env.get_ep_meta())

    env.reset_from_xml_string(model_xml)
    env.sim.reset()
    env.sim.set_state_from_flattened(initial_state)
    env.sim.forward()
    if hasattr(env, "update_state"):
        env.update_state()

    if getattr(env, "viewer_get_obs", False):
        observation = env.viewer._get_observations(force_update=True)
    else:
        observation = env._get_observations(force_update=True)

    return PreparedEpisode(
        observation=observation,
        model_xml=model_xml,
        initial_state=initial_state,
    )


def world_delta_to_base(delta_world: np.ndarray, base_to_world_rotation: np.ndarray) -> np.ndarray:
    """Rotate a translation vector from MuJoCo world coordinates into robot-base coordinates."""
    delta = np.asarray(delta_world, dtype=np.float64).reshape(3)
    rotation = np.asarray(base_to_world_rotation, dtype=np.float64).reshape(3, 3)
    return rotation.T @ delta


def build_action_vector(
    *,
    robot: Any,
    arm: str,
    delta_position: np.ndarray,
    delta_rotation: np.ndarray,
    gripper: float,
    gripper_dof: int,
) -> np.ndarray:
    arm_action = np.concatenate(
        [
            np.asarray(delta_position, dtype=np.float64).reshape(3),
            np.asarray(delta_rotation, dtype=np.float64).reshape(3),
        ]
    )
    action_dict = {
        arm: arm_action,
        f"{arm}_gripper": np.full(int(gripper_dof), float(gripper), dtype=np.float64),
    }
    return np.asarray(robot.create_action_vector(action_dict), dtype=np.float32)


class RobosuiteLiftAdapter:
    env_name = "Lift"

    def __init__(
        self,
        *,
        robot: str = "Panda",
        controller: str | None = "BASIC",
        arm: str = "right",
        seed: int = 0,
        control_freq: int = 20,
        horizon: int = 350,
        renderer: bool = False,
    ) -> None:
        try:
            import robosuite as suite
            from robosuite.controllers import load_composite_controller_config
        except ImportError as exc:
            raise RuntimeError(
                "robosuite is not installed. Install with: "
                "pip install 'robosuite==1.5.2' 'mujoco>=3.3.0,<3.10'"
            ) from exc

        controller_config = load_composite_controller_config(controller=controller, robot=robot)
        creation_config: dict[str, Any] = {
            "env_name": "Lift",
            "robots": [robot],
            "controller_configs": controller_config,
        }
        self.env_info = copy.deepcopy(creation_config)
        self.repository_version = str(suite.__version__)
        self.arm = arm
        self._base_seed = int(seed)
        self._suite = suite
        self.env = suite.make(
            **creation_config,
            has_renderer=bool(renderer),
            has_offscreen_renderer=False,
            use_camera_obs=False,
            use_object_obs=True,
            reward_shaping=True,
            control_freq=control_freq,
            horizon=horizon,
            ignore_done=True,
            hard_reset=False,
            lite_physics=True,
            seed=seed,
        )
        self.robot = self.env.robots[0]
        if arm not in self.robot.arms:
            raise ValueError(f"arm {arm!r} not available; robot arms are {self.robot.arms}")
        self.gripper_dof = int(self.robot.gripper[arm].dof)
        self._episode_model_xml: str | None = None
        if self.gripper_dof < 1:
            raise ValueError(f"robot {robot!r} arm {arm!r} has no controllable gripper")

    def reset(self, seed: int | None = None) -> Mapping[str, Any]:
        # robosuite 1.5.2 seeds the environment at construction; reset() itself
        # takes no seed argument. The generator constructs one adapter per attempt.
        if seed is not None and int(seed) != self._base_seed:
            raise ValueError(
                f"adapter was constructed with seed {self._base_seed}, but reset requested {seed}; "
                "construct a fresh adapter for deterministic episode seeding"
            )
        prepared = prepare_deterministic_episode(self.env)
        self._episode_model_xml = prepared.model_xml
        return prepared.observation

    def step(self, action: np.ndarray):
        return self.env.step(action)

    def eef_position(self, observation: Mapping[str, Any]) -> np.ndarray:
        candidates = (
            f"robot0_{self.arm}_eef_pos",
            "robot0_eef_pos",
            f"{self.arm}_eef_pos",
            "eef_pos",
        )
        for key in candidates:
            if key in observation:
                return np.asarray(observation[key], dtype=np.float64).reshape(3)

        # Direct site_xpos is also in MuJoCo world coordinates, matching cube_pos.
        try:
            return np.asarray(self.env.sim.data.site_xpos[self.robot.eef_site_id[self.arm]], dtype=np.float64).reshape(3)
        except Exception as exc:
            keys = ", ".join(sorted(observation.keys()))
            raise KeyError(f"cannot resolve world-frame end-effector position; observation keys: {keys}") from exc

    def cube_position(self, observation: Mapping[str, Any]) -> np.ndarray:
        if "cube_pos" not in observation:
            raise KeyError(f"Lift observation is missing cube_pos; keys={sorted(observation.keys())}")
        return np.asarray(observation["cube_pos"], dtype=np.float64).reshape(3)

    def action(self, delta_position: np.ndarray, gripper: float) -> np.ndarray:
        # Planner errors are world-frame because both eef_pos and cube_pos are world-frame.
        # Panda's default OSC_POSE controller consumes base-frame translation deltas.
        delta_base = world_delta_to_base(delta_position, self.robot.base_ori)
        return build_action_vector(
            robot=self.robot,
            arm=self.arm,
            delta_position=delta_base,
            delta_rotation=np.zeros(3),
            gripper=gripper,
            gripper_dof=self.gripper_dof,
        )

    def state(self) -> np.ndarray:
        return np.asarray(self.env.sim.get_state().flatten(), dtype=np.float64)

    def model_xml(self) -> str:
        if self._episode_model_xml is not None:
            return self._episode_model_xml
        return str(self.env.sim.model.get_xml())

    def success(self) -> bool:
        return bool(self.env._check_success())

    def close(self) -> None:
        self.env.close()

    def env_info_json(self) -> str:
        return json.dumps(self.env_info)
