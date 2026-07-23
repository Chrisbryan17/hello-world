from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def load_probe_module():
    path = Path(__file__).parents[1] / "tools" / "btc_minute4_recovery_probe.py"
    spec = spec_from_file_location("btc_minute4_recovery_probe", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_btc_source_files_prefers_direct_parquet_pair():
    probe = load_probe_module()
    resolved = probe.resolve_btc_source_files(
        [
            "README.md",
            "btc_markets.parquet",
            "btc_ticks.parquet",
            "eth_markets.parquet",
        ]
    )
    assert resolved == {
        "kind": "direct_parquet",
        "markets": "btc_markets.parquet",
        "ticks": "btc_ticks.parquet",
    }


def test_resolve_btc_source_files_retains_zip_fallback():
    probe = load_probe_module()
    resolved = probe.resolve_btc_source_files(
        ["README.md", "archives/polymarket-5m-btc.zip"]
    )
    assert resolved == {
        "kind": "zip",
        "archive": "archives/polymarket-5m-btc.zip",
    }
