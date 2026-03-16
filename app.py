from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import sqlite3
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "leave_requests.db"

# School demo salt. I know na dapat mo gamit og env sa real deployments
PASSWORD_SALT = "school-demo-static-salt"

ROLE_PERMISSIONS: dict[str, dict[str, list[str]]] = {
    "employee": {"leave": ["submit", "view_own"]},
    "supervisor": {"leave": ["view_all", "decide"]},
    "admin": {
        "leave": ["view_all", "manage"],
        "users": ["manage"],
        "reports": ["view"],
    },
}


def hash_password(password: str) -> str:
    import hashlib

    return hashlib.sha256((PASSWORD_SALT + password).encode("utf-8")).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed


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
            full_name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('employee', 'supervisor', 'admin')),
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1))
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('Pending', 'Approved', 'Rejected')) DEFAULT 'Pending',
            decided_by INTEGER,
            decided_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(employee_id) REFERENCES users(id),
            FOREIGN KEY(decided_by) REFERENCES users(id)
        )
        """
    )

    cur.execute("SELECT COUNT(*) AS total FROM users")
    if cur.fetchone()["total"] == 0:
        seed = [
            ("Admin User", "admin", "poiuytrewq", "admin", 1),
            ("Supervisor User", "supervisor", "poiuytrewq", "supervisor", 1),
            ("Employee User", "employee", "poiuytrewq", "employee", 1),
        ]
        cur.executemany(
            "INSERT INTO users (full_name, username, password, role, active) VALUES (?, ?, ?, ?, ?)",
            [(n, u, hash_password(p), r, a) for (n, u, p, r, a) in seed],
        )

    conn.commit()
    conn.close()


def has_permission(role: str, module: str, action: str) -> bool:
    return action in ROLE_PERMISSIONS.get(role, {}).get(module, [])


def get_current_user(request: Request) -> Optional[sqlite3.Row]:
    uid = request.session.get("user_id")
    if not uid:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    if not user:
        return None
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
    ctx = {"request": request, "title": title, "current_user": user, "permissions": permissions}
    ctx.update(extra)
    return ctx


app = FastAPI(title="Company Leave Request System")
app.add_middleware(SessionMiddleware, secret_key="simple-secret-key")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def get_role_destination(user: sqlite3.Row) -> str:
    if user["role"] == "employee":
        return "/leave/mine"
    if user["role"] == "supervisor":
        return "/leave"
    return "/users"


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url=get_role_destination(user), status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", base_context(request, "Login", error=None))


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()

    if not user or not verify_password(password, user["password"]):
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


@app.get("/leave/new", response_class=HTMLResponse)
def new_leave_page(request: Request):
    user = ensure_logged_in(request)
    ensure_permission(user, "leave", "submit")
    return templates.TemplateResponse(
        "leave_new.html",
        base_context(request, "New Leave Request", error=None, message=request.query_params.get("message")),
    )


@app.post("/leave/new", response_class=HTMLResponse)
def create_leave(
    request: Request,
    start_date: str = Form(...),
    end_date: str = Form(...),
    reason: str = Form(...),
):
    user = ensure_logged_in(request)
    ensure_permission(user, "leave", "submit")

    reason = reason.strip()
    if not reason:
        return templates.TemplateResponse(
            "leave_new.html",
            base_context(request, "New Leave Request", error="Reason is required.", message=None),
        )

    try:
        sd = date.fromisoformat(start_date)
        ed = date.fromisoformat(end_date)
    except ValueError:
        return templates.TemplateResponse(
            "leave_new.html",
            base_context(request, "New Leave Request", error="Invalid date format.", message=None),
        )
    if ed < sd:
        return templates.TemplateResponse(
            "leave_new.html",
            base_context(request, "New Leave Request", error="End date must be after start date.", message=None),
        )

    conn = get_db()
    conn.execute(
        """
        INSERT INTO leave_requests (employee_id, start_date, end_date, reason, status, created_at)
        VALUES (?, ?, ?, ?, 'Pending', ?)
        """,
        (user["id"], sd.isoformat(), ed.isoformat(), reason, datetime.utcnow().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/leave/new?message=Request submitted.", status_code=303)


@app.get("/leave/mine", response_class=HTMLResponse)
def my_leave_requests(request: Request):
    user = ensure_logged_in(request)
    ensure_permission(user, "leave", "view_own")

    conn = get_db()
    raw_items = conn.execute(
        """
        SELECT id, start_date, end_date, reason, status, created_at
        FROM leave_requests
        WHERE employee_id = ?
        ORDER BY id DESC
        """,
        (user["id"],),
    ).fetchall()
    conn.close()

    items = []
    for r in raw_items:
        created_at = r["created_at"]
        try:
            dt = datetime.fromisoformat(created_at)
            created_at_display = dt.strftime("%b %d, %Y %I:%M %p")
        except Exception:
            created_at_display = created_at
        items.append({**dict(r), "created_at_display": created_at_display})

    return templates.TemplateResponse(
        "leave_mine.html",
        base_context(request, "My Leave Requests", items=items),
    )


@app.get("/leave", response_class=HTMLResponse)
def all_leave_requests(request: Request):
    user = ensure_logged_in(request)
    ensure_permission(user, "leave", "view_all")

    conn = get_db()
    raw_items = conn.execute(
        """
        SELECT lr.id, lr.start_date, lr.end_date, lr.reason, lr.status, lr.created_at,
               u.full_name AS employee_name
        FROM leave_requests lr
        JOIN users u ON u.id = lr.employee_id
        ORDER BY lr.id DESC
        """
    ).fetchall()
    conn.close()

    items = []
    for r in raw_items:
        created_at = r["created_at"]
        try:
            dt = datetime.fromisoformat(created_at)
            created_at_display = dt.strftime("%b %d, %Y %I:%M %p")
        except Exception:
            created_at_display = created_at
        items.append({**dict(r), "created_at_display": created_at_display})

    return templates.TemplateResponse(
        "leave_all.html",
        base_context(request, "All Leave Requests", items=items),
    )


@app.post("/leave/{request_id}/decide", response_class=HTMLResponse)
def decide_leave(request: Request, request_id: int, decision: str = Form(...)):
    user = ensure_logged_in(request)
    ensure_permission(user, "leave", "decide")

    decision = decision.strip().capitalize()
    if decision not in ("Pending", "Approved", "Rejected"):
        return RedirectResponse(url="/leave", status_code=303)

    conn = get_db()
    exists = conn.execute("SELECT id FROM leave_requests WHERE id = ?", (request_id,)).fetchone()
    if not exists:
        conn.close()
        raise HTTPException(status_code=404, detail="Leave request not found.")

    conn.execute(
        """
        UPDATE leave_requests
        SET status = ?, decided_by = ?, decided_at = ?
        WHERE id = ?
        """,
        (decision, user["id"], datetime.utcnow().isoformat(timespec="seconds"), request_id),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url="/leave", status_code=303)


@app.get("/users", response_class=HTMLResponse)
def list_users(request: Request):
    user = ensure_logged_in(request)
    ensure_permission(user, "users", "manage")

    conn = get_db()
    # Hide admin account from the management table
    users = conn.execute(
        "SELECT id, full_name, username, role FROM users WHERE role != 'admin' ORDER BY id"
    ).fetchall()
    conn.close()
    return templates.TemplateResponse(
        "users.html",
        base_context(
            request,
            "User Management",
            users=users,
            error=request.query_params.get("error"),
        ),
    )


@app.post("/users/new", response_class=HTMLResponse)
def create_user(
    request: Request,
    full_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
):
    user = ensure_logged_in(request)
    ensure_permission(user, "users", "manage")

    full_name = full_name.strip()
    username = username.strip()
    password = password.strip()
    role = role.strip().lower()

    # admin accounts are seeded
    if role == "admin":
        conn = get_db()
        users = conn.execute("SELECT id, full_name, username, role FROM users ORDER BY id").fetchall()
        conn.close()
        return templates.TemplateResponse(
            "users.html",
            base_context(request, "User Management", users=users, error="Only one Admin account is allowed."),
        )

    if not full_name or not username or not password or role not in ROLE_PERMISSIONS:
        conn = get_db()
        users = conn.execute("SELECT id, full_name, username, role FROM users ORDER BY id").fetchall()
        conn.close()
        return templates.TemplateResponse(
            "users.html",
            base_context(
                request,
                "User Management",
                users=users,
                error="Valid name, username, password, and role are required.",
            ),
        )

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (full_name, username, password, role, active) VALUES (?, ?, ?, ?, 1)",
            (full_name, username, hash_password(password), role),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        users = conn.execute("SELECT id, full_name, username, role FROM users ORDER BY id").fetchall()
        conn.close()
        return templates.TemplateResponse(
            "users.html",
            base_context(request, "User Management", users=users, error="Username already exists."),
        )
    conn.close()
    return RedirectResponse(url="/users", status_code=303)


@app.post("/users/update/{user_id}", response_class=HTMLResponse)
def update_user(
    request: Request,
    user_id: int,
    full_name: str = Form(...),
    username: str = Form(""),
    role: str = Form(...),
    password: str = Form(""),
):
    current_user = ensure_logged_in(request)
    ensure_permission(current_user, "users", "manage")

    full_name = full_name.strip()
    username = username.strip()
    role = role.strip().lower()
    password = password.strip()

    if not full_name or role not in ROLE_PERMISSIONS:
        return RedirectResponse(url="/users", status_code=303)

    if current_user["role"] == "admin" and user_id == current_user["id"]:
        return RedirectResponse(url="/account", status_code=303)

    # Prevent role changes to admin through this endpoint
    if role == "admin":
        return RedirectResponse(url="/users", status_code=303)

    conn = get_db()
    try:
        if password:
            conn.execute(
                "UPDATE users SET full_name = ?, role = ?, password = ? WHERE id = ?",
                (full_name, role, hash_password(password), user_id),
            )
        else:
            conn.execute("UPDATE users SET full_name = ?, role = ? WHERE id = ?", (full_name, role, user_id))

        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return RedirectResponse(url="/users?error=Username+already+exists.", status_code=303)

    conn.close()
    if current_user["id"] == user_id:
        return RedirectResponse(url="/users", status_code=303)
    return RedirectResponse(url="/users", status_code=303)


@app.get("/account", response_class=HTMLResponse)
def account_settings(request: Request):
    user = ensure_logged_in(request)
    return templates.TemplateResponse(
        "account.html",
        base_context(
            request,
            "Account Settings",
            error=request.query_params.get("error"),
            message=request.query_params.get("message"),
        ),
    )


@app.post("/account", response_class=HTMLResponse)
def update_account(
    request: Request,
    full_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(""),
):
    user = ensure_logged_in(request)
    full_name = full_name.strip()
    username = username.strip()
    password = password.strip()

    if not full_name or not username:
        return RedirectResponse(url="/account?error=Name+and+username+are+required.", status_code=303)

    conn = get_db()
    try:
        if password:
            conn.execute(
                "UPDATE users SET full_name = ?, username = ?, password = ? WHERE id = ?",
                (full_name, username, hash_password(password), user["id"]),
            )
        else:
            conn.execute(
                "UPDATE users SET full_name = ?, username = ? WHERE id = ?",
                (full_name, username, user["id"]),
            )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return RedirectResponse(url="/account?error=Username+already+exists.", status_code=303)

    conn.close()
    return RedirectResponse(url="/account?message=Updated+successfully.", status_code=303)


@app.post("/users/delete/{user_id}", response_class=HTMLResponse)
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



@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    user = ensure_logged_in(request)
    ensure_permission(user, "reports", "view")

    conn = get_db()
    total = conn.execute("SELECT COUNT(*) AS c FROM leave_requests").fetchone()["c"]
    pending = conn.execute("SELECT COUNT(*) AS c FROM leave_requests WHERE status = 'Pending'").fetchone()["c"]
    approved = conn.execute("SELECT COUNT(*) AS c FROM leave_requests WHERE status = 'Approved'").fetchone()["c"]
    rejected = conn.execute("SELECT COUNT(*) AS c FROM leave_requests WHERE status = 'Rejected'").fetchone()["c"]
    conn.close()
    return templates.TemplateResponse(
        "reports.html",
        base_context(request, "Reports", total=total, pending=pending, approved=approved, rejected=rejected),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401:
        return RedirectResponse(url="/login", status_code=303)

    title = "Access Error" if exc.status_code == 403 else "Not Found" if exc.status_code == 404 else "Error"
    return templates.TemplateResponse(
        "error.html",
        base_context(request, title, message=exc.detail),
        status_code=exc.status_code,
    )

