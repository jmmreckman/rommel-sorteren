import io
import uuid
from pathlib import Path

import pillow_heif
from PIL import Image, ImageOps

from .db import get_db

pillow_heif.register_heif_opener()  # zodat HEIC/HEIF-foto's (standaard op recente telefoons) ook werken

THUMB_DIR = Path(__file__).resolve().parent.parent / "data" / "thumbs"
SMALL_SIZE = (500, 500)
MEDIUM_SIZE = (1400, 1400)


def _make_thumb(raw: bytes, path: Path, max_size):
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    img.thumbnail(max_size)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "WEBP", quality=82)


def upload_photo(raw: bytes, filename: str, tags: str = "") -> dict:
    """Foto rechtstreeks vanuit de app: thumbnails maken en lokaal
    registreren, zodat de ingevulde tags/naam meteen doorzoekbaar zijn."""
    local_id = f"local:{uuid.uuid4().hex}"

    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    small_path = THUMB_DIR / f"{local_id.split(':')[1]}_s.webp"
    medium_path = THUMB_DIR / f"{local_id.split(':')[1]}_m.webp"
    _make_thumb(raw, small_path, SMALL_SIZE)
    _make_thumb(raw, medium_path, MEDIUM_SIZE)

    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO photos (drive_file_id, filename, thumb_small, thumb_medium, tags)
               VALUES (?, ?, ?, ?, ?)""",
            (local_id, filename or "foto.jpg", f"thumbs/{small_path.name}",
             f"thumbs/{medium_path.name}", (tags or "").strip()),
        )
        photo_id = cur.lastrowid

    return {"id": photo_id, "tags": (tags or "").strip()}
