from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VariantId(StrEnum):
    CONTAINER_20_STD = "20std"
    CONTAINER_40_STD = "40std"
    CONTAINER_40_HC = "40hc"


@dataclass(frozen=True, slots=True)
class VariantSpec:
    variant_id: VariantId
    nominal_name: str
    external_length_mm: int
    external_width_mm: int
    external_height_mm: int
    maximum_gross_mass_kg: int = 30_480
    bundle_count: int = 4


VARIANTS: dict[VariantId, VariantSpec] = {
    VariantId.CONTAINER_20_STD: VariantSpec(
        VariantId.CONTAINER_20_STD, "20 ft standard", 6058, 2438, 2591
    ),
    VariantId.CONTAINER_40_STD: VariantSpec(
        VariantId.CONTAINER_40_STD, "40 ft standard", 12192, 2438, 2591
    ),
    VariantId.CONTAINER_40_HC: VariantSpec(
        VariantId.CONTAINER_40_HC, "40 ft high cube", 12192, 2438, 2896
    ),
}


def get_variant(variant_id: VariantId | str) -> VariantSpec:
    return VARIANTS[VariantId(variant_id)]
