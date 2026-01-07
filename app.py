from flask import Flask, render_template, request, redirect, url_for, session, abort
import sqlite3, os
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "super_secreto_demo"
app.permanent_session_lifetime = timedelta(hours=8)

EMPRESA = "Altasolucion"
LOGO = "logo.png"

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DB = ":memory:"
db_conn = None

# -------------------------
# DB
# -------------------------
def get_db():
    global db_conn
    if db_conn is None:
        db_conn = sqlite3.connect(DB, check_same_thread=False)
        db_conn.row_factory = sqlite3.Row
    return db_conn

def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE,
            nombre TEXT,
            apellido TEXT,
            email TEXT,
            password TEXT,
            rol TEXT,
            activo INTEGER
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS actividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            fecha TEXT,
            cliente TEXT,
            comentarios TEXT,
            proxima_visita TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS fotos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actividad_id INTEGER,
            archivo TEXT
        )
    """)

    # Admin
    conn.execute("""
        INSERT OR IGNORE INTO usuarios
        (usuario, nombre, apellido, email, password, rol, activo)
        VALUES (?, ?, ?, ?, ?, ?, 1)
    """, (
        "admin", "Admin", "Sistema", "admin@demo.com",
        generate_password_hash("admin123"), "admin"
    ))

    # Demo
    conn.execute("""
        INSERT OR IGNORE INTO usuarios
        (usuario, nombre, apellido, email, password, rol, activo)
        VALUES (?, ?, ?, ?, ?, ?, 1)
    """, (
        "demo", "Demo", "Vendedor", "demo@demo.com",
        generate_password_hash("1234"), "vendedor"
    ))

    conn.commit()

init_db()

# -------------------------
# CONTEXT
# -------------------------
@app.context_processor
def inject_now():
    return {"now": lambda: datetime.now().strftime("%Y-%m-%d %H:%M")}

# -------------------------
# LOGIN
# -------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form["usuario"]
        p = request.form["password"]

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM usuarios WHERE usuario=? AND activo=1",
            (u,)
        ).fetchone()

        if user and check_password_hash(user["password"], p):
            session.permanent = True
            session["user_id"] = user["id"]
            session["usuario"] = user["usuario"]
            session["rol"] = user["rol"]
            return redirect(url_for("dashboard"))
        else:
            error = "Credenciales incorrectas"

    return render_template("login.html", empresa=EMPRESA, logo=LOGO, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -------------------------
# DASHBOARD
# -------------------------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html", empresa=EMPRESA, logo=LOGO, rol=session["rol"])

# -------------------------
# VISITAS
# -------------------------
@app.route("/visitas")
def visitas():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    visitas = conn.execute("""
        SELECT * FROM actividades
        WHERE usuario_id=?
        ORDER BY fecha DESC
    """, (session["user_id"],)).fetchall()

    return render_template("visitas.html", visitas=visitas, empresa=EMPRESA, logo=LOGO)

@app.route("/visitas/nueva", methods=["POST"])
def nueva_visita():
    if "user_id" not in session:
        abort(403)

    fotos = request.files.getlist("fotos")
    if len(fotos) < 2:
        return "Debes subir mínimo 2 fotos", 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO actividades (usuario_id, fecha, cliente, comentarios, proxima_visita)
        VALUES (?, ?, ?, ?, ?)
    """, (
        session["user_id"],
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        request.form["cliente"],
        request.form["comentarios"],
        request.form["proxima_visita"]
    ))

    actividad_id = cur.lastrowid
    carpeta = f"{UPLOAD_FOLDER}/actividad_{actividad_id}"
    os.makedirs(carpeta, exist_ok=True)

    for f in fotos:
        filename = secure_filename(f.filename)
        ruta = f"{carpeta}/{filename}"
        f.save(ruta)
        cur.execute("""
            INSERT INTO fotos (actividad_id, archivo)
            VALUES (?, ?)
        """, (actividad_id, ruta))

    conn.commit()
    return redirect(url_for("visitas"))

# -------------------------
# CAMBIAR PASSWORD
# -------------------------
@app.route("/cambiar-password", methods=["GET"])
def cambiar_password():
    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template(
        "cambiar_password.html",
        empresa=EMPRESA,
        logo=LOGO
    )

