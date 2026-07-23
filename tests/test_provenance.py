import pytest

from jcc.provenance import (
    DataStatus,
    DimensionSource,
    ReleaseGateError,
    require_verified_dimensions,
)


def test_nominal_unverified_dimensions_are_blocked_from_certification_release() -> None:
    source = DimensionSource(
        status=DataStatus.NOMINAL_UNVERIFIED,
        document="approved design specification",
        edition="revision 1",
    )
    with pytest.raises(ReleaseGateError, match="licensed standards data"):
        require_verified_dimensions(source)


def test_verified_dimensions_pass_release_guard() -> None:
    source = DimensionSource(
        status=DataStatus.LICENSED_VERIFIED,
        document="controlled standards register",
        edition="approved entry",
    )
    require_verified_dimensions(source)
