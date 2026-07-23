from jcc.variants import VARIANTS, VariantId, get_variant


def test_catalogue_contains_exactly_three_required_variants() -> None:
    assert set(VARIANTS) == {
        VariantId.CONTAINER_20_STD,
        VariantId.CONTAINER_40_STD,
        VariantId.CONTAINER_40_HC,
    }


def test_all_variants_share_approved_width_and_rating() -> None:
    for spec in VARIANTS.values():
        assert spec.external_width_mm == 2438
        assert spec.maximum_gross_mass_kg == 30_480
        assert spec.bundle_count == 4


def test_get_variant_accepts_enum_or_string() -> None:
    assert get_variant(VariantId.CONTAINER_20_STD) is VARIANTS[VariantId.CONTAINER_20_STD]
    assert get_variant("40hc") is VARIANTS[VariantId.CONTAINER_40_HC]
