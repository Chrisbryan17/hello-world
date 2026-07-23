from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DataStatus(StrEnum):
    NOMINAL_UNVERIFIED = "nominal_unverified"
    LICENSED_VERIFIED = "licensed_verified"


@dataclass(frozen=True, slots=True)
class DimensionSource:
    status: DataStatus
    document: str
    edition: str


class ReleaseGateError(RuntimeError):
    pass


def require_verified_dimensions(source: DimensionSource) -> None:
    if source.status is not DataStatus.LICENSED_VERIFIED:
        raise ReleaseGateError(
            "Certification release requires licensed standards data and an approved controlled entry."
        )
