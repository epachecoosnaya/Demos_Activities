from flask import Flask, render_template, request, redirect, url_for, session, abort
import sqlite3
from datetime import datetime, timedelta
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "super_secreto_demo"
app.permanent_session_lifetime = timedelta(hours=8)

EMPRESA = "Altasolucion"
LOGO = "logo.png"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "actividades")
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
            email TEXT,
            password TEXT,
            rol TEXT,
            activo INTEGER,
            fecha_creacion TEXT
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

    conn.execute("""
        INSERT OR IGNORE INTO usuarios
        (usuario, email, password, rol, activo, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("demo", "demo@demo.com", "1234", "vendedor", 1, datetime.now().strftime("%Y-%m-%d %H:%M")))

    conn.execute("""
        INSERT OR IGNORE INTO usuarios
        (usuario, email, password, rol, activo, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("admin", "admin@demo.com", "admin123", "admin", 1, datetime.now().strftime("%Y-%m-%d %H:%M")))

    conn.commit()


init_db()


@app.context_processor
def inject_now():
    return {"now": lambda: datetime.now().strftime("%Y-%m-%d %H:%M")}


# -------------------------
# Auth
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
        user = conn.execute("""
            SELECT * FROM usuarios
            WHERE usuario=? AND password=? AND activo=1
        """, (u, p)).fetchone()

        if user:
            session.permanent = True
            session["user_id"] = user["id"]
            session["usuario"] = user["usuario"]
            session["rol"] = user["rol"]
            session["login_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            return redirect(url_for("dashboard"))
        else:
            error = "Credenciales incorrectas"

    return render_template("login.html", empresa=EMPRESA, logo=LOGO, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------------
# Dashboard
# -------------------------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template(
        "dashboard.html",
        empresa=EMPRESA,
        logo=LOGO,
        rol=session["rol"],
        login_time=session["login_time"]
    )


# -------------------------
# Visitas
# -------------------------
@app.route("/visitas")
def visitas():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    if session["rol"] == "admin":
        actividades = conn.execute("""
            SELECT a.*, u.usuario
            FROM actividades a
            JOIN usuarios u ON u.id = a.usuario_id
            ORDER BY fecha DESC
        """).fetchall()
    else:
        actividades = conn.execute("""
            SELECT *
            FROM actividades
            WHERE usuario_id=?
            ORDER BY fecha DESC
        """, (session["user_id"],)).fetchall()

    fotos = conn.execute("SELECT * FROM fotos").fetchall()

    return render_template(
        "visitas.html",
        empresa=EMPRESA,
        logo=LOGO,
        actividades=actividades,
        fotos=fotos,
        rol=session["rol"]
    )


@app.route("/actividad/nueva", methods=["POST"])
def nueva_actividad():
    if "user_id" not in session:
        return redirect(url_for("login"))

    archivos = request.files.getlist("fotos")
    if len(archivos) < 2:
        abort(400, "Debe subir mínimo 2 fotos")

    conn = get_db()
    cur = conn.execute("""
        INSERT INTO actividades
        (usuario_id, fecha, cliente, comentarios, proxima_visita)
        VALUES (?, ?, ?, ?, ?)
    """, (
        session["user_id"],
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        request.form["cliente"],
        request.form["comentarios"],
        request.form.get("proxima_visita")
    ))

    actividad_id = cur.lastrowid
    carpeta = os.path.join(UPLOAD_FOLDER, f"actividad_{actividad_id}")
    os.makedirs(carpeta, exist_ok=True)

    for f in archivos:
        nombre = secure_filename(f.filename)
        ruta = os.path.join(carpeta, nombre)
        f.save(ruta)
        conn.execute(
            "INSERT INTO fotos (actividad_id, archivo) VALUES (?, ?)",
            (actividad_id, f"uploads/actividades/actividad_{actividad_id}/{nombre}")
        )

    conn.commit()
    return redirect(url_for("visitas"))


if __name__ == "__main__":
    app.run(debug=True)
