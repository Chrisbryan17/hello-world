from __future__ import annotations

import hashlib
import json
import math
import pathlib
from datetime import datetime, timezone

import mido
import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

ROOT = pathlib.Path("genesis-directors-audio")
AUDIO = ROOT / "narration"
AUDIO.mkdir(parents=True, exist_ok=True)

SCENES = [
    {
        "id": "00_prologue",
        "heading": "BEFORE THE FIRST DAWN",
        "script": "Before the first dawn. Before the first breath. Before time could be measured by sun or moon, there was darkness over the deep. The earth was unformed and empty. Yet the silence was not abandoned. The Spirit of God moved over the waters... and creation waited for a word.",
    },
    {
        "id": "01_light",
        "heading": "DAY ONE — LIGHT",
        "script": "Then God spoke: Let there be light. And light broke into the darkness. Day was divided from night; brightness from shadow. The first evening passed, and the first morning came. The universe had received its first rhythm... and God saw that the light was good.",
    },
    {
        "id": "02_sky",
        "heading": "DAY TWO — THE HEAVENS",
        "script": "God stretched an expanse between the waters. Above, the heavens opened like a vast blue sanctuary. Below, the seas gathered beneath it. Mist rose. Clouds formed. Wind crossed the face of the deep. The world gained height, distance... and a horizon.",
    },
    {
        "id": "03_land",
        "heading": "DAY THREE — LAND AND LIFE",
        "script": "The waters drew back, and dry ground appeared. Mountains lifted from the sea. Valleys opened. Rivers found their paths. Then the bare earth awakened. Grass unfolded. Trees reached upward. Seed and fruit carried life within themselves... ready to fill the world again and again.",
    },
    {
        "id": "04_lights",
        "heading": "DAY FOUR — SUN, MOON, AND STARS",
        "script": "God appointed lights in the heavens: the sun to govern the day, the moon to watch over the night, and stars beyond counting. They marked seasons, days, and years. What had been formless now moved with order. What had been dark... now shone with signs of purpose.",
    },
    {
        "id": "05_sea_sky",
        "heading": "DAY FIVE — SEA AND SKY",
        "script": "The waters surged with living creatures. Great beasts moved through the deep. Silver shoals turned as one beneath the waves. Above them, wings filled the open sky: eagles, doves, and birds of every kind. God blessed them to multiply... until sea and heaven overflowed with life.",
    },
    {
        "id": "06_animals",
        "heading": "DAY SIX — CREATURES OF THE EARTH",
        "script": "Across the land came creatures strong and small: cattle in the fields, lions in the grass, deer among the trees, and every animal that moved close to the earth. Each entered the world according to its kind... taking its place inside a creation rich with balance and wonder.",
    },
    {
        "id": "07_humanity",
        "heading": "DAY SIX — HUMANITY",
        "script": "Then God said: Let us make humanity in our image. From the dust came a living form, and into it came breath. Male and female, humanity was created with dignity, imagination, and responsibility: to cultivate the earth, to guard its life, and to reflect the Creator within creation. God looked upon everything that had been made... and it was very good.",
    },
    {
        "id": "08_rest",
        "heading": "DAY SEVEN — REST",
        "script": "The heavens and the earth were complete. On the seventh day, God rested. Not from weakness... but in completion. The day was blessed and set apart. Creation did not end in noise or conquest, but in peace: a sacred pause in which the work could be seen, received... and called good.",
    },
    {
        "id": "09_epilogue",
        "heading": "GENESIS",
        "script": "This is the beginning: light from darkness, order from chaos, life from the earth, and humanity entrusted with a living world. Genesis opens with a creation spoken into beauty... and with an invitation to remember that existence itself is a gift.",
    },
]

VOICE_CANDIDATES = ["bm_george", "bm_daniel", "bm_lewis", "bm_fable", "am_michael"]
VOICE_SPEED = 0.89
LANGUAGE = "en-gb"
SAMPLE_RATE = 48000
BPM = 54
TPB = 480


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def select_voice(kokoro: Kokoro) -> str:
    failures = []
    for voice in VOICE_CANDIDATES:
        try:
            samples, _ = kokoro.create(
                "In the beginning, God created the heavens and the earth.",
                voice=voice,
                speed=VOICE_SPEED,
                lang=LANGUAGE,
            )
            if np.asarray(samples).size:
                return voice
        except Exception as exc:
            failures.append(f"{voice}: {type(exc).__name__}: {exc}")
    raise RuntimeError("No narration voice succeeded: " + " | ".join(failures))


def sec_to_tick(seconds: float) -> int:
    return int(round(seconds * BPM / 60.0 * TPB))


def build_track(name: str, program: int, channel: int, events: list[tuple[float, str, int, int]]) -> mido.MidiTrack:
    track = mido.MidiTrack()
    track.append(mido.MetaMessage("track_name", name=name, time=0))
    track.append(mido.Message("program_change", program=program, channel=channel, time=0))
    track.append(mido.Message("control_change", control=7, value=104, channel=channel, time=0))
    timeline = []
    for seconds, kind, note, velocity in events:
        timeline.append((sec_to_tick(seconds), kind, note, velocity))
    timeline.sort(key=lambda x: (x[0], 0 if x[1] == "off" else 1))
    last = 0
    for tick, kind, note, velocity in timeline:
        delta = max(0, tick - last)
        last = tick
        track.append(mido.Message("note_on" if kind == "on" else "note_off", note=note, velocity=velocity, channel=channel, time=delta))
    track.append(mido.MetaMessage("end_of_track", time=sec_to_tick(2.0)))
    return track


def add_note(events, start, duration, note, velocity):
    events.append((start, "on", note, velocity))
    events.append((start + duration, "off", note, 0))


def compose_score(scene_records: list[dict]) -> float:
    midi = mido.MidiFile(type=1, ticks_per_beat=TPB)
    tempo = mido.MidiTrack()
    tempo.append(mido.MetaMessage("track_name", name="Tempo", time=0))
    tempo.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(BPM), time=0))
    tempo.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    midi.tracks.append(tempo)

    strings, choir, bass, horn, harp, timpani = ([] for _ in range(6))
    cursor = 0.0
    progressions = [
        [[38,45,50,53],[34,41,46,50],[41,48,53,57],[36,43,48,52]],
        [[38,45,50,57],[41,48,53,60],[43,50,55,62],[45,52,57,64]],
        [[41,48,53,57],[36,43,48,52],[34,41,46,50],[38,45,50,53]],
        [[43,50,55,59],[38,45,50,53],[41,48,53,57],[45,52,57,60]],
        [[38,45,50,57],[45,52,57,64],[43,50,55,62],[41,48,53,60]],
        [[34,41,46,50],[38,45,50,53],[43,50,55,59],[41,48,53,57]],
        [[41,48,53,57],[43,50,55,59],[38,45,50,53],[45,52,57,60]],
        [[38,45,50,57],[34,41,46,53],[41,48,53,60],[45,52,57,64]],
        [[34,41,46,50],[41,48,53,57],[38,45,50,53],[34,41,46,50]],
        [[38,45,50,57],[41,48,53,60],[45,52,57,64],[38,45,50,57]],
    ]

    for i, rec in enumerate(scene_records):
        scene_len = float(rec["scene_duration_seconds"])
        chord_len = scene_len / 4.0
        chords = progressions[i]
        scene_energy = [54, 72, 62, 68, 76, 70, 73, 82, 58, 74][i]

        add_note(timpani, cursor + 0.05, 1.2, chords[0][0] - 2, 64 if i not in (1,7) else 84)
        if i in (1,4,7,9):
            add_note(timpani, cursor + scene_len * 0.52, 1.0, chords[2][0] - 2, 72)

        for c, chord in enumerate(chords):
            start = cursor + c * chord_len
            dur = chord_len + 0.35
            swell = scene_energy + (5 if c in (1,2) else 0)
            for note in chord:
                add_note(strings, start, dur, note + 12, min(104, swell))
            add_note(bass, start, dur, chord[0] - 12, min(94, swell - 4))
            add_note(choir, start + 0.45, max(0.8, dur - 0.7), chord[0] + 24, min(88, swell - 12))
            add_note(choir, start + 0.65, max(0.8, dur - 0.9), chord[2] + 24, min(82, swell - 16))
            if c in (0,2) or i in (1,7):
                add_note(horn, start + 0.65, max(1.2, dur * 0.64), chord[0] + 12, min(96, swell + 4))
                add_note(horn, start + 0.7, max(1.2, dur * 0.61), chord[2] + 12, min(88, swell - 2))

            arp = [chord[0] + 24, chord[1] + 24, chord[2] + 24, chord[3] + 24, chord[2] + 24, chord[1] + 24]
            step = min(1.05, chord_len / 7.0)
            at = start + 0.8
            k = 0
            while at < start + chord_len - 0.3:
                add_note(harp, at, min(1.2, step * 1.7), arp[k % len(arp)], 42 + (k % 3) * 5)
                at += step
                k += 1

        cursor += scene_len

    midi.tracks.append(build_track("String Ensemble", 48, 0, strings))
    midi.tracks.append(build_track("Choir Aahs", 52, 1, choir))
    midi.tracks.append(build_track("Contrabass", 43, 2, bass))
    midi.tracks.append(build_track("French Horn", 60, 3, horn))
    midi.tracks.append(build_track("Orchestral Harp", 46, 4, harp))
    midi.tracks.append(build_track("Timpani", 47, 5, timpani))
    midi.save(ROOT / "score.mid")
    return cursor


def main() -> None:
    kokoro = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
    actual_voice = select_voice(kokoro)
    records = []

    for i, scene in enumerate(SCENES):
        samples, sample_rate = kokoro.create(
            scene["script"],
            voice=actual_voice,
            speed=VOICE_SPEED,
            lang=LANGUAGE,
        )
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim > 1:
            samples = samples.mean(axis=-1)
        if not np.isfinite(samples).all() or not samples.size:
            raise RuntimeError(f"Invalid narration generated for {scene['id']}")
        peak = float(np.max(np.abs(samples)))
        if peak > 0.96:
            samples *= 0.96 / peak

        path = AUDIO / f"{scene['id']}.wav"
        sf.write(path, samples, int(sample_rate), subtype="PCM_16")
        info = sf.info(path)
        offset = 2.8 if i == 0 else (2.2 if i == 9 else 1.8)
        tail = 4.6 if i in (0,7,9) else 3.8
        scene_duration = float(info.duration) + offset + tail
        records.append({
            **scene,
            "file": str(path.relative_to(ROOT)),
            "duration_seconds": round(float(info.duration), 6),
            "narration_offset_seconds": offset,
            "scene_duration_seconds": round(scene_duration, 6),
            "sample_rate": int(info.samplerate),
            "channels": int(info.channels),
            "frames": int(info.frames),
            "sha256": sha256(path),
        })

    total_duration = compose_score(records)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "kokoro-onnx / Kokoro-82M v1.0",
        "voice_profile": "deep, measured British male stage narrator; original synthetic voice, not a celebrity imitation",
        "requested_voice_candidates": VOICE_CANDIDATES,
        "actual_voice": actual_voice,
        "language": LANGUAGE,
        "speed": VOICE_SPEED,
        "scene_count": len(records),
        "total_duration_seconds": round(total_duration, 6),
        "total_narration_seconds": round(sum(r["duration_seconds"] for r in records), 6),
        "scenes": records,
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    if len(list(AUDIO.glob("*.wav"))) != 10:
        raise RuntimeError("Expected ten narration WAV files")
    if any(r["channels"] != 1 for r in records):
        raise RuntimeError("Narration must remain mono")
    print(json.dumps({
        "voice": actual_voice,
        "scene_count": len(records),
        "narration_seconds": manifest["total_narration_seconds"],
        "film_seconds": manifest["total_duration_seconds"],
    }, indent=2))


if __name__ == "__main__":
    main()
