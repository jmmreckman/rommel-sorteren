import io
import logging
import os
from pathlib import Path

import pillow_heif
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from PIL import Image, ImageOps

from .db import get_db

pillow_heif.register_heif_opener()  # zodat HEIC/HEIF-foto's (standaard op recente telefoons) ook werken

logger = logging.getLogger("rommel")

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
THUMB_DIR = Path(__file__).resolve().parent.parent / "data" / "thumbs"
SMALL_SIZE = (500, 500)
MEDIUM_SIZE = (1400, 1400)


def _drive_service():
    creds_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def _list_drive_images(service, folder_id: str):
    query = f"'{folder_id}' in parents and trashed = false and mimeType contains 'image/'"
    page_token = None
    while True:
        resp = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, webViewLink)",
            pageToken=page_token,
            pageSize=100,
        ).execute()
        for f in resp.get("files", []):
            yield f
        page_token = resp.get("nextPageToken")
        if not page_token:
            break


def _download_bytes(service, file_id: str) -> bytes:
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def _make_thumb(raw: bytes, path: Path, max_size):
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    img.thumbnail(max_size)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "WEBP", quality=82)


def sync_drive() -> dict:
    folder_id = os.environ["DRIVE_FOLDER_ID"]
    service = _drive_service()
    THUMB_DIR.mkdir(parents=True, exist_ok=True)

    with get_db() as conn:
        existing = {row["drive_file_id"] for row in conn.execute("SELECT drive_file_id FROM photos")}
        existing |= {row["drive_file_id"] for row in conn.execute("SELECT drive_file_id FROM deleted_drive_files")}

    added = 0
    skipped = 0
    for f in _list_drive_images(service, folder_id):
        if f["id"] in existing:
            skipped += 1
            continue

        try:
            raw = _download_bytes(service, f["id"])
            small_path = THUMB_DIR / f"{f['id']}_s.webp"
            medium_path = THUMB_DIR / f"{f['id']}_m.webp"
            _make_thumb(raw, small_path, SMALL_SIZE)
            _make_thumb(raw, medium_path, MEDIUM_SIZE)
            del raw  # nooit het volledige origineel bewaren, alleen de thumbnails
        except Exception:
            # Eén onleesbare/onverwachte foto mag de rest van de sync niet
            # blokkeren - overslaan en bij de volgende ronde opnieuw proberen.
            logger.exception("Foto '%s' (%s) kon niet verwerkt worden, overgeslagen", f.get("name"), f["id"])
            continue

        with get_db() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO photos
                   (drive_file_id, filename, thumb_small, thumb_medium, drive_link)
                   VALUES (?, ?, ?, ?, ?)""",
                (f["id"], f["name"], f"thumbs/{small_path.name}", f"thumbs/{medium_path.name}",
                 f.get("webViewLink")),
            )
        added += 1

    return {"added": added, "skipped_already_synced": skipped}


if __name__ == "__main__":
    print(sync_drive())
