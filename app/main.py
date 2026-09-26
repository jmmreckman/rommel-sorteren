import asyncio
import hashlib
import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, Request, Response, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .db import init_db, get_db, USERS, other_user, choices_match, CATEGORY_PALETTE
from .mailer import stuur_mail
from .photos import upload_photo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rommel")

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR.parent / "data"

app = FastAPI(title="Rommel Sorteren")

# Verandert bij elke herstart (dus bij elke deploy), zodat style.css/app.js
# een nieuwe URL krijgen en de browser ze nooit uit een oude cache pakt.
ASSET_VERSION = str(int(time.time()))


def _serve_html(filename: str) -> Response:
    html = (APP_DIR / "static" / filename).read_text()
    html = html.replace("/assets/style.css", f"/assets/style.css?v={ASSET_VERSION}")
    html = html.replace("/assets/app.js", f"/assets/app.js?v={ASSET_VERSION}")
    return Response(html, media_type="text/html")


PUBLIC_PATHS = {"/login", "/health", "/garage-sale"}


def _site_password() -> str:
    return os.environ.get("SITE_PASSWORD", "verander-mij")


def _sign(user: str) -> str:
    return hashlib.sha256(f"{user}:{_site_password()}".encode()).hexdigest()


def _parse_session(cookie_value: str | None) -> str | None:
    if not cookie_value or "." not in cookie_value:
        return None
    user, token = cookie_value.split(".", 1)
    if user in USERS and token == _sign(user):
        return user
    return None


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if (path in PUBLIC_PATHS or path.startswith("/assets/") or path.startswith("/thumbs/")
            or path.startswith("/api/garage-sale")):
        response = await call_next(request)
        if not path.startswith("/thumbs/"):
            # HTML/JS/CSS wijzigen regelmatig tijdens ontwikkeling - nooit
            # laten cachen, anders zie je soms een oude versie van de app.
            # Thumbnails zelf veranderen nooit (vast bestandsnaam), die mogen
            # gewoon lang gecached blijven.
            response.headers["Cache-Control"] = "no-store"
        return response
    user = _parse_session(request.cookies.get("session"))
    if user is None:
        if path.startswith("/api/"):
            return JSONResponse({"error": "niet ingelogd"}, status_code=401)
        return RedirectResponse("/login")
    request.state.user = user
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


def current_user(request: Request) -> str:
    return request.state.user


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/login")
def login_page():
    return _serve_html("login.html")


@app.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    user = form.get("user")
    password = form.get("password")
    if user in USERS and password == _site_password():
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(
            "session", f"{user}.{_sign(user)}",
            max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax",
        )
        return resp
    return RedirectResponse("/login?fout=1", status_code=303)


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login")
    resp.delete_cookie("session")
    return resp


@app.get("/api/me")
def api_me(user: str = Depends(current_user)):
    return {"user": user, "partner": other_user(user)}


@app.get("/api/categories")
def api_categories():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM categories ORDER BY sort_order, id").fetchall()
    return [dict(r) for r in rows]


class CategoryIn(BaseModel):
    name: str
    requires_name: bool = False


@app.post("/api/categories")
def api_add_category(body: CategoryIn):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "naam mag niet leeg zijn")
    with get_db() as conn:
        existing = conn.execute("SELECT * FROM categories WHERE LOWER(name)=LOWER(?)", (name,)).fetchone()
        if existing:
            return dict(existing)
        next_order = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 n FROM categories").fetchone()["n"]
        count = conn.execute("SELECT COUNT(*) c FROM categories").fetchone()["c"]
        color = CATEGORY_PALETTE[count % len(CATEGORY_PALETTE)]
        cur = conn.execute(
            "INSERT INTO categories (name, requires_name, sort_order, color) VALUES (?, ?, ?, ?)",
            (name, int(body.requires_name), next_order, color),
        )
        row = conn.execute("SELECT * FROM categories WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


class CategoryUpdateIn(BaseModel):
    garage_sale: bool


@app.patch("/api/categories/{category_id}")
def api_update_category(category_id: int, body: CategoryUpdateIn):
    with get_db() as conn:
        row = conn.execute("SELECT id FROM categories WHERE id=?", (category_id,)).fetchone()
        if not row:
            raise HTTPException(404, "categorie niet gevonden")
        conn.execute("UPDATE categories SET garage_sale=? WHERE id=?", (int(body.garage_sale), category_id))
    return {"ok": True}


@app.get("/api/stats")
def api_stats(user: str = Depends(current_user)):
    partner = other_user(user)
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"]
        my_queue = conn.execute(
            "SELECT COUNT(*) c FROM photos WHERE id NOT IN (SELECT photo_id FROM choices WHERE user=?)",
            (user,),
        ).fetchone()["c"]
        rows = conn.execute(
            """SELECT ca.category_id cat_a, ca.person_name name_a, cj.category_id cat_j, cj.person_name name_j
               FROM choices ca JOIN choices cj ON ca.photo_id = cj.photo_id
               WHERE ca.user=? AND cj.user=?""",
            (user, partner),
        ).fetchall()
        overleg = 0
        resolved = 0
        for r in rows:
            a = {"category_id": r["cat_a"], "person_name": r["name_a"]}
            b = {"category_id": r["cat_j"], "person_name": r["name_j"]}
            if choices_match(a, b):
                resolved += 1
            else:
                overleg += 1
        waiting_for_partner = conn.execute(
            """SELECT COUNT(*) c FROM choices ca
               WHERE ca.user=? AND ca.photo_id NOT IN (SELECT photo_id FROM choices WHERE user=?)""",
            (user, partner),
        ).fetchone()["c"]
    return {
        "total": total,
        "my_queue": my_queue,
        "overleg": overleg,
        "resolved": resolved,
        "waiting_for_partner": waiting_for_partner,
    }


@app.delete("/api/photos/{photo_id}")
def api_delete_photo(photo_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
        if not row:
            raise HTTPException(404, "foto niet gevonden")
        conn.execute("DELETE FROM photos WHERE id=?", (photo_id,))
    for rel_path in (row["thumb_small"], row["thumb_medium"]):
        (DATA_DIR / rel_path).unlink(missing_ok=True)
    return {"ok": True}


class TagsIn(BaseModel):
    tags: str = ""


@app.patch("/api/photos/{photo_id}/tags")
def api_update_tags(photo_id: int, body: TagsIn):
    with get_db() as conn:
        row = conn.execute("SELECT id FROM photos WHERE id=?", (photo_id,)).fetchone()
        if not row:
            raise HTTPException(404, "foto niet gevonden")
        conn.execute("UPDATE photos SET tags=? WHERE id=?", (body.tags.strip(), photo_id))
    return {"ok": True, "tags": body.tags.strip()}


@app.post("/api/photos/upload")
async def api_upload_photo(file: UploadFile = File(...), tags: str = Form("")):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "leeg bestand")
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, upload_photo, raw, file.filename, tags)
    except Exception as e:
        raise HTTPException(500, f"upload mislukt: {e}")
    return result


def _describe_photo(conn, photo) -> dict:
    cats = {c["id"]: dict(c) for c in conn.execute("SELECT * FROM categories").fetchall()}
    choices = {
        row["user"]: row
        for row in conn.execute("SELECT * FROM choices WHERE photo_id=?", (photo["id"],)).fetchall()
    }

    def describe(user):
        c = choices.get(user)
        if not c:
            return None
        cat = cats.get(c["category_id"])
        return {
            "category": cat["name"] if cat else "?",
            "color": cat["color"] if cat else "#888888",
            "person_name": c["person_name"],
        }

    ayla = describe("ayla")
    jurian = describe("jurian")
    if ayla and jurian:
        status = "definitief" if choices_match(
            {"category_id": choices["ayla"]["category_id"], "person_name": choices["ayla"]["person_name"]},
            {"category_id": choices["jurian"]["category_id"], "person_name": choices["jurian"]["person_name"]},
        ) else "overleg"
    elif ayla or jurian:
        status = "wachten"
    else:
        status = "nog niks gekozen"

    return {
        "id": photo["id"],
        "filename": photo["filename"],
        "thumb_small": photo["thumb_small"],
        "thumb_medium": photo["thumb_medium"],
        "tags": photo["tags"],
        "status": status,
        "ayla": ayla,
        "jurian": jurian,
    }


@app.get("/api/photos/search")
def api_search_photos(q: str = ""):
    q = q.strip()
    with get_db() as conn:
        if not q:
            # Leeg zoekveld: toon alles, ongeacht status - zodat ook foto's
            # die nergens anders zichtbaar zijn (bv. alleen door jou al
            # gekozen, partner nog niet) terug te vinden en te verwijderen zijn.
            rows = conn.execute(
                "SELECT * FROM photos ORDER BY added_at DESC LIMIT 500",
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM photos WHERE tags LIKE ? ORDER BY added_at DESC LIMIT 40",
                (f"%{q}%",),
            ).fetchall()
        return [_describe_photo(conn, r) for r in rows]


@app.get("/api/queue")
def api_queue(limit: int = 6, user: str = Depends(current_user)):
    partner = other_user(user)
    with get_db() as conn:
        rows = conn.execute(
            """SELECT p.*, cp.category_id AS partner_category_id, cp.person_name AS partner_person_name
               FROM photos p
               LEFT JOIN choices cp ON cp.photo_id = p.id AND cp.user = ?
               WHERE p.id NOT IN (SELECT photo_id FROM choices WHERE user=?)
               ORDER BY p.added_at ASC LIMIT ?""",
            (partner, user, limit),
        ).fetchall()
    return [dict(r) for r in rows]


class ChoiceIn(BaseModel):
    photo_id: int
    category_id: int
    person_name: str | None = None


def _meld_mijlpaal(user: str, total_choices: int) -> None:
    """Mailt Jurian zodra Ayla weer 10 foto's verwerkt heeft."""
    if user != "ayla" or total_choices == 0 or total_choices % 10 != 0:
        return
    stuur_mail(
        "Ayla is weer bezig geweest op Rommel Sorteren! 🎉",
        f"Ayla heeft nu in totaal {total_choices} foto's gecategoriseerd.\n\n"
        f"Kijk maar mee op https://rommel.steenhub.nl",
    )


@app.post("/api/choice")
def api_choice(body: ChoiceIn, user: str = Depends(current_user)):
    partner = other_user(user)
    with get_db() as conn:
        cat = conn.execute("SELECT * FROM categories WHERE id=?", (body.category_id,)).fetchone()
        if not cat:
            raise HTTPException(400, "onbekende categorie")
        conn.execute(
            """INSERT INTO choices (photo_id, user, category_id, person_name, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(photo_id, user) DO UPDATE SET
                 category_id=excluded.category_id, person_name=excluded.person_name, updated_at=datetime('now')""",
            (body.photo_id, user, body.category_id, body.person_name),
        )
        partner_choice = conn.execute(
            "SELECT category_id, person_name FROM choices WHERE photo_id=? AND user=?",
            (body.photo_id, partner),
        ).fetchone()
        total_choices = conn.execute(
            "SELECT COUNT(*) c FROM choices WHERE user=?", (user,)
        ).fetchone()["c"]
    _meld_mijlpaal(user, total_choices)
    if partner_choice is None:
        return {"ok": True, "partner_chose": False, "match": None, "total_choices": total_choices}
    match = choices_match(
        {"category_id": body.category_id, "person_name": body.person_name},
        {"category_id": partner_choice["category_id"], "person_name": partner_choice["person_name"]},
    )
    return {"ok": True, "partner_chose": True, "match": match, "total_choices": total_choices}


@app.get("/api/overleg")
def api_overleg(user: str = Depends(current_user)):
    partner = other_user(user)
    with get_db() as conn:
        rows = conn.execute(
            """SELECT p.*, ca.category_id cat_a, ca.person_name name_a, cj.category_id cat_j, cj.person_name name_j
               FROM photos p
               JOIN choices ca ON ca.photo_id = p.id AND ca.user = ?
               JOIN choices cj ON cj.photo_id = p.id AND cj.user = ?
               ORDER BY p.added_at ASC""",
            (user, partner),
        ).fetchall()
        cats = {c["id"]: dict(c) for c in conn.execute("SELECT * FROM categories").fetchall()}
    result = []
    for r in rows:
        a = {"category_id": r["cat_a"], "person_name": r["name_a"]}
        b = {"category_id": r["cat_j"], "person_name": r["name_j"]}
        if choices_match(a, b):
            continue
        result.append({
            "id": r["id"],
            "filename": r["filename"],
            "thumb_small": r["thumb_small"],
            "thumb_medium": r["thumb_medium"],
            "tags": r["tags"],
            "mine": {"category": cats[a["category_id"]]["name"], "color": cats[a["category_id"]]["color"], "person_name": a["person_name"]},
            "theirs": {"category": cats[b["category_id"]]["name"], "color": cats[b["category_id"]]["color"], "person_name": b["person_name"]},
        })
    return result


@app.post("/api/overleg/{photo_id}/adopt")
def api_overleg_adopt(photo_id: int, user: str = Depends(current_user)):
    partner = other_user(user)
    with get_db() as conn:
        partner_choice = conn.execute(
            "SELECT category_id, person_name FROM choices WHERE photo_id=? AND user=?",
            (photo_id, partner),
        ).fetchone()
        if not partner_choice:
            raise HTTPException(404, "geen keuze van partner gevonden")
        conn.execute(
            """INSERT INTO choices (photo_id, user, category_id, person_name, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(photo_id, user) DO UPDATE SET
                 category_id=excluded.category_id, person_name=excluded.person_name, updated_at=datetime('now')""",
            (photo_id, user, partner_choice["category_id"], partner_choice["person_name"]),
        )
        total_choices = conn.execute(
            "SELECT COUNT(*) c FROM choices WHERE user=?", (user,)
        ).fetchone()["c"]
    _meld_mijlpaal(user, total_choices)
    return {"ok": True, "total_choices": total_choices}


@app.get("/api/resultaten")
def api_resultaten():
    with get_db() as conn:
        cats = conn.execute("SELECT * FROM categories ORDER BY sort_order, id").fetchall()
        rows = conn.execute(
            """SELECT p.*, ca.category_id cat_a, ca.person_name name_a, cj.category_id cat_j, cj.person_name name_j
               FROM photos p
               JOIN choices ca ON ca.photo_id = p.id AND ca.user = 'ayla'
               JOIN choices cj ON cj.photo_id = p.id AND cj.user = 'jurian'
               ORDER BY p.added_at ASC"""
        ).fetchall()
    grouped = {c["id"]: {"category": dict(c), "photos": []} for c in cats}
    for r in rows:
        a = {"category_id": r["cat_a"], "person_name": r["name_a"]}
        b = {"category_id": r["cat_j"], "person_name": r["name_j"]}
        if not choices_match(a, b):
            continue
        if r["cat_a"] not in grouped:
            continue
        grouped[r["cat_a"]]["photos"].append({
            "id": r["id"],
            "filename": r["filename"],
            "thumb_small": r["thumb_small"],
            "thumb_medium": r["thumb_medium"],
            "person_name": r["name_a"],
            "tags": r["tags"],
        })
    return list(grouped.values())


@app.get("/api/garage-sale")
def api_garage_sale():
    with get_db() as conn:
        garage_cats = {row["id"] for row in conn.execute("SELECT id FROM categories WHERE garage_sale=1")}
        if not garage_cats:
            return []
        rows = conn.execute(
            """SELECT p.*, ca.category_id cat_a, ca.person_name name_a, cj.category_id cat_j, cj.person_name name_j
               FROM photos p
               JOIN choices ca ON ca.photo_id = p.id AND ca.user = 'ayla'
               JOIN choices cj ON cj.photo_id = p.id AND cj.user = 'jurian'
               ORDER BY p.added_at ASC"""
        ).fetchall()
        result = []
        for r in rows:
            a = {"category_id": r["cat_a"], "person_name": r["name_a"]}
            b = {"category_id": r["cat_j"], "person_name": r["name_j"]}
            if not choices_match(a, b) or r["cat_a"] not in garage_cats:
                continue
            interesse = [
                row["name"] for row in conn.execute(
                    "SELECT name FROM garage_sale_interest WHERE photo_id=? ORDER BY created_at",
                    (r["id"],),
                ).fetchall()
            ]
            result.append({
                "id": r["id"],
                "filename": r["filename"],
                "thumb_small": r["thumb_small"],
                "thumb_medium": r["thumb_medium"],
                "tags": r["tags"],
                "interesse": interesse,
            })
    return result


class InterestIn(BaseModel):
    name: str


@app.post("/api/garage-sale/{photo_id}/interest")
def api_garage_sale_interest(photo_id: int, body: InterestIn):
    naam = body.name.strip()
    if not naam:
        raise HTTPException(400, "naam mag niet leeg zijn")
    with get_db() as conn:
        photo = conn.execute("SELECT id FROM photos WHERE id=?", (photo_id,)).fetchone()
        if not photo:
            raise HTTPException(404, "product niet gevonden")
        conn.execute(
            "INSERT INTO garage_sale_interest (photo_id, name) VALUES (?, ?)",
            (photo_id, naam),
        )
    return {"ok": True}


(DATA_DIR / "thumbs").mkdir(parents=True, exist_ok=True)
app.mount("/thumbs", StaticFiles(directory=str(DATA_DIR / "thumbs")), name="thumbs")
app.mount("/assets", StaticFiles(directory=str(APP_DIR / "static")), name="assets")


@app.get("/{page:path}")
def spa(page: str):
    file_map = {
        "": "index.html",
        "kiezen": "kiezen.html",
        "overleg": "overleg.html",
        "resultaten": "resultaten.html",
        "toevoegen": "toevoegen.html",
        "zoek": "zoek.html",
        "garage-sale": "garage-sale.html",
    }
    filename = file_map.get(page.strip("/"))
    if not filename:
        raise HTTPException(404)
    return _serve_html(filename)
