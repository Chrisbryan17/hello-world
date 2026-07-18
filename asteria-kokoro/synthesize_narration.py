from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro


def srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize Asteria narration with Kokoro ONNX")
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--voices", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    payload = json.loads(args.script.read_text(encoding="utf-8"))
    voice = payload["voice"]
    speed = float(payload["speed"])
    target_rate = int(payload.get("sample_rate", 24_000))
    kokoro = Kokoro(str(args.model), str(args.voices))

    pre_roll = np.zeros(int(target_rate * 0.45), dtype=np.float32)
    inter_scene = np.zeros(int(target_rate * 0.72), dtype=np.float32)
    post_roll = np.zeros(int(target_rate * 0.70), dtype=np.float32)
    master_parts = [pre_roll]
    timeline = []
    cursor = len(pre_roll) / target_rate
    srt_blocks = []

    for index, scene in enumerate(payload["scenes"], start=1):
        samples, sample_rate = kokoro.create(
            scene["text"], voice=voice, speed=speed, lang="en-us"
        )
        if int(sample_rate) != target_rate:
            raise RuntimeError(f"Unexpected Kokoro sample rate {sample_rate}")
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
        if peak > 0.98:
            samples *= 0.98 / peak

        clip_path = args.out / f"{scene['id']}.wav"
        sf.write(clip_path, samples, target_rate, subtype="PCM_16")
        start = cursor
        end = start + len(samples) / target_rate
        timeline.append({
            "index": index,
            "id": scene["id"],
            "title": scene["title"],
            "text": scene["text"],
            "start_seconds": round(start, 6),
            "end_seconds": round(end, 6),
            "duration_seconds": round(end - start, 6),
            "file": clip_path.name,
        })
        srt_blocks.append("\n".join([
            str(index),
            f"{srt_timestamp(start)} --> {srt_timestamp(end)}",
            scene["title"],
            "",
        ]))
        master_parts.extend([samples, inter_scene])
        cursor = end + len(inter_scene) / target_rate

    master_parts.append(post_roll)
    master = np.concatenate(master_parts)
    sf.write(args.out / "asteria_kokoro_narration.wav", master, target_rate, subtype="PCM_16")
    manifest = {
        "engine": "Kokoro ONNX",
        "repository": "https://github.com/thewh1teagle/kokoro-onnx",
        "model": args.model.name,
        "voices": args.voices.name,
        "voice": voice,
        "speed": speed,
        "sample_rate": target_rate,
        "total_duration_seconds": round(len(master) / target_rate, 6),
        "scenes": timeline,
    }
    (args.out / "narration_timeline.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (args.out / "scene_titles.srt").write_text("\n".join(srt_blocks), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
