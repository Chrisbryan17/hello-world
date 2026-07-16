from __future__ import annotations

import hashlib
import json
import pathlib
import time
import traceback
import urllib.parse
import urllib.request

from PIL import Image

ITEMS = [
    ("earth_waters", "File:Separation of the Earth from the Waters.png", "Michelangelo", "The Separation of the Earth and Waters", "public domain"),
    ("creation_eve", "File:The Creation of Eve (1).png", "Michelangelo", "The Creation of Eve", "public domain"),
    ("garden_eve", "File:The Garden of Eden with the Creation of Eve (Jan Brueghel the Younger).jpg", "Jan Brueghel the Younger", "The Garden of Eden with the Creation of Eve", "public domain"),
    ("world_expulsion", "File:The Creation of the World and the Expulsion from Paradise MET Paradise0236.jpg", "Giovanni di Paolo", "The Creation of the World and the Expulsion from Paradise", "CC0"),
    ("world_lesueur", "File:Eustache Le Sueur - The Creation of the World.jpg", "Eustache Le Sueur", "The Creation of the World", "public domain"),
    ("adam_naming", "File:Adam in the Garden of Eden, Naming the Animals MET DT5631.jpg", "Joachim Wtewael", "Adam in the Garden of Eden, Naming the Animals", "CC0"),
    ("garden_animals", "File:Garden of Eden; Creation of the Animals MET DP801707.jpg", "Anonymous Netherlandish", "Garden of Eden; Creation of the Animals", "CC0"),
    ("world_roos", "File:The Creation of the World (Cajetan Roos)-WUS02198.jpg", "Cajetan Roos", "The Creation of the World", "CC0"),
]

ROOT = pathlib.Path("genesis-more-paintings")
ART = ROOT / "art"
API = "https://commons.wikimedia.org/w/api.php"
ERROR = ROOT / "error.txt"


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def open_retry(opener: urllib.request.OpenerDirector, url: str, timeout: int):
    last = None
    for attempt in range(1, 5):
        try:
            return opener.open(url, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"Attempt {attempt} failed for {url}: {type(exc).__name__}: {exc}", flush=True)
            if attempt < 4:
                time.sleep(2.5 * attempt)
    raise RuntimeError(f"All retries failed for {url}: {last}")


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener()
    opener.addheaders = [("User-Agent", "GenesisFilmBuilder/2.3 (https://github.com/Chrisbryan17/hello-world)")]
    manifest = []

    for slug, title, artist, artwork_title, license_name in ITEMS:
        print(f"Resolving {slug}: {title}", flush=True)
        qs = urllib.parse.urlencode({
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "iiprop": "url|size|mime|sha1",
            "iiurlwidth": "2400",
            "titles": title,
        })
        with open_retry(opener, API + "?" + qs, 120) as response:
            data = json.load(response)
        page = next(iter(data["query"]["pages"].values()))
        if "missing" in page or "imageinfo" not in page:
            raise RuntimeError(f"Commons file title did not resolve: {title}; page={page}")
        info = page["imageinfo"][0]
        source_url = info.get("thumburl") or info["url"]
        ext = pathlib.Path(urllib.parse.urlparse(source_url).path).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png"}:
            ext = pathlib.Path(urllib.parse.urlparse(info["url"]).path).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png"}:
            ext = ".jpg"
        out = ART / f"{slug}{ext}"
        with open_retry(opener, source_url, 240) as response:
            out.write_bytes(response.read())
        with Image.open(out) as image:
            image.verify()
        with Image.open(out) as image:
            width, height = image.size
        if width < 700 or height < 600:
            raise RuntimeError(f"Painting below minimum dimensions: {slug} {width}x{height}")
        manifest.append({
            "slug": slug,
            "file": str(out.relative_to(ROOT)),
            "commons_title": title,
            "artist": artist,
            "title": artwork_title,
            "license": license_name,
            "source_url": info.get("descriptionurl", ""),
            "original_url": info["url"],
            "download_url": source_url,
            "width": width,
            "height": height,
            "bytes": out.stat().st_size,
            "sha256": sha256(out),
        })
        print(f"Downloaded {slug}: {width}x{height}, {out.stat().st_size} bytes", flush=True)

    if len(manifest) != len(ITEMS):
        raise RuntimeError(f"Expected {len(ITEMS)} paintings, found {len(manifest)}")
    (ROOT / "manifest.json").write_text(
        json.dumps({"count": len(manifest), "paintings": manifest}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Verified and manifested {len(manifest)} paintings", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        ROOT.mkdir(parents=True, exist_ok=True)
        ERROR.write_text(traceback.format_exc(), encoding="utf-8")
        print(ERROR.read_text(encoding="utf-8"), flush=True)
        raise
