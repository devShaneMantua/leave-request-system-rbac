from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "suggestion_box.db"

ROLE_PERMISSIONS = {
    "admin": {
        "suggestions": ["manage", "view"],
        "responses": ["manage", "reply", "view"],
        "users": ["manage"],
    },
    "student": {
        "suggestions": ["submit"],
        "responses": ["view"],
        "users": [],
    },
    "reviewer": {
        "suggestions": ["view"],
        "responses": ["reply"],
        "users": [],
    },
}


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'student', 'reviewer'))
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES users(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            suggestion_id INTEGER NOT NULL,
            reviewer_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(suggestion_id) REFERENCES suggestions(id),
            FOREIGN KEY(reviewer_id) REFERENCES users(id)
        )
        """
    )

    cur.execute("SELECT COUNT(*) AS total FROM users")
    total_users = cur.fetchone()["total"]

    if total_users == 0:
        seed_users = [
            ("admin", "poiuytrewq", "admin"),
            ("student", "poiuytrewq", "student"),
            ("reviewer", "poiuytrewq", "reviewer"),
        ]
        cur.executemany(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            seed_users,
        )

    conn.commit()
    conn.close()


def has_permission(role: str, module: str, action: str) -> bool:
    return action in ROLE_PERMISSIONS.get(role, {}).get(module, [])


def get_current_user(request: Request) -> Optional[sqlite3.Row]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return user


def ensure_logged_in(request: Request) -> sqlite3.Row:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Please log in.")
    return user


def ensure_permission(user: sqlite3.Row, module: str, action: str) -> None:
    if not has_permission(user["role"], module, action):
        raise HTTPException(status_code=403, detail="You do not have permission.")


def base_context(request: Request, title: str, **extra) -> dict:
    user = get_current_user(request)
    permissions = ROLE_PERMISSIONS.get(user["role"], {}) if user else {}
    context = {
        "request": request,
        "title": title,
        "current_user": user,
        "permissions": permissions,
    }
    context.update(extra)
    return context


app = FastAPI(title="Digital Suggestion Box")
app.add_middleware(SessionMiddleware, secret_key="simple-secret-key")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def get_role_destination(user) -> str:
    """Get the appropriate destination URL based on user role."""
    if user["role"] == "student":
        return "/suggestions/new"
    if user["role"] == "reviewer":
        return "/suggestions"
    return "/users"


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url=get_role_destination(user), status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        base_context(request, "Login", error=None),
    )


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username = ? AND password = ?",
        (username, password),
    ).fetchone()
    conn.close()

    if not user:
        return templates.TemplateResponse(
            "login.html",
            base_context(request, "Login", error="Invalid credentials."),
        )

    request.session["user_id"] = user["id"]
    return RedirectResponse(url=get_role_destination(user), status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/home")
def role_home(request: Request):
    user = ensure_logged_in(request)
    return RedirectResponse(url=get_role_destination(user), status_code=303)


@app.get("/dashboard")
def legacy_dashboard_redirect(request: Request):
    user = ensure_logged_in(request)
    return RedirectResponse(url=get_role_destination(user), status_code=303)


@app.get("/suggestions", response_class=HTMLResponse)
def list_suggestions(request: Request):
    user = ensure_logged_in(request)
    if has_permission(user["role"], "suggestions", "manage"):
        allowed = True
    else:
        allowed = has_permission(user["role"], "suggestions", "view")
    if not allowed:
        raise HTTPException(status_code=403, detail="Not allowed to view suggestions.")

    conn = get_db()
    suggestions = conn.execute(
        """
        SELECT s.id, s.content, s.created_at, u.username AS student_name,
               COUNT(r.id) AS response_count
        FROM suggestions s
        JOIN users u ON u.id = s.student_id
        LEFT JOIN responses r ON r.suggestion_id = s.id
        GROUP BY s.id
        ORDER BY s.id DESC
        """
    ).fetchall()
    conn.close()

    return templates.TemplateResponse(
        "suggestions.html",
        base_context(request, "Suggestions", suggestions=suggestions),
    )


@app.get("/suggestions/new", response_class=HTMLResponse)
def new_suggestion_page(request: Request):
    user = ensure_logged_in(request)
    ensure_permission(user, "suggestions", "submit")
    message = request.query_params.get("message")
    return templates.TemplateResponse(
        "new_suggestion.html",
        base_context(request, "Submit Suggestion", error=None, message=message),
    )


@app.post("/suggestions/new", response_class=HTMLResponse)
def create_suggestion(request: Request, content: str = Form(...)):
    user = ensure_logged_in(request)
    ensure_permission(user, "suggestions", "submit")

    if not content.strip():
        return templates.TemplateResponse(
            "new_suggestion.html",
            base_context(request, "Submit Suggestion", error="Suggestion is required."),
        )

    conn = get_db()
    conn.execute(
        "INSERT INTO suggestions (student_id, content, created_at) VALUES (?, ?, ?)",
        (user["id"], content.strip(), datetime.utcnow().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(
        url="/suggestions/new?message=Suggestion submitted successfully.", status_code=303
    )


@app.post("/suggestions/delete/{suggestion_id}")
def delete_suggestion(request: Request, suggestion_id: int):
    user = ensure_logged_in(request)
    ensure_permission(user, "suggestions", "manage")

    conn = get_db()
    conn.execute("DELETE FROM responses WHERE suggestion_id = ?", (suggestion_id,))
    conn.execute("DELETE FROM suggestions WHERE id = ?", (suggestion_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/suggestions", status_code=303)


@app.get("/responses", response_class=HTMLResponse)
def list_responses(request: Request):
    user = ensure_logged_in(request)
    conn = get_db()

    if has_permission(user["role"], "responses", "manage"):
        responses = conn.execute(
            """
            SELECT r.id, r.content, r.created_at,
                   s.id AS suggestion_id, s.content AS suggestion_content,
                   reviewer.username AS reviewer_name,
                   student.username AS student_name
            FROM responses r
            JOIN suggestions s ON s.id = r.suggestion_id
            JOIN users reviewer ON reviewer.id = r.reviewer_id
            JOIN users student ON student.id = s.student_id
            ORDER BY r.id DESC
            """
        ).fetchall()
    elif has_permission(user["role"], "responses", "view"):
        responses = conn.execute(
            """
            SELECT r.id, r.content, r.created_at,
                   s.id AS suggestion_id, s.content AS suggestion_content,
                   reviewer.username AS reviewer_name,
                   student.username AS student_name
            FROM responses r
            JOIN suggestions s ON s.id = r.suggestion_id
            JOIN users reviewer ON reviewer.id = r.reviewer_id
            JOIN users student ON student.id = s.student_id
            WHERE s.student_id = ?
            ORDER BY r.id DESC
            """,
            (user["id"],),
        ).fetchall()
    elif has_permission(user["role"], "responses", "reply"):
        responses = conn.execute(
            """
            SELECT r.id, r.content, r.created_at,
                   s.id AS suggestion_id, s.content AS suggestion_content,
                   reviewer.username AS reviewer_name,
                   student.username AS student_name
            FROM responses r
            JOIN suggestions s ON s.id = r.suggestion_id
            JOIN users reviewer ON reviewer.id = r.reviewer_id
            JOIN users student ON student.id = s.student_id
            WHERE r.reviewer_id = ?
            ORDER BY r.id DESC
            """,
            (user["id"],),
        ).fetchall()
    else:
        conn.close()
        raise HTTPException(status_code=403, detail="Not allowed to view responses.")

    conn.close()
    return templates.TemplateResponse(
        "responses.html",
        base_context(request, "Responses", responses=responses),
    )


@app.get("/responses/new/{suggestion_id}", response_class=HTMLResponse)
def new_response_page(request: Request, suggestion_id: int):
    user = ensure_logged_in(request)
    ensure_permission(user, "responses", "reply")

    conn = get_db()
    suggestion = conn.execute(
        """
        SELECT s.id, s.content, u.username AS student_name
        FROM suggestions s
        JOIN users u ON u.id = s.student_id
        WHERE s.id = ?
        """,
        (suggestion_id,),
    ).fetchone()
    conn.close()

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found.")

    return templates.TemplateResponse(
        "new_response.html",
        base_context(request, "Write Response", suggestion=suggestion, error=None),
    )


@app.post("/responses/new/{suggestion_id}")
def create_response(request: Request, suggestion_id: int, content: str = Form(...)):
    user = ensure_logged_in(request)
    ensure_permission(user, "responses", "reply")

    if not content.strip():
        conn = get_db()
        suggestion = conn.execute(
            """
            SELECT s.id, s.content, u.username AS student_name
            FROM suggestions s
            JOIN users u ON u.id = s.student_id
            WHERE s.id = ?
            """,
            (suggestion_id,),
        ).fetchone()
        conn.close()
        return templates.TemplateResponse(
            "new_response.html",
            base_context(request, "Write Response", suggestion=suggestion, error="Response is required."),
        )

    conn = get_db()
    exists = conn.execute("SELECT id FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    if not exists:
        conn.close()
        raise HTTPException(status_code=404, detail="Suggestion not found.")

    conn.execute(
        "INSERT INTO responses (suggestion_id, reviewer_id, content, created_at) VALUES (?, ?, ?, ?)",
        (
            suggestion_id,
            user["id"],
            content.strip(),
            datetime.utcnow().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/responses", status_code=303)


@app.post("/responses/delete/{response_id}")
def delete_response(request: Request, response_id: int):
    user = ensure_logged_in(request)
    ensure_permission(user, "responses", "manage")

    conn = get_db()
    conn.execute("DELETE FROM responses WHERE id = ?", (response_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/responses", status_code=303)


@app.get("/users", response_class=HTMLResponse)
def list_users(request: Request):
    user = ensure_logged_in(request)
    ensure_permission(user, "users", "manage")

    conn = get_db()
    users = conn.execute("SELECT id, username, role FROM users ORDER BY id").fetchall()
    conn.close()

    return templates.TemplateResponse(
        "users.html",
        base_context(request, "User Management", users=users, error=None),
    )


@app.post("/users/new", response_class=HTMLResponse)
def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
):
    user = ensure_logged_in(request)
    ensure_permission(user, "users", "manage")

    username = username.strip()
    password = password.strip()
    role = role.strip().lower()

    if not username or not password or role not in ROLE_PERMISSIONS:
        conn = get_db()
        users = conn.execute("SELECT id, username, role FROM users ORDER BY id").fetchall()
        conn.close()
        return templates.TemplateResponse(
            "users.html",
            base_context(
                request,
                "User Management",
                users=users,
                error="Valid username, password, and role are required.",
            ),
        )

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            (username, password, role),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        users = conn.execute("SELECT id, username, role FROM users ORDER BY id").fetchall()
        conn.close()
        return templates.TemplateResponse(
            "users.html",
            base_context(
                request,
                "User Management",
                users=users,
                error="Username already exists.",
            ),
        )

    conn.close()
    return RedirectResponse(url="/users", status_code=303)


@app.post("/users/delete/{user_id}")
def delete_user(request: Request, user_id: int):
    current_user = ensure_logged_in(request)
    ensure_permission(current_user, "users", "manage")

    if current_user["id"] == user_id:
        return RedirectResponse(url="/users", status_code=303)

    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/users", status_code=303)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401:
        return RedirectResponse(url="/login", status_code=303)

    if exc.status_code in (403, 404):
        title = "Access Error" if exc.status_code == 403 else "Not Found"
        return templates.TemplateResponse(
            "error.html",
            base_context(request, title, message=exc.detail),
            status_code=exc.status_code,
        )

    return templates.TemplateResponse(
        "error.html",
        base_context(request, "Error", message="An unexpected error happened."),
        status_code=exc.status_code,
    )
