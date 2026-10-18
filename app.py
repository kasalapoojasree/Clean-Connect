"""
CleanConnect - AI-powered Community Cleanliness Management System
Flask + SQLite + Pillow/NumPy (AI module in models/waste_classifier.py)

Run:        python app.py
Demo data:  python app.py seed      (remove again with: python app.py unseed)
Admin:      python app.py reset-admin   (prints a new admin password)
"""
import os
import re
import sys
import uuid
import secrets
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from models.waste_classifier import WASTE_CLASSES, get_classifier

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
DB_PATH = os.path.join(INSTANCE_DIR, "database.db")
os.makedirs(INSTANCE_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

CATEGORIES = ["Garbage Dump", "Overflowing Bin", "Dirty Road", "Drainage Waste",
              "Plastic Waste", "Water Pollution", "Other"]
SEVERITIES = ["Low", "Medium", "High", "Critical"]
STATUSES = ["Submitted", "Under Review", "Assigned", "In Progress", "Resolved"]
INTERESTS = ["Cleanliness Drives", "Awareness Campaigns", "Waste Segregation",
             "Lake/Waterbody Cleaning", "Tree Plantation", "Community Education"]
AVAILABILITY = ["Weekdays", "Weekends", "Evenings", "Flexible"]
ALLOWED_EXT = {"jpg", "jpeg", "png"}
Image.MAX_IMAGE_PIXELS = 40_000_000


def load_secret_key():
    """Use SECRET_KEY from the environment, otherwise create one once and keep it."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(INSTANCE_DIR, "secret_key")
    if not os.path.exists(path):
        with open(path, "w") as fh:
            fh.write(secrets.token_hex(32))
    with open(path) as fh:
        return fh.read().strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=load_secret_key(),
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

# ----------------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    location TEXT NOT NULL,
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    location TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    incident_time TEXT,
    image_path TEXT,
    ai_category TEXT,
    ai_confidence REAL,
    ai_mode TEXT,
    status TEXT NOT NULL DEFAULT 'Submitted',
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS volunteers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL,
    area TEXT NOT NULL,
    interests TEXT NOT NULL,
    availability TEXT NOT NULL,
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    changed_by TEXT NOT NULL,
    changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
CREATE INDEX IF NOT EXISTS idx_history_report ON status_history(report_id);
"""


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def ensure_admin(db, force_new=False):
    """Create the default admin on first run. The password comes from the
    CLEANCONNECT_ADMIN_PASSWORD environment variable, or is generated randomly
    and written to instance/admin_credentials.txt (never shown in the website)."""
    if not force_new and db.execute("SELECT 1 FROM admins").fetchone():
        return
    username = os.environ.get("CLEANCONNECT_ADMIN_USER", "admin@cleanconnect.local")
    env_pw = os.environ.get("CLEANCONNECT_ADMIN_PASSWORD")
    # Never ship a predictable administrator password. If no password is
    # configured, generate one and write it to a local, git-ignored file.
    password = env_pw if env_pw else secrets.token_urlsafe(18)
    db.execute("DELETE FROM admins")
    db.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)",
               (username, generate_password_hash(password)))
    db.commit()
    if env_pw:
        print(f"[CleanConnect] Admin '{username}' created using CLEANCONNECT_ADMIN_PASSWORD.")
    else:
        credentials_path = os.path.join(INSTANCE_DIR, "admin_credentials.txt")
        with open(credentials_path, "w", encoding="utf-8") as fh:
            fh.write(f"username: {username}\npassword: {password}\n")
        try:
            os.chmod(credentials_path, 0o600)
        except OSError:
            pass
        print("=" * 60)
        print(" CleanConnect admin account created")
        print(f"   username: {username}")
        print(f"   password: {password}")
        print(" (also saved in instance/admin_credentials.txt - delete it after noting it)")
        print("=" * 60)


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    ensure_admin(conn)
    conn.close()


# ----------------------------------------------------------------------------
# Helpers: validation, security, templates
# ----------------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?\d[\d\s-]{6,14}$")


def field(name, maxlen=200):
    return (request.form.get(name) or "").strip()[:maxlen]


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.before_request
def protect_csrf():
    if request.method == "POST":
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        if not secrets.compare_digest(sent, session.get("_csrf", "")):
            abort(400)


def safe_next(default):
    nxt = request.values.get("next", "")
    if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
        return nxt
    return default


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "admin_id" not in session:
            flash("Administrator login required.", "warning")
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_globals():
    return dict(csrf_token=csrf_token, CATEGORIES=CATEGORIES, SEVERITIES=SEVERITIES,
                STATUSES=STATUSES, INTERESTS=INTERESTS, AVAILABILITY=AVAILABILITY,
                WASTE_CLASSES=WASTE_CLASSES,
                is_user="user_id" in session, is_admin="admin_id" in session,
                user_name=session.get("user_name"), year=datetime.now().year)


@app.template_filter("fdate")
def fdate(value, fmt="%d %b %Y, %I:%M %p"):
    if not value:
        return "-"
    try:
        return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S").strftime(fmt)
    except ValueError:
        return value


# ----------------------------------------------------------------------------
# Image handling + AI classification
# ----------------------------------------------------------------------------
def load_image(file_storage):
    """Validate an uploaded file and return it as an RGB Pillow image."""
    name = secure_filename(file_storage.filename or "")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED_EXT:
        raise ValueError("Only JPG, JPEG or PNG images are allowed.")
    try:
        probe = Image.open(file_storage.stream)
        probe.verify()
        file_storage.stream.seek(0)
        img = Image.open(file_storage.stream)
        if img.format not in ("JPEG", "PNG"):
            raise ValueError("Only JPG, JPEG or PNG images are allowed.")
        return ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise ValueError("That file is not a valid image.")


def save_image(img):
    """Re-encode the validated image (strips metadata) under a random file name."""
    img = img.copy()
    img.thumbnail((1600, 1600))
    filename = f"{uuid.uuid4().hex}.jpg"
    img.save(os.path.join(UPLOAD_DIR, filename), "JPEG", quality=88)
    return filename


@app.post("/api/classify")
def api_classify():
    """Live AI preview used by the report form (nothing is stored)."""
    if "user_id" not in session:
        return jsonify(error="Please log in first."), 401
    file = request.files.get("photo")
    if not file or not file.filename:
        return jsonify(error="No image received."), 400
    try:
        result = get_classifier().predict(load_image(file))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except FileNotFoundError as exc:
        return jsonify(error=str(exc)), 503
    return jsonify(result)


# ----------------------------------------------------------------------------
# Operational health + ML observability
# ----------------------------------------------------------------------------
@app.get("/api/health")
def api_health():
    """Non-sensitive health status for local smoke tests and deployment probes."""
    db_ok = False
    try:
        get_db().execute("SELECT 1").fetchone()
        db_ok = True
    except sqlite3.Error:
        pass
    model_status = "not_checked"
    try:
        get_classifier()
        model_status = "ready"
    except FileNotFoundError:
        model_status = "not_trained"
    except Exception:
        model_status = "load_error"
    healthy = db_ok and model_status == "ready"
    return jsonify(status="ok" if healthy else "degraded", database="ready" if db_ok else "error",
                   ml_model=model_status), (200 if healthy else 503)


@app.route("/admin/ml-insights")
@admin_required
def admin_ml_insights():
    """Show model evaluation metadata without exposing the serialized model."""
    model_dir = os.path.join(BASE_DIR, "models", "model")
    card_path = os.path.join(model_dir, "model_card.json")
    report_path = os.path.join(model_dir, "training_report.txt")
    model_card = None
    report_text = None
    try:
        import json
        with open(card_path, encoding="utf-8") as fh:
            model_card = json.load(fh)
    except (OSError, ValueError):
        pass
    try:
        with open(report_path, encoding="utf-8") as fh:
            report_text = fh.read()
    except OSError:
        pass
    try:
        classifier = get_classifier()
        model_ready = True
        runtime_error = None
    except Exception as exc:
        model_ready = False
        runtime_error = str(exc)
    return render_template("admin_ml_insights.html", model_card=model_card,
                           report_text=report_text, model_ready=model_ready,
                           runtime_error=runtime_error)


# ----------------------------------------------------------------------------
# Public pages
# ----------------------------------------------------------------------------
@app.route("/")
def index():
    db = get_db()
    stats = db.execute("""SELECT COUNT(*) AS total,
                          COALESCE(SUM(status = 'Resolved'), 0) AS resolved FROM reports""").fetchone()
    volunteers = db.execute("SELECT COUNT(*) FROM volunteers").fetchone()[0]
    return render_template("index.html", total=stats["total"], resolved=stats["resolved"],
                           volunteers=volunteers, classes=len(WASTE_CLASSES))


@app.route("/awareness")
def awareness():
    return render_template("awareness.html")


@app.route("/map")
def map_page():
    return render_template("map.html")


@app.route("/api/map-data")
def api_map_data():
    rows = get_db().execute(
        """SELECT complaint_id, user_id, title, category, severity, status, location, latitude,
                  longitude, created_at FROM reports
           WHERE latitude IS NOT NULL AND longitude IS NOT NULL ORDER BY id DESC LIMIT 1000"""
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["created_at"] = fdate(d["created_at"], "%d %b %Y")
        can_view = "admin_id" in session or session.get("user_id") == d["user_id"]
        d["url"] = url_for("report_details", complaint_id=d["complaint_id"]) if can_view else None
        del d["user_id"]
        out.append(d)
    return jsonify(out)


# ----------------------------------------------------------------------------
# Authentication (citizens)
# ----------------------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name, email = field("name", 80), field("email", 120).lower()
        phone, location = field("phone", 20), field("location", 120)
        password, confirm = request.form.get("password", ""), request.form.get("confirm_password", "")
        errors = []
        if len(name) < 2:
            errors.append("Please enter your full name.")
        if not EMAIL_RE.match(email):
            errors.append("Enter a valid email address.")
        if not PHONE_RE.match(phone):
            errors.append("Enter a valid phone number (7-15 digits).")
        if len(location) < 2:
            errors.append("Please enter your area/location.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        db = get_db()
        if not errors and db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            errors.append("An account with this email already exists. Try logging in.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("register.html", form=request.form), 400
        db.execute("""INSERT INTO users (name, email, phone, password_hash, location, created_at)
                      VALUES (?, ?, ?, ?, ?, ?)""",
                   (name, email, phone, generate_password_hash(password), location, now()))
        db.commit()
        flash("Account created. You can log in now.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email, password = field("email", 120).lower(), request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.permanent = True
            session["user_id"], session["user_name"] = user["id"], user["name"]
            flash(f"Welcome back, {user['name'].split()[0]}!", "success")
            return redirect(safe_next(url_for("dashboard")))
        flash("Incorrect email or password.", "danger")
        return render_template("login.html"), 401
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("user_name", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# ----------------------------------------------------------------------------
# Citizen: dashboard, report, tracking
# ----------------------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    db, uid = get_db(), session["user_id"]
    user = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    counts = db.execute("""SELECT COUNT(*) AS total,
        COALESCE(SUM(status IN ('Submitted','Under Review','Assigned')), 0) AS pending,
        COALESCE(SUM(status = 'In Progress'), 0) AS in_progress,
        COALESCE(SUM(status = 'Resolved'), 0) AS resolved FROM reports WHERE user_id = ?""", (uid,)).fetchone()
    volunteer = db.execute("SELECT * FROM volunteers WHERE user_id = ? OR email = ?",
                           (uid, user["email"])).fetchone()
    recent = db.execute("SELECT * FROM reports WHERE user_id = ? ORDER BY id DESC LIMIT 5", (uid,)).fetchall()
    return render_template("dashboard.html", user=user, counts=counts, volunteer=volunteer, recent=recent)


def parse_coord(raw, low, high):
    raw = (raw or "").strip()
    if not raw:
        return None
    value = float(raw)
    if not low <= value <= high:
        raise ValueError
    return value


@app.route("/report", methods=["GET", "POST"])
@login_required
def report():
    if request.method == "GET":
        return render_template("report.html", form={}, now_local=datetime.now().strftime("%Y-%m-%dT%H:%M"))

    title, description, location = field("title", 120), field("description", 2000), field("location", 200)
    category, severity = field("category", 40), field("severity", 20)
    errors = []
    if len(title) < 3:
        errors.append("Title must be at least 3 characters.")
    if len(description) < 10:
        errors.append("Please describe the problem in at least 10 characters.")
    if len(location) < 3:
        errors.append("Please enter the location.")
    if category not in CATEGORIES:
        errors.append("Choose a valid problem category.")
    if severity not in SEVERITIES:
        errors.append("Choose a valid severity.")
    try:
        lat = parse_coord(request.form.get("latitude"), -90, 90)
        lng = parse_coord(request.form.get("longitude"), -180, 180)
        if (lat is None) != (lng is None):
            errors.append("Provide both latitude and longitude, or leave both empty.")
    except ValueError:
        lat = lng = None
        errors.append("Latitude/longitude are not valid numbers.")
    incident = now()
    raw_time = field("incident_time", 30)
    if raw_time:
        try:
            parsed = datetime.strptime(raw_time, "%Y-%m-%dT%H:%M")
            if parsed > datetime.now() + timedelta(minutes=5):
                errors.append("The date/time cannot be in the future.")
            incident = parsed.strftime("%Y-%m-%d %H:%M:00")
        except ValueError:
            errors.append("Enter a valid date and time.")

    img = None
    photo = request.files.get("photo")
    if photo and photo.filename:
        try:
            img = load_image(photo)
        except ValueError as exc:
            errors.append(str(exc))

    if errors:
        for e in errors:
            flash(e, "danger")
        return render_template("report.html", form=request.form,
                               now_local=datetime.now().strftime("%Y-%m-%dT%H:%M")), 400

    image_path = ai = None
    if img is not None:
        try:
            ai = get_classifier().predict(img)
        except FileNotFoundError as exc:
            flash(str(exc), "danger")
            return render_template("report.html", form=request.form,
                                   now_local=datetime.now().strftime("%Y-%m-%dT%H:%M")), 503
        image_path = save_image(img)

    db, ts = get_db(), now()
    cur = db.execute(
        """INSERT INTO reports (complaint_id, user_id, title, description, category, severity, location,
               latitude, longitude, incident_time, image_path, ai_category, ai_confidence, ai_mode,
               status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Submitted', ?, ?)""",
        (uuid.uuid4().hex, session["user_id"], title, description, category, severity, location, lat, lng,
         incident, image_path, ai["label"] if ai else None, ai["confidence"] if ai else None,
         ai["mode"] if ai else None, ts, ts))
    rid = cur.lastrowid
    complaint_id = f"CC-{datetime.now().year}-{rid:04d}"
    db.execute("UPDATE reports SET complaint_id = ? WHERE id = ?", (complaint_id, rid))
    db.execute("INSERT INTO status_history (report_id, status, changed_by, changed_at) VALUES (?, 'Submitted', ?, ?)",
               (rid, f"user:{session['user_name']}", ts))
    db.commit()
    flash(f"Your complaint has been submitted successfully. Complaint ID: {complaint_id}", "success")
    return redirect(url_for("report_details", complaint_id=complaint_id))


def build_report_query(args, user_id=None, admin=False):
    sql = ("SELECT r.*, u.name AS user_name, u.email AS user_email FROM reports r "
           "JOIN users u ON u.id = r.user_id WHERE 1 = 1")
    params = []
    if user_id is not None:
        sql += " AND r.user_id = ?"
        params.append(user_id)
    q = (args.get("q") or "").strip()[:100]
    if q:
        cols = ["r.complaint_id", "r.title", "r.location", "r.category", "r.status", "r.severity"]
        if admin:
            cols.append("u.name")
        sql += " AND (" + " OR ".join(f"{c} LIKE ?" for c in cols) + ")"
        params += [f"%{q}%"] * len(cols)
    for key, col in (("status", "r.status"), ("category", "r.category"), ("severity", "r.severity")):
        val = (args.get(key) or "").strip()
        if val:
            sql += f" AND {col} = ?"
            params.append(val)
    return sql + " ORDER BY r.id DESC LIMIT 500", params


@app.route("/my-reports")
@login_required
def my_reports():
    sql, params = build_report_query(request.args, user_id=session["user_id"])
    rows = get_db().execute(sql, params).fetchall()
    return render_template("my_reports.html", reports=rows, args=request.args)


@app.route("/report/<complaint_id>")
def report_details(complaint_id):
    if "user_id" not in session and "admin_id" not in session:
        flash("Please log in to view complaint details.", "warning")
        return redirect(url_for("login", next=request.path))
    db = get_db()
    row = db.execute("""SELECT r.*, u.name AS user_name, u.email AS user_email, u.phone AS user_phone
                        FROM reports r JOIN users u ON u.id = r.user_id WHERE r.complaint_id = ?""",
                     (complaint_id,)).fetchone()
    if row is None or ("admin_id" not in session and row["user_id"] != session.get("user_id")):
        abort(404)
    history = db.execute("SELECT * FROM status_history WHERE report_id = ? ORDER BY id", (row["id"],)).fetchall()
    return render_template("report_details.html", r=row, history=history,
                           step=STATUSES.index(row["status"]))


# ----------------------------------------------------------------------------
# Volunteers
# ----------------------------------------------------------------------------
@app.route("/volunteer", methods=["GET", "POST"])
def volunteer():
    db = get_db()
    user = None
    if "user_id" in session:
        user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    if request.method == "POST":
        name, email = field("name", 80), field("email", 120).lower()
        phone, area = field("phone", 20), field("area", 120)
        availability = field("availability", 20)
        interests = [i for i in request.form.getlist("interests") if i in INTERESTS]
        errors = []
        if len(name) < 2:
            errors.append("Please enter your name.")
        if not EMAIL_RE.match(email):
            errors.append("Enter a valid email address.")
        if not PHONE_RE.match(phone):
            errors.append("Enter a valid phone number.")
        if len(area) < 2:
            errors.append("Please enter your area.")
        if not interests:
            errors.append("Select at least one activity you are interested in.")
        if availability not in AVAILABILITY:
            errors.append("Choose your availability.")
        if not errors and db.execute("SELECT 1 FROM volunteers WHERE email = ?", (email,)).fetchone():
            errors.append("This email is already registered as a volunteer.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("volunteer.html", user=user, form=request.form,
                                   form_interests=interests, done=None), 400
        db.execute("""INSERT INTO volunteers (user_id, name, email, phone, area, interests, availability, created_at)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                   (session.get("user_id"), name, email, phone, area, ", ".join(interests), availability, now()))
        db.commit()
        session["vol_done"] = name
        return redirect(url_for("volunteer"))
    done = session.pop("vol_done", None)
    existing = None
    if user:
        existing = db.execute("SELECT * FROM volunteers WHERE user_id = ? OR email = ?",
                              (user["id"], user["email"])).fetchone()
    return render_template("volunteer.html", user=user, form={}, form_interests=[], done=done, existing=existing)


# ----------------------------------------------------------------------------
# Admin
# ----------------------------------------------------------------------------
FAILED_LOGINS = {}  # ip -> list of timestamps (simple brute-force throttle)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        ip = request.remote_addr or "?"
        recent = [t for t in FAILED_LOGINS.get(ip, []) if t > datetime.now() - timedelta(minutes=5)]
        FAILED_LOGINS[ip] = recent
        if len(recent) >= 5:
            flash("Too many failed attempts. Try again in a few minutes.", "danger")
            return render_template("admin_login.html"), 429
        admin = get_db().execute("SELECT * FROM admins WHERE username = ?", (field("username", 60),)).fetchone()
        if admin and check_password_hash(admin["password_hash"], request.form.get("password", "")):
            session.permanent = True
            session["admin_id"], session["admin_name"] = admin["id"], admin["username"]
            FAILED_LOGINS.pop(ip, None)
            return redirect(url_for("admin_dashboard"))
        FAILED_LOGINS[ip].append(datetime.now())
        flash("Incorrect admin username or password.", "danger")
        return render_template("admin_login.html"), 401
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_id", None)
    session.pop("admin_name", None)
    flash("Administrator logged out.", "info")
    return redirect(url_for("index"))


def admin_stats(db):
    return db.execute("""SELECT COUNT(*) AS total,
        COALESCE(SUM(status IN ('Submitted','Under Review','Assigned')), 0) AS pending,
        COALESCE(SUM(status = 'In Progress'), 0) AS in_progress,
        COALESCE(SUM(status = 'Resolved'), 0) AS resolved,
        COALESCE(SUM(severity IN ('High','Critical') AND status != 'Resolved'), 0) AS high
        FROM reports""").fetchone()


@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    recent = db.execute("""SELECT r.*, u.name AS user_name FROM reports r JOIN users u ON u.id = r.user_id
                           ORDER BY r.id DESC LIMIT 8""").fetchall()
    volunteers = db.execute("SELECT COUNT(*) FROM volunteers").fetchone()[0]
    demo = db.execute("SELECT COUNT(*) FROM users WHERE is_demo = 1").fetchone()[0]
    return render_template("admin_dashboard.html", stats=admin_stats(db), volunteers=volunteers,
                           reports=recent, demo_loaded=bool(demo), next_url=url_for("admin_dashboard"))


@app.route("/admin/reports")
@admin_required
def admin_reports():
    sql, params = build_report_query(request.args, admin=True)
    rows = get_db().execute(sql, params).fetchall()
    return render_template("admin_reports.html", reports=rows, args=request.args,
                           next_url=request.full_path.rstrip("?"))


@app.post("/admin/reports/<int:rid>/status")
@admin_required
def admin_update_status(rid):
    db, new = get_db(), field("status", 20)
    row = db.execute("SELECT * FROM reports WHERE id = ?", (rid,)).fetchone()
    if row is None:
        abort(404)
    if new not in STATUSES:
        flash("Invalid status.", "danger")
    elif new != row["status"]:
        ts = now()
        db.execute("UPDATE reports SET status = ?, updated_at = ? WHERE id = ?", (new, ts, rid))
        db.execute("INSERT INTO status_history (report_id, status, changed_by, changed_at) VALUES (?, ?, ?, ?)",
                   (rid, new, f"admin:{session['admin_name']}", ts))
        db.commit()
        flash(f"{row['complaint_id']} updated to '{new}'.", "success")
    return redirect(safe_next(url_for("admin_reports")))


@app.post("/admin/reports/<int:rid>/delete")
@admin_required
def admin_delete_report(rid):
    db = get_db()
    row = db.execute("SELECT * FROM reports WHERE id = ?", (rid,)).fetchone()
    if row is None:
        abort(404)
    db.execute("DELETE FROM reports WHERE id = ?", (rid,))
    db.commit()
    if row["image_path"]:
        try:
            os.remove(os.path.join(UPLOAD_DIR, os.path.basename(row["image_path"])))
        except OSError:
            pass
    flash(f"Report {row['complaint_id']} deleted.", "info")
    nxt = safe_next(url_for("admin_reports"))
    return redirect(url_for("admin_reports") if "/report/" in nxt else nxt)


@app.route("/admin/volunteers")
@admin_required
def admin_volunteers():
    rows = get_db().execute("SELECT * FROM volunteers ORDER BY id DESC").fetchall()
    return render_template("admin_volunteers.html", volunteers=rows)


@app.post("/admin/volunteers/<int:vid>/delete")
@admin_required
def admin_delete_volunteer(vid):
    db = get_db()
    db.execute("DELETE FROM volunteers WHERE id = ?", (vid,))
    db.commit()
    flash("Volunteer removed.", "info")
    return redirect(url_for("admin_volunteers"))


@app.route("/analytics")
@admin_required
def analytics():
    return render_template("analytics.html", stats=admin_stats(get_db()))


@app.route("/api/analytics")
@admin_required
def api_analytics():
    db = get_db()
    categories = [dict(r) for r in db.execute(
        "SELECT category AS label, COUNT(*) AS n FROM reports GROUP BY category ORDER BY n DESC")]
    st = admin_stats(db)
    # last 12 months, including empty months
    today = datetime.now().replace(day=1)
    months = []
    for i in range(11, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y}-{m:02d}")
    by_month = {r["m"]: r["n"] for r in db.execute(
        "SELECT strftime('%Y-%m', created_at) AS m, COUNT(*) AS n FROM reports GROUP BY m")}
    sev = {r["severity"]: r["n"] for r in db.execute("SELECT severity, COUNT(*) AS n FROM reports GROUP BY severity")}
    interests = Counter()
    for r in db.execute("SELECT interests FROM volunteers"):
        interests.update(i.strip() for i in r["interests"].split(",") if i.strip())
    areas = [dict(r) for r in db.execute(
        """SELECT MIN(TRIM(location)) AS label, COUNT(*) AS n FROM reports
           GROUP BY LOWER(TRIM(location)) ORDER BY n DESC LIMIT 8""")]
    return jsonify(
        categories=categories,
        status={"Resolved": st["resolved"], "In Progress": st["in_progress"], "Pending": st["pending"]},
        months=[{"label": datetime.strptime(m, "%Y-%m").strftime("%b %Y"), "n": by_month.get(m, 0)} for m in months],
        severity=[{"label": s, "n": sev.get(s, 0)} for s in SEVERITIES],
        volunteers=[{"label": k, "n": interests.get(k, 0)} for k in INTERESTS],
        areas=areas)


# ----------------------------------------------------------------------------
# Demo data (clearly marked with is_demo = 1 so it can be removed)
# ----------------------------------------------------------------------------
DEMO_EMAIL = "demo.citizen@cleanconnect.demo"
DEMO_REPORTS = [
    # title, description, category, severity, location, lat, lng, ai label, conf, status, days ago
    ("Overflowing garbage bin near market", "The public bin has been overflowing for three days and waste is spreading onto the road.",
     "Overflowing Bin", "High", "Main Market Road", 16.5075, 80.6480, "Mixed Waste", 71.0, "Under Review", 2),
    ("Plastic waste near lake", "Plastic bottles and covers are floating along the lake edge.",
     "Plastic Waste", "Critical", "City Lake, East Bank", 16.5150, 80.6320, "Plastic", 82.0, "In Progress", 9),
    ("Dirty roadside near bus stand", "Food waste and leaves have piled up along the footpath near the bus stand.",
     "Dirty Road", "Medium", "Bus Stand Junction", 16.5190, 80.6190, "Organic", 64.0, "Assigned", 21),
    ("Mixed waste dump behind school", "An open dump of household and construction waste behind the school wall.",
     "Garbage Dump", "High", "Gandhi Nagar", 16.5000, 80.6560, "Mixed Waste", 68.0, "Resolved", 35),
    ("Drainage blocked with waste", "The roadside drain is clogged with plastic and silt and overflows when it rains.",
     "Drainage Waste", "Medium", "Gandhi Nagar", 16.4960, 80.6610, "Plastic", 58.0, "Submitted", 1),
]
DEMO_VOLUNTEERS = [
    ("Demo Volunteer One", "demo.vol1@cleanconnect.demo", "9000000001", "City Lake", "Lake/Waterbody Cleaning, Cleanliness Drives", "Weekends"),
    ("Demo Volunteer Two", "demo.vol2@cleanconnect.demo", "9000000002", "Gandhi Nagar", "Waste Segregation, Community Education", "Evenings"),
    ("Demo Volunteer Three", "demo.vol3@cleanconnect.demo", "9000000003", "Main Market", "Awareness Campaigns, Tree Plantation", "Flexible"),
]


def seed_demo(db):
    if db.execute("SELECT 1 FROM users WHERE email = ?", (DEMO_EMAIL,)).fetchone():
        return False
    ts = now()
    uid = db.execute(
        "INSERT INTO users (name, email, phone, password_hash, location, is_demo, created_at) VALUES (?,?,?,?,?,1,?)",
        ("Demo Citizen", DEMO_EMAIL, "9000000000", generate_password_hash("Demo@12345"), "Gandhi Nagar", ts)).lastrowid
    for t, d, c, s, loc, la, ln, ai, conf, st, days in DEMO_REPORTS:
        created = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        rid = db.execute(
            """INSERT INTO reports (complaint_id, user_id, title, description, category, severity, location, latitude,
                   longitude, incident_time, ai_category, ai_confidence, ai_mode, status, is_demo, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'sample',?,1,?,?)""",
            (uuid.uuid4().hex, uid, t, d, c, s, loc, la, ln, created, ai, conf, st, created, created)).lastrowid
        db.execute("UPDATE reports SET complaint_id = ? WHERE id = ?", (f"CC-{datetime.now().year}-{rid:04d}", rid))
        db.execute("INSERT INTO status_history (report_id, status, changed_by, changed_at) VALUES (?, 'Submitted', 'user:Demo Citizen', ?)",
                   (rid, created))
        for step in STATUSES[1:STATUSES.index(st) + 1]:
            db.execute("INSERT INTO status_history (report_id, status, changed_by, changed_at) VALUES (?,?,?,?)",
                       (rid, step, "admin:demo", created))
    for n, e, p, a, i, av in DEMO_VOLUNTEERS:
        db.execute("""INSERT INTO volunteers (name, email, phone, area, interests, availability, is_demo, created_at)
                      VALUES (?,?,?,?,?,?,1,?)""", (n, e, p, a, i, av, ts))
    db.commit()
    return True


def unseed_demo(db):
    db.execute("DELETE FROM volunteers WHERE is_demo = 1")
    db.execute("DELETE FROM users WHERE is_demo = 1")  # reports + history cascade
    db.commit()


@app.post("/admin/demo/<action>")
@admin_required
def admin_demo(action):
    db = get_db()
    if action == "load":
        flash("Demo data loaded." if seed_demo(db) else "Demo data is already loaded.", "success")
    elif action == "remove":
        unseed_demo(db)
        flash("Demo data removed.", "info")
    else:
        abort(404)
    return redirect(url_for("admin_dashboard"))


# ----------------------------------------------------------------------------
# Error pages
# ----------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(_e):
    return render_template("500.html"), 500


@app.errorhandler(400)
def bad_request(_e):
    return render_template("error.html", code=400, title="Form expired",
                           message="Your form could not be verified. Go back, refresh the page and try again."), 400


@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403, title="Not allowed",
                           message="You do not have permission to view this page."), 403


@app.errorhandler(413)
def too_large(_e):
    return render_template("error.html", code=413, title="File too large",
                           message="The upload is larger than the 6 MB limit. Choose a smaller photo."), 413


init_db()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "seed":
        conn = connect()
        print("Demo data loaded (demo login: demo.citizen@cleanconnect.demo / Demo@12345)."
              if seed_demo(conn) else "Demo data already present.")
        conn.close()
    elif cmd == "unseed":
        conn = connect()
        unseed_demo(conn)
        conn.close()
        print("Demo data removed.")
    elif cmd == "reset-admin":
        conn = connect()
        ensure_admin(conn, force_new=True)
        conn.close()
    else:
        app.run(host="127.0.0.1", port=5000, debug=os.environ.get("CLEANCONNECT_DEBUG", "0") == "1")
