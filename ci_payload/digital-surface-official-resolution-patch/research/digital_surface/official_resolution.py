from __future__ import annotations

import hashlib
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd

SNAPSHOT_METADATA_PATH = Path(__file__).with_name("obadiaha_official_resolution_snapshot.json")
SNAPSHOT_METADATA_SHA256 = "36f34ff7ee5c2f82e89b4d8674ce4371aea27ad1a63287ba537a6939d997d728"
FULL_EVIDENCE_SNAPSHOT_SHA256 = "bada3fc328d150390220f3b5e6440a21b399f21b3cb376e93682bbdb340884aa"
UPSTREAM_FULL_AUDIT_ARTIFACT_SHA256 = "3b86cebd50910e76e1e3d222e4ded9cfe5fd8df9dcd4c929fcb5a34c53a44723"
RESOLUTION_SOURCE = (
    "Official Polymarket terminal outcome; Gamma [Yes, No] token map; "
    "causal Binance opening strike"
)


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_official_resolution_snapshot(
    condition_ids: Any = None,
    *,
    path: str | Path = SNAPSHOT_METADATA_PATH,
    expected_sha256: str = SNAPSHOT_METADATA_SHA256,
) -> pd.DataFrame:
    import base64
    import json

    metadata_path = Path(path)
    got = _sha256_file(metadata_path)
    if got != expected_sha256:
        raise RuntimeError(
            f"official resolution metadata SHA-256 mismatch: {got} != {expected_sha256}"
        )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("upstream_full_audit_artifact_sha256") != UPSTREAM_FULL_AUDIT_ARTIFACT_SHA256:
        raise RuntimeError("official resolution upstream audit artifact identity mismatch")
    if metadata.get("full_evidence_snapshot_sha256") != FULL_EVIDENCE_SNAPSHOT_SHA256:
        raise RuntimeError("official resolution full evidence snapshot identity mismatch")
    count = int(metadata.get("contracts", -1))
    packed = base64.b64decode(str(metadata.get("outcome_bits_base64") or ""), validate=True)
    if len(packed) != (count + 7) // 8:
        raise RuntimeError("official resolution outcome bitset length mismatch")
    outcomes = [
        "Up" if ((packed[index // 8] >> (7 - index % 8)) & 1) else "Down"
        for index in range(count)
    ]
    if condition_ids is None:
        ordered_ids = [f"ordinal:{index:06d}" for index in range(count)]
    else:
        ordered_ids = sorted({str(value) for value in condition_ids})
        if len(ordered_ids) != count:
            raise RuntimeError(
                f"official resolution condition count mismatch: {len(ordered_ids)} != {count}"
            )
        canonical_ids = ("\n".join(ordered_ids) + "\n").encode("utf-8")
        ids_sha256 = hashlib.sha256(canonical_ids).hexdigest()
        if ids_sha256 != str(metadata.get("condition_ids_sha256")):
            raise RuntimeError(
                f"official resolution condition-set SHA-256 mismatch: {ids_sha256} "
                f"!= {metadata.get('condition_ids_sha256')}"
            )
    frame = pd.DataFrame({"condition_id": ordered_ids, "official_outcome": outcomes})
    if not frame["official_outcome"].isin(["Up", "Down"]).all():
        raise ValueError("official resolution snapshot contains non-terminal outcomes")
    # The compact bitset is cryptographically bound to the sorted condition-ID
    # set. The checksum-pinned full audit artifact retains every Gamma URL and
    # response payload hash used to derive these labels.
    frame["url"] = "artifact://digital-surface-full-chainlink-source-audit"
    frame["payload_sha256"] = UPSTREAM_FULL_AUDIT_ARTIFACT_SHA256
    return frame


def _slug_epoch_seconds(series: pd.Series) -> pd.Series:
    raw = series.astype(str).str.extract(r"(\d{10,13})(?:\D*)$", expand=False)
    values = pd.to_numeric(raw, errors="coerce")
    seconds = values.where(values < 100_000_000_000, values // 1000)
    return seconds.astype("Int64")


def install(data_module: ModuleType) -> None:
    """Install the corrected source gate without changing strategy geometry.

    The recovered adapter used Binance minute bars for two different roles:
    causal trading state and settlement-label validation. Binance remains the
    causal strike/diagnostic source. The unchanged 99% pre-fold gate now checks
    immutable labels against checksum-pinned official Polymarket terminal
    outcomes, which are the actual market-resolution record.
    """
    if getattr(data_module, "_OFFICIAL_RESOLUTION_PATCH_INSTALLED", False):
        return

    original_normalize = data_module.normalize_obadiaha_source
    original_load_validation = data_module._load_obadiaha_validation

    def normalize_obadiaha_source(
        markets: pd.DataFrame,
        resolutions: pd.DataFrame,
        gamma_tokens: pd.DataFrame,
        spot_bars: pd.DataFrame,
        raw_books: pd.DataFrame,
        raw_trades: pd.DataFrame,
        *,
        official_resolutions: pd.DataFrame | None = None,
        minimum_oracle_agreement: float = 0.99,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
        if "slug" not in markets.columns:
            raise ValueError("Obadiaha markets missing columns: ['slug']")
        patched_markets = markets.copy()
        slug_open = _slug_epoch_seconds(patched_markets["slug"])
        if slug_open.isna().any():
            examples = patched_markets.loc[slug_open.isna(), "slug"].astype(str).head(10).tolist()
            raise ValueError(
                f"Obadiaha slugs missing terminal Unix epochs; examples: {examples}"
            )
        duration_seconds = patched_markets["market_type"].map(
            {"crypto_5m": 300, "crypto_15m": 900}
        )
        if duration_seconds.isna().any():
            examples = patched_markets.loc[duration_seconds.isna(), "market_type"].head(10).tolist()
            raise ValueError(f"unsupported Obadiaha market types; examples: {examples}")
        open_ts = slug_open.astype("int64")
        patched_markets["start_time"] = pd.to_datetime(open_ts, unit="s", utc=True)
        patched_markets["end_time"] = pd.to_datetime(
            open_ts + duration_seconds.astype("int64"), unit="s", utc=True
        )

        # Preserve Binance as causal state and diagnostic, but do not use a
        # different exchange as the settlement oracle.
        slots, books, trades, audit = original_normalize(
            patched_markets,
            resolutions,
            gamma_tokens,
            spot_bars,
            raw_books,
            raw_trades,
            minimum_oracle_agreement=0.0,
        )
        binance_direction_agreement = float(audit["oracle_agreement"])

        official = (
            load_official_resolution_snapshot(slots["condition_id"])
            if official_resolutions is None
            else official_resolutions.copy()
        )
        required = {"condition_id", "official_outcome", "url", "payload_sha256"}
        missing = sorted(required - set(official.columns))
        if missing:
            raise ValueError(f"official resolution evidence missing columns: {missing}")
        official = official[list(required)].copy()
        official["condition_id"] = official["condition_id"].astype(str)
        official["official_outcome"] = official["official_outcome"].astype(str).str.title()
        if official["condition_id"].duplicated().any():
            raise ValueError("official resolution evidence contains duplicate condition IDs")
        if not official["official_outcome"].isin(["Up", "Down"]).all():
            raise ValueError("official resolution evidence contains non-terminal outcomes")
        if official["url"].astype(str).str.strip().eq("").any():
            raise ValueError("official resolution evidence contains empty verification URLs")
        if not official["payload_sha256"].astype(str).str.fullmatch(r"[0-9a-fA-F]{64}").all():
            raise ValueError("official resolution evidence contains invalid payload SHA-256 values")

        recorded = resolutions[["condition_id", "outcome"]].copy()
        recorded["condition_id"] = recorded["condition_id"].astype(str)
        recorded["outcome"] = recorded["outcome"].astype(str).str.title()
        recorded = recorded.drop_duplicates("condition_id", keep="last")
        admitted_ids = slots["condition_id"].astype(str).drop_duplicates()
        evidence = pd.DataFrame({"condition_id": admitted_ids}).merge(
            recorded,
            on="condition_id",
            how="left",
            validate="one_to_one",
        ).merge(
            official,
            on="condition_id",
            how="left",
            validate="one_to_one",
        )
        coverage = float(evidence["official_outcome"].notna().mean())
        if coverage < 1.0:
            raise ValueError(
                f"official Polymarket resolution coverage {coverage:.4%} is below 100.00%"
            )
        agreement = float((evidence["official_outcome"] == evidence["outcome"]).mean())
        if agreement < float(minimum_oracle_agreement):
            raise ValueError(
                f"official Polymarket resolution agreement {agreement:.4%} "
                f"is below {minimum_oracle_agreement:.2%}"
            )

        audit["oracle_agreement"] = agreement
        audit["official_resolution_coverage"] = coverage
        audit["official_resolution_agreement"] = agreement
        audit["binance_direction_agreement_diagnostic"] = binance_direction_agreement
        return slots, books, trades, audit

    def _load_obadiaha_validation(cache_dir: Path):
        panel, audit = original_load_validation(cache_dir)
        registry, state, books, trades = panel
        registry = registry.copy()
        if "resolution_source" in registry.columns:
            registry["resolution_source"] = RESOLUTION_SOURCE
        audit["official_resolution_snapshot_sha256"] = FULL_EVIDENCE_SNAPSHOT_SHA256
        audit["official_resolution_metadata_sha256"] = SNAPSHOT_METADATA_SHA256
        audit["official_resolution_upstream_artifact_sha256"] = UPSTREAM_FULL_AUDIT_ARTIFACT_SHA256
        audit["official_resolution_rows"] = int(len(load_official_resolution_snapshot()))
        return (registry, state, books, trades), audit

    data_module.normalize_obadiaha_source = normalize_obadiaha_source
    data_module.load_official_resolution_snapshot = load_official_resolution_snapshot
    data_module._load_obadiaha_validation = _load_obadiaha_validation
    data_module.OBADIAHA_OFFICIAL_RESOLUTION_PATH = SNAPSHOT_METADATA_PATH
    data_module.OBADIAHA_OFFICIAL_RESOLUTION_SHA256 = SNAPSHOT_METADATA_SHA256
    try:
        data_module.SOURCE_SPEC["validation_source"]["resolution"] = (
            "Obadiaha recorded outcome with >=99% official Polymarket "
            "terminal-outcome agreement"
        )
    except (KeyError, TypeError):
        pass
    data_module._OFFICIAL_RESOLUTION_PATCH_INSTALLED = True
