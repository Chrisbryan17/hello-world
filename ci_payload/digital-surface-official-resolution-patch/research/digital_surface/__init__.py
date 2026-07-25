"""Causal digital-surface relative-value research engine."""

from . import data as _data
from .official_resolution import install as _install_official_resolution

_install_official_resolution(_data)

from .types import AtomicFill, Contract, FoldResult, PairCandidate, SurfacePoint

__all__ = ["AtomicFill", "Contract", "FoldResult", "PairCandidate", "SurfacePoint"]
__version__ = "0.1.0"
