from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


def _sha256(name: str, value: str) -> str:
    text = str(value).strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"{name} must be a 64-character SHA-256 hex digest")
    return text


def _normalise(value: str) -> bytes:
    return str(value).strip().lower().encode("utf-8")


def _positions(value: str, *, m_bits: int, k_hashes: int) -> tuple[int, ...]:
    digest = hashlib.sha256(_normalise(value)).digest()
    h1 = int.from_bytes(digest[:8], "big")
    h2 = int.from_bytes(digest[8:16], "big") or 0x9E3779B97F4A7C15
    return tuple((h1 + index * h2) % m_bits for index in range(k_hashes))


def build_diagnostic_bloom(
    market_ids: Iterable[str],
    *,
    source_sha256: str,
    m_bits: int = 262_144,
    k_hashes: int = 7,
) -> dict[str, object]:
    if m_bits <= 0 or m_bits % 8:
        raise ValueError("m_bits must be a positive multiple of 8")
    if k_hashes <= 0:
        raise ValueError("k_hashes must be positive")
    ids = sorted({str(value).strip().lower() for value in market_ids if str(value).strip()})
    bitset = bytearray(m_bits // 8)
    for value in ids:
        for position in _positions(value, m_bits=m_bits, k_hashes=k_hashes):
            bitset[position // 8] |= 1 << (position % 8)
    raw = bytes(bitset)
    return {
        "algorithm": "sha256-double-hash-v1",
        "bitset_base64": base64.b64encode(raw).decode("ascii"),
        "bitset_sha256": hashlib.sha256(raw).hexdigest(),
        "item_count": len(ids),
        "k_hashes": int(k_hashes),
        "m_bits": int(m_bits),
        "source_sha256": _sha256("source_sha256", source_sha256),
        "version": 1,
    }


@dataclass(frozen=True, slots=True)
class DiagnosticBloomFilter:
    bitset: bytes
    m_bits: int
    k_hashes: int
    item_count: int
    source_sha256: str

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "DiagnosticBloomFilter":
        if int(payload.get("version", -1)) != 1:
            raise ValueError("unsupported diagnostic Bloom filter version")
        if payload.get("algorithm") != "sha256-double-hash-v1":
            raise ValueError("unsupported diagnostic Bloom filter algorithm")
        m_bits = int(payload["m_bits"])
        k_hashes = int(payload["k_hashes"])
        item_count = int(payload["item_count"])
        if m_bits <= 0 or m_bits % 8:
            raise ValueError("m_bits must be a positive multiple of 8")
        if k_hashes <= 0 or item_count < 0:
            raise ValueError("invalid Bloom filter dimensions")
        try:
            bitset = base64.b64decode(str(payload["bitset_base64"]), validate=True)
        except Exception as exc:
            raise ValueError("invalid Bloom filter base64") from exc
        if len(bitset) != m_bits // 8:
            raise ValueError("Bloom filter bitset length mismatch")
        expected = _sha256("bitset_sha256", str(payload["bitset_sha256"]))
        got = hashlib.sha256(bitset).hexdigest()
        if got != expected:
            raise ValueError(f"bitset SHA-256 mismatch: {got} != {expected}")
        return cls(
            bitset=bitset,
            m_bits=m_bits,
            k_hashes=k_hashes,
            item_count=item_count,
            source_sha256=_sha256("source_sha256", str(payload["source_sha256"])),
        )

    @classmethod
    def from_path(cls, path: str | Path) -> "DiagnosticBloomFilter":
        return cls.from_payload(json.loads(Path(path).read_text(encoding="utf-8")))

    def __contains__(self, market_id: object) -> bool:
        value = str(market_id)
        return all(
            bool(self.bitset[position // 8] & (1 << (position % 8)))
            for position in _positions(value, m_bits=self.m_bits, k_hashes=self.k_hashes)
        )
