from flask import (
    Flask, render_template, request, redirect,
    url_for, session, abort, flash
)
import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import os
import base64
import uuid

# -------------------------
# APP
# -------------------------
app = Flask(__name__)
app.secret_key = "super_secreto_demo"
app.permanent_session_lifetime = timedelta(hours=8)

EMPRESA = "Altasolucion"
LOGO = "logo.png"

# -------------------------
# DATABASE (PERSISTENTE)
# -------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.db")

UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT UNIQUE,
        nombre TEXT,
        apellido TEXT,
        email TEXT UNIQUE,
        password TEXT,
        rol TEXT,
        activo INTEGER,
        fecha_creacion TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS visitas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER,
        fecha TEXT,
        cliente TEXT,
        comentarios TEXT,
        proxima_visita TEXT,
        firma TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS fotos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        visita_id INTEGER,
        archivo TEXT
    )
    """)

    # ADMIN POR DEFECTO
    conn.execute("""
    INSERT OR IGNORE INTO usuarios
    (usuario, nombre, apellido, email, password, rol, activo, fecha_creacion)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "admin", "Admin", "Sistema", "admin@demo.com",
        generate_password_hash("admin123"),
        "admin", 1, datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    conn.commit()
    conn.close()

init_db()

# -------------------------
# CONTEXT
# -------------------------
@app.context_processor
def inject_now():
    return {"now": lambda: datetime.now().strftime("%Y-%m-%d %H:%M")}

# -------------------------
# AUTH
# -------------------------
@app.route("/")
def inicio():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
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
        conn.close()

        if user and check_password_hash(user["password"], p):
            session.permanent = True
            session["user_id"] = user["id"]
            session["usuario"] = user["usuario"]
            session["rol"] = user["rol"]
            return redirect(url_for("dashboard"))

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

    return render_template(
        "dashboard.html",
        empresa=EMPRESA,
        logo=LOGO,
        rol=session["rol"]
    )

# -------------------------
# USUARIOS (ADMIN)
# -------------------------
@app.route("/usuarios")
def usuarios():
    if session.get("rol") != "admin":
        abort(403)

    conn = get_db()
    usuarios = conn.execute("SELECT * FROM usuarios").fetchall()
    conn.close()

    return render_template(
        "usuarios.html",
        empresa=EMPRESA,
        logo=LOGO,
        usuarios=usuarios
    )

@app.route("/usuarios/crear", methods=["POST"])
def crear_usuario():
    if session.get("rol") != "admin":
        abort(403)

    conn = get_db()
    conn.execute("""
    INSERT INTO usuarios
    (usuario, nombre, apellido, email, password, rol, activo, fecha_creacion)
    VALUES (?, ?, ?, ?, ?, ?, 1, ?)
    """, (
        request.form["usuario"],
        request.form["nombre"],
        request.form["apellido"],
        request.form["email"],
        generate_password_hash(request.form["password"]),
        request.form["rol"],
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))
    conn.commit()
    conn.close()

    return redirect(url_for("usuarios"))

# -------------------------
# VISITAS
# -------------------------
@app.route("/visitas")
def visitas():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    visitas = conn.execute("""
        SELECT v.*, u.usuario
        FROM visitas v
        JOIN usuarios u ON u.id = v.usuario_id
        ORDER BY v.fecha DESC
    """).fetchall()
    conn.close()

    return render_template(
        "visitas.html",
        empresa=EMPRESA,
        logo=LOGO,
        visitas=visitas
    )

@app.route("/visitas/nueva", methods=["POST"])
def nueva_visita():
    if "user_id" not in session:
        abort(403)

    fotos = request.files.getlist("fotos[]")
    firma = request.form.get("firma")

    if not firma or len(fotos) < 2:
        flash("Debes subir mínimo 2 fotos y firmar", "danger")
        return redirect(url_for("visitas"))

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO visitas
    (usuario_id, fecha, cliente, comentarios, proxima_visita, firma)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        session["user_id"],
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        request.form["cliente"],
        request.form["comentarios"],
        request.form["proxima_visita"],
        firma
    ))

    visita_id = cur.lastrowid

    for f in fotos:
        filename = f"{uuid.uuid4().hex}_{f.filename}"
        path = os.path.join(UPLOAD_FOLDER, filename)
        f.save(path)

        cur.execute(
            "INSERT INTO fotos (visita_id, archivo) VALUES (?, ?)",
            (visita_id, filename)
        )

    conn.commit()
    conn.close()

    return redirect(url_for("visitas"))

