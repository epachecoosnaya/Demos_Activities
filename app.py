from flask import Flask, render_template, request, redirect, url_for, session, abort, flash
import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import os, base64, uuid

# -------------------------
# APP CONFIG
# -------------------------
app = Flask(__name__)
app.secret_key = "super_secreto_demo"
app.permanent_session_lifetime = timedelta(hours=8)

EMPRESA = "Altasolucion"
LOGO = "logo.png"

BASE_DIR = app.root_path
DB = os.path.join(BASE_DIR, "data.db")

UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
FIRMAS_FOLDER = os.path.join(BASE_DIR, "static", "firmas")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(FIRMAS_FOLDER, exist_ok=True)

# -------------------------
# DB
# -------------------------
def get_db():
    conn = sqlite3.connect(DB)
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

    # ADMIN
    conn.execute("""
    INSERT OR IGNORE INTO usuarios
    (usuario, nombre, apellido, email, password, rol, activo, fecha_creacion)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "admin", "Admin", "Sistema", "admin@demo.com",
        generate_password_hash("admin123"),
        "admin", 1, datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    # DEMO
    conn.execute("""
    INSERT OR IGNORE INTO usuarios
    (usuario, nombre, apellido, email, password, rol, activo, fecha_creacion)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "demo", "Demo", "Vendedor", "demo@demo.com",
        generate_password_hash("1234"),
        "vendedor", 1, datetime.now().strftime("%Y-%m-%d %H:%M")
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

# -------------------------
# GUARDAR VISITA
# -------------------------
@app.route("/visitas/guardar", methods=["POST"])
def guardar_visita():
    if "user_id" not in session:
        abort(403)

    fotos = request.files.getlist("fotos")
    firma_data = request.form.get("firma")

    if len(fotos) < 2:
        flash("Debes subir al menos 2 fotos", "danger")
        return redirect(url_for("visitas"))

    if not firma_data:
        flash("La firma es obligatoria", "danger")
        return redirect(url_for("visitas"))

    # Guardar firma
    firma_b64 = firma_data.split(",")[1]
    firma_bytes = base64.b64decode(firma_b64)
    firma_nombre = f"{uuid.uuid4()}.png"
    firma_path = os.path.join(FIRMAS_FOLDER, firma_nombre)

    with open(firma_path, "wb") as f:
        f.write(firma_bytes)

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
        firma_nombre
    ))

    visita_id = cur.lastrowid

    for foto in fotos:
        nombre = f"{uuid.uuid4()}_{foto.filename}"
        ruta = os.path.join(UPLOAD_FOLDER, nombre)
        foto.save(ruta)

        cur.execute("""
        INSERT INTO fotos (visita_id, archivo)
        VALUES (?, ?)
        """, (visita_id, nombre))

    conn.commit()
    conn.close()

    flash("Visita registrada correctamente", "success")
    return redirect(url_for("visitas"))

# -------------------------
if __name__ == "__main__":
    app.run(debug=True)
