#!/usr/bin/env python3
"""Generate lossless chapter narration with Kokoro v1.0."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "kokoro_narration" / "scenes.json"
MODEL_PATH = ROOT / "kokoro-v1.0.onnx"
VOICES_PATH = ROOT / "voices-v1.0.bin"
OUTPUT_DIR = ROOT / "kokoro-output"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def split_text(text: str, max_chars: int = 430) -> list[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if current:
            chunks.append(" ".join(current).strip())
            current = []
            current_len = 0

    for sentence in sentences:
        if len(sentence) <= max_chars:
            candidate_len = current_len + (1 if current else 0) + len(sentence)
            if current and candidate_len > max_chars:
                flush()
            current.append(sentence)
            current_len += (1 if current_len else 0) + len(sentence)
            continue

        flush()
        words = sentence.split()
        piece: list[str] = []
        piece_len = 0
        for word in words:
            candidate_len = piece_len + (1 if piece else 0) + len(word)
            if piece and candidate_len > max_chars:
                chunks.append(" ".join(piece))
                piece = []
                piece_len = 0
            piece.append(word)
            piece_len += (1 if piece_len else 0) + len(word)
        if piece:
            chunks.append(" ".join(piece))

    flush()
    return chunks


def as_mono_float32(samples: object) -> np.ndarray:
    audio = np.asarray(samples, dtype=np.float32).squeeze()
    if audio.ndim != 1:
        audio = audio.reshape(-1)
    if not np.all(np.isfinite(audio)):
        raise ValueError("Kokoro returned non-finite audio samples")
    return audio


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Loading Kokoro model: {MODEL_PATH}", flush=True)
    started = time.perf_counter()
    kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))
    print(f"Model loaded in {time.perf_counter() - started:.2f}s", flush=True)

    available_voices = set(kokoro.get_voices())
    voice = config["voice"]
    language = config["language"]
    speed = float(config["speed"])
    if voice not in available_voices:
        raise ValueError(f"Voice {voice!r} unavailable; got {sorted(available_voices)}")

    manifest: dict[str, object] = {
        "engine": "kokoro-onnx",
        "source_cli": "https://github.com/nazdridoy/kokoro-tts",
        "voice": voice,
        "language": language,
        "speed": speed,
        "model_sha256": sha256(MODEL_PATH),
        "voices_sha256": sha256(VOICES_PATH),
        "scenes": [],
    }

    for index, scene in enumerate(config["scenes"], start=1):
        scene_id = scene["id"]
        text = scene["text"]
        chunks = split_text(text)
        print(f"[{index}/{len(config['scenes'])}] {scene_id}: {len(chunks)} chunk(s)", flush=True)

        parts: list[np.ndarray] = []
        sample_rate: int | None = None
        scene_started = time.perf_counter()
        for chunk_index, chunk in enumerate(chunks, start=1):
            chunk_started = time.perf_counter()
            samples, sr = kokoro.create(chunk, voice=voice, speed=speed, lang=language)
            audio = as_mono_float32(samples)
            if sample_rate is None:
                sample_rate = int(sr)
            elif sample_rate != int(sr):
                raise ValueError(f"Sample-rate changed inside {scene_id}: {sample_rate} -> {sr}")
            parts.append(audio)
            if chunk_index < len(chunks):
                parts.append(np.zeros(round(sample_rate * 0.12), dtype=np.float32))
            print(
                f"  chunk {chunk_index}/{len(chunks)}: {len(chunk)} chars, "
                f"{len(audio) / sample_rate:.2f}s audio in {time.perf_counter() - chunk_started:.2f}s",
                flush=True,
            )

        if not parts or sample_rate is None:
            raise RuntimeError(f"No audio generated for {scene_id}")

        audio = np.concatenate(parts)
        peak_before = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak_before > 0.97:
            audio = audio * (0.97 / peak_before)
        peak_after = float(np.max(np.abs(audio))) if audio.size else 0.0

        output_path = OUTPUT_DIR / f"{index - 1:02d}-{scene_id}.wav"
        sf.write(output_path, audio, sample_rate, subtype="PCM_24")
        duration = len(audio) / sample_rate
        elapsed = time.perf_counter() - scene_started
        digest = sha256(output_path)
        print(f"  wrote {output_path.name}: {duration:.3f}s in {elapsed:.2f}s", flush=True)

        manifest["scenes"].append(
            {
                "index": index - 1,
                "id": scene_id,
                "text": text,
                "chunks": chunks,
                "sample_rate": sample_rate,
                "samples": int(len(audio)),
                "duration_seconds": duration,
                "target_seconds": float(scene["target_seconds"]),
                "duration_pad": float(scene["duration_pad"]),
                "peak_before": peak_before,
                "peak_after": peak_after,
                "sha256": digest,
                "file": output_path.name,
            }
        )

    manifest_path = OUTPUT_DIR / "kokoro-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest: {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
