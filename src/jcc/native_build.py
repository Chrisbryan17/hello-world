from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .freecad_adapter import build_scaffold_document
from .kinematics import MechanismParameters, sample_fold_cycle
from .variants import VARIANTS


DEFAULT_MECHANISM = MechanismParameters(180.0, 160.0, 12.0, 610.0)


@dataclass(frozen=True, slots=True)
class NativeBuildJob:
    variant_id: str
    progress: float
    filename: str


def native_build_jobs(samples: int = 3) -> tuple[NativeBuildJob, ...]:
    jobs: list[NativeBuildJob] = []
    for spec in VARIANTS.values():
        for index, state in enumerate(
            sample_fold_cycle(spec, DEFAULT_MECHANISM, samples=samples)
        ):
            jobs.append(
                NativeBuildJob(
                    variant_id=str(spec.variant_id),
                    progress=state.progress,
                    filename=(
                        f"{spec.variant_id}_{index:03d}_{state.progress:.3f}.FCStd"
                    ),
                )
            )
    return tuple(jobs)


def build_native_family(output_dir: str | Path, samples: int = 3) -> tuple[Path, ...]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for spec in VARIANTS.values():
        states = sample_fold_cycle(spec, DEFAULT_MECHANISM, samples=samples)
        for index, state in enumerate(states):
            filename = f"{spec.variant_id}_{index:03d}_{state.progress:.3f}.FCStd"
            paths.append(
                build_scaffold_document(
                    spec,
                    DEFAULT_MECHANISM,
                    state,
                    output / filename,
                )
            )
    return tuple(paths)
