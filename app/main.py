import asyncio
import hashlib
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .db import init_db, get_db, USERS, other_user, choices_match, CATEGORY_PALETTE
from .drive_sync import sync_drive

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rommel")

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR.parent / "data"

app = FastAPI(title="Rommel Sorteren")
_sync_lock = asyncio.Lock()


async def run_sync():
    """Draait de (blokkerende) Drive-sync in een aparte thread, met een lock
    zodat een handmatige klik en de automatische achtergrondsync elkaar
    nooit overlappen."""
    async with _sync_lock:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, sync_drive)


async def _periodic_sync_loop():
    interval_minutes = int(os.environ.get("SYNC_INTERVAL_MINUTES", "15"))
    while True:
        await asyncio.sleep(interval_minutes * 60)
        try:
            result = await run_sync()
            logger.info("Automatische Drive-sync: %s", result)
        except Exception:
            logger.exception(
                "Automatische Drive-sync mislukt, probeer over %s minuten opnieuw",
                interval_minutes,
            )

PUBLIC_PATHS = {"/login", "/health"}


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
    if path in PUBLIC_PATHS or path.startswith("/assets/") or path.startswith("/thumbs/"):
        return await call_next(request)
    user = _parse_session(request.cookies.get("session"))
    if user is None:
        if path.startswith("/api/"):
            return JSONResponse({"error": "niet ingelogd"}, status_code=401)
        return RedirectResponse("/login")
    request.state.user = user
    return await call_next(request)


def current_user(request: Request) -> str:
    return request.state.user


@app.on_event("startup")
def _startup():
    init_db()
    asyncio.create_task(_periodic_sync_loop())


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/login")
def login_page():
    return Response((APP_DIR / "static" / "login.html").read_text(), media_type="text/html")


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
    if partner_choice is None:
        return {"ok": True, "partner_chose": False, "match": None}
    match = choices_match(
        {"category_id": body.category_id, "person_name": body.person_name},
        {"category_id": partner_choice["category_id"], "person_name": partner_choice["person_name"]},
    )
    return {"ok": True, "partner_chose": True, "match": match}


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
    return {"ok": True}


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
            "drive_link": r["drive_link"],
            "person_name": r["name_a"],
        })
    return list(grouped.values())


@app.post("/api/sync")
async def api_sync():
    try:
        return await run_sync()
    except Exception as e:
        raise HTTPException(500, f"sync mislukt: {e}")


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
    }
    filename = file_map.get(page.strip("/"))
    if not filename:
        raise HTTPException(404)
    return Response((APP_DIR / "static" / filename).read_text(), media_type="text/html")
