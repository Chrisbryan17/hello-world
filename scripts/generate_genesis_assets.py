from __future__ import annotations

import hashlib
import json
import pathlib
import time
import urllib.request
from datetime import datetime, timezone

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

ROOT = pathlib.Path("genesis-assets")
AUDIO = ROOT / "audio"
ART = ROOT / "art"
AUDIO.mkdir(parents=True, exist_ok=True)
ART.mkdir(parents=True, exist_ok=True)

SCENES = [
    {
        "id": "00_prologue",
        "heading": "BEFORE THE FIRST DAWN",
        "script": "Before the first dawn, before the first breath, before time could be measured by sun or moon, there was darkness over the deep. The earth was unformed and empty. Yet the silence was not abandoned. The Spirit of God moved over the waters, and creation waited for a word.",
    },
    {
        "id": "01_light",
        "heading": "DAY ONE — LIGHT",
        "script": "Then God spoke: Let there be light. And light broke into the darkness. Day was divided from night; brightness from shadow. The first evening passed, and the first morning came. The universe had received its first rhythm, and God saw that the light was good.",
    },
    {
        "id": "02_sky",
        "heading": "DAY TWO — THE HEAVENS",
        "script": "God stretched an expanse between the waters. Above, the heavens opened like a vast blue sanctuary. Below, the seas gathered beneath it. Mist rose. Clouds formed. Wind crossed the face of the deep. The world gained height, distance, and a horizon.",
    },
    {
        "id": "03_land",
        "heading": "DAY THREE — LAND AND LIFE",
        "script": "The waters drew back, and dry ground appeared. Mountains lifted from the sea. Valleys opened. Rivers found their paths. Then the bare earth awakened. Grass unfolded. Trees reached upward. Seed and fruit carried life within themselves, ready to fill the world again and again.",
    },
    {
        "id": "04_lights",
        "heading": "DAY FOUR — SUN, MOON, AND STARS",
        "script": "God appointed lights in the heavens: the sun to govern the day, the moon to watch over the night, and stars beyond counting. They marked seasons, days, and years. What had been formless now moved with order; what had been dark now shone with signs of purpose.",
    },
    {
        "id": "05_sea_sky",
        "heading": "DAY FIVE — SEA AND SKY",
        "script": "The waters surged with living creatures. Great beasts moved through the deep. Silver shoals turned as one beneath the waves. Above them, wings filled the open sky: eagles, doves, and birds of every kind. God blessed them to multiply, until sea and heaven overflowed with life.",
    },
    {
        "id": "06_animals",
        "heading": "DAY SIX — CREATURES OF THE EARTH",
        "script": "Across the land came creatures strong and small: cattle in the fields, lions in the grass, deer among the trees, and every animal that moved close to the earth. Each entered the world according to its kind, taking its place inside a creation rich with balance and wonder.",
    },
    {
        "id": "07_humanity",
        "heading": "DAY SIX — HUMANITY",
        "script": "Then God said, Let us make humanity in our image. From the dust came a living form, and into it came breath. Male and female, humanity was created with dignity, imagination, and responsibility: to cultivate the earth, to guard its life, and to reflect the Creator within creation. God looked upon everything that had been made, and it was very good.",
    },
    {
        "id": "08_rest",
        "heading": "DAY SEVEN — REST",
        "script": "The heavens and the earth were complete. On the seventh day, God rested—not from weakness, but in completion. The day was blessed and set apart. Creation did not end in noise or conquest, but in peace: a sacred pause in which the work could be seen, received, and called good.",
    },
    {
        "id": "09_epilogue",
        "heading": "GENESIS",
        "script": "This is the beginning: light from darkness, order from chaos, life from the earth, and humanity entrusted with a living world. Genesis opens with a creation spoken into beauty—and with an invitation to remember that existence itself is a gift.",
    },
]

ARTWORKS = {
    "light.jpg": {
        "url": "https://upload.wikimedia.org/wikipedia/commons/5/5d/Dividing_Light_from_Darkness.jpg",
        "fallback_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/5/5d/Dividing_Light_from_Darkness.jpg/1280px-Dividing_Light_from_Darkness.jpg",
        "title": "Separation of Light from Darkness",
        "artist": "Michelangelo",
        "status": "public domain",
    },
    "sun_moon.jpg": {
        "url": "https://upload.wikimedia.org/wikipedia/commons/3/3c/Michelangelo%2C_Creation_of_the_Sun%2C_Moon%2C_and_Plants_01.jpg",
        "fallback_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3c/Michelangelo%2C_Creation_of_the_Sun%2C_Moon%2C_and_Plants_01.jpg/1280px-Michelangelo%2C_Creation_of_the_Sun%2C_Moon%2C_and_Plants_01.jpg",
        "title": "The Creation of the Sun, Moon, and Plants",
        "artist": "Michelangelo",
        "status": "public domain",
    },
    "adam.jpg": {
        "url": "https://upload.wikimedia.org/wikipedia/commons/5/5b/Michelangelo_-_Creation_of_Adam_%28cropped%29.jpg",
        "fallback_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/5/5b/Michelangelo_-_Creation_of_Adam_%28cropped%29.jpg/1280px-Michelangelo_-_Creation_of_Adam_%28cropped%29.jpg",
        "title": "The Creation of Adam",
        "artist": "Michelangelo",
        "status": "public domain",
    },
    "animals.jpg": {
        "url": "https://upload.wikimedia.org/wikipedia/commons/8/87/Jacopo_Tintoretto_%E2%80%94_Creation_of_the_Animals.jpg",
        "fallback_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/87/Jacopo_Tintoretto_%E2%80%94_Creation_of_the_Animals.jpg/1280px-Jacopo_Tintoretto_%E2%80%94_Creation_of_the_Animals.jpg",
        "title": "The Creation of the Animals",
        "artist": "Tintoretto",
        "status": "public domain",
    },
}


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(urls: list[str], destination: pathlib.Path) -> str:
    if destination.exists() and destination.stat().st_size > 1024:
        print(f"Artwork already present: {destination} ({destination.stat().st_size} bytes)", flush=True)
        return "preexisting"
    last_error = None
    for url in urls:
        for attempt in range(1, 5):
            try:
                print(f"Downloading {destination.name}, attempt {attempt}: {url}", flush=True)
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 GenesisVideoBuilder/1.1"},
                )
                with urllib.request.urlopen(request, timeout=180) as response:
                    payload = response.read()
                if len(payload) < 1024:
                    raise RuntimeError(f"download too small: {len(payload)} bytes")
                destination.write_bytes(payload)
                print(f"Downloaded {destination.name}: {len(payload)} bytes", flush=True)
                return url
            except Exception as exc:
                last_error = exc
                print(f"Download failed: {type(exc).__name__}: {exc}", flush=True)
                time.sleep(attempt * 2)
    raise RuntimeError(f"Unable to download {destination.name}: {last_error}")


model = pathlib.Path("kokoro-v1.0.onnx")
voices = pathlib.Path("voices-v1.0.bin")
if not model.exists() or not voices.exists():
    raise FileNotFoundError("Kokoro model files were not downloaded")

print("Loading Kokoro model", flush=True)
kokoro = Kokoro(str(model), str(voices))
requested_voice = "am_michael"
actual_voice = requested_voice
records = []

for index, scene in enumerate(SCENES, 1):
    print(f"Generating narration {index}/10: {scene['id']}", flush=True)
    tts_text = scene["script"].replace("—", ", ").replace("–", "-")
    samples, sample_rate = kokoro.create(
        tts_text, voice=actual_voice, speed=0.94, lang="en-us"
    )
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples.mean(axis=-1)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak > 0.98:
        samples = samples * (0.98 / peak)
    output = AUDIO / f"{scene['id']}.wav"
    sf.write(output, samples, int(sample_rate), subtype="PCM_16")
    info = sf.info(output)
    print(
        f"Wrote {output}: {info.duration:.3f}s, {info.samplerate}Hz, {info.channels}ch",
        flush=True,
    )
    records.append(
        {
            **scene,
            "file": str(output.relative_to(ROOT)),
            "duration_seconds": round(float(info.duration), 6),
            "sample_rate": int(info.samplerate),
            "channels": int(info.channels),
            "frames": int(info.frames),
            "sha256": sha256(output),
        }
    )

art_records = []
for filename, metadata in ARTWORKS.items():
    destination = ART / filename
    source_used = download([metadata["url"], metadata["fallback_url"]], destination)
    art_records.append(
        {
            "file": str(destination.relative_to(ROOT)),
            "bytes": destination.stat().st_size,
            "sha256": sha256(destination),
            "source_used": source_used,
            **metadata,
        }
    )

manifest = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "engine": "kokoro-onnx / Kokoro-82M v1.0",
    "requested_voice": requested_voice,
    "actual_voice": actual_voice,
    "language": "en-us",
    "speed": 0.94,
    "scene_count": len(records),
    "total_narration_seconds": round(sum(item["duration_seconds"] for item in records), 6),
    "scenes": records,
    "artworks": art_records,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
(ROOT / "storyboard.json").write_text(
    json.dumps({"title": "GENESIS — The First Seven Days", "scenes": SCENES}, indent=2) + "\n",
    encoding="utf-8",
)

if len(list(AUDIO.glob("*.wav"))) != 10:
    raise RuntimeError("Expected ten narration WAV files")
if any(item["channels"] != 1 for item in records):
    raise RuntimeError("All narration must remain mono")
if len(list(ART.glob("*.jpg"))) != 4:
    raise RuntimeError("Expected four artwork files")

print(json.dumps({
    "scene_count": len(records),
    "voice": actual_voice,
    "total_narration_seconds": manifest["total_narration_seconds"],
    "art_count": len(art_records),
}, indent=2), flush=True)
