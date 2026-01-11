from flask import Flask, render_template, request, redirect, url_for, session, abort
import sqlite3
from datetime import datetime, timedelta
import os
import secrets
import base64
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "super_secreto_demo"
app.permanent_session_lifetime = timedelta(hours=8)

EMPRESA = "Altasolucion"
LOGO = "logo.png"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.db")

UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp"}


# -------------------------
# DB helpers
# -------------------------
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
        CREATE TABLE IF NOT EXISTS actividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            fecha TEXT,
            cliente TEXT,
            comentarios TEXT,
            proxima_visita TEXT,
            firma_archivo TEXT,
            FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS fotos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actividad_id INTEGER,
            archivo TEXT,
            FOREIGN KEY(actividad_id) REFERENCES actividades(id)
        )
    """)

    # Admin demo
    conn.execute("""
        INSERT OR IGNORE INTO usuarios
        (usuario, nombre, apellido, email, password, rol, activo, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "admin", "Admin", "Sistema", "admin@demo.com",
        generate_password_hash("admin123"),
        "admin", 1, datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    # Vendedor demo
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
        u = request.form.get("usuario", "").strip()
        p = request.form.get("password", "")

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
        rol=session.get("rol")
    )


# -------------------------
# Visitas
# -------------------------
@app.route("/visitas")
def visitas():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()

    if session.get("rol") == "admin":
        rows = conn.execute("""
            SELECT a.*, u.usuario
            FROM actividades a
            JOIN usuarios u ON u.id = a.usuario_id
            ORDER BY a.fecha DESC
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT a.*, u.usuario
            FROM actividades a
            JOIN usuarios u ON u.id = a.usuario_id
            WHERE a.usuario_id=?
            ORDER BY a.fecha DESC
        """, (session["user_id"],)).fetchall()

    # fotos por actividad
    fotos = conn.execute("""
        SELECT * FROM fotos
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    # agrupar fotos por actividad_id
    fotos_por_act = {}
    for f in fotos:
        fotos_por_act.setdefault(f["actividad_id"], []).append(f)

    return render_template(
        "visitas.html",
        empresa=EMPRESA,
        logo=LOGO,
        visitas=rows,
        fotos_por_act=fotos_por_act,
        rol=session.get("rol")
    )


def _allowed_file(filename: str) -> bool:
    if not filename:
        return False
    ext = filename.rsplit(".", 1)[-1].lower()
    return ext in ALLOWED_IMAGE_EXT


def _save_base64_signature(data_url: str) -> str:
    """
    data_url: "data:image/png;base64,AAAA..."
    returns relative path like "uploads/firma_xxx.png"
    """
    if not data_url or "base64," not in data_url:
        raise ValueError("Firma inválida")

    header, b64 = data_url.split("base64,", 1)
    if "image/png" not in header:
        # forzamos png desde canvas normalmente
        pass

    raw = base64.b64decode(b64)
    fname = f"firma_{secrets.token_hex(12)}.png"
    full = os.path.join(UPLOAD_FOLDER, fname)

    with open(full, "wb") as f:
        f.write(raw)

    return f"uploads/{fname}"


@app.route("/visitas/nueva", methods=["POST"])
def nueva_visita():
    if "user_id" not in session:
        return redirect(url_for("login"))

    cliente = (request.form.get("cliente") or "").strip()
    comentarios = (request.form.get("comentarios") or "").strip()
    proxima_visita = (request.form.get("proxima_visita") or "").strip()
    firma_data = request.form.get("firma_data")  # dataURL

    # Validaciones server-side (NO confiar en JS)
    if not cliente or not comentarios:
        return "Faltan campos obligatorios", 400

    files = request.files.getlist("fotos")
    valid_files = [f for f in files if f and f.filename]

    if len(valid_files) < 2:
        return "Debes subir mínimo 2 fotos", 400

    # Firma obligatoria
    if not firma_data:
        return "Firma obligatoria", 400

    # Guardar firma
    try:
        firma_archivo = _save_base64_signature(firma_data)
    except Exception:
        return "Firma inválida", 400

    conn = get_db()

    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")

    cur = conn.execute("""
        INSERT INTO actividades (usuario_id, fecha, cliente, comentarios, proxima_visita, firma_archivo)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        session["user_id"], fecha, cliente, comentarios, proxima_visita, firma_archivo
    ))

    actividad_id = cur.lastrowid

    # Guardar fotos
    for f in valid_files:
        filename = secure_filename(f.filename)
        if not _allowed_file(filename):
            conn.rollback()
            conn.close()
            return "Formato de foto no permitido", 400

        ext = filename.rsplit(".", 1)[-1].lower()
        new_name = f"actividad_{actividad_id}_{secrets.token_hex(8)}.{ext}"
        full_path = os.path.join(UPLOAD_FOLDER, new_name)
        f.save(full_path)

        conn.execute("""
            INSERT INTO fotos (actividad_id, archivo)
            VALUES (?, ?)
        """, (actividad_id, f"uploads/{new_name}"))

    conn.commit()
    conn.close()

    return redirect(url_for("visitas"))


# -------------------------
# Usuarios (si ya lo tienes en tu proyecto, déjalo como esté)
# NOTA: No lo toco aquí para no romper nada.
# -------------------------


# -------------------------
# Cambiar password (tu ruta ya existía, asegúrate que se llame así)
# -------------------------
@app.route("/cambiar-password", methods=["GET", "POST"])
def cambiar_password():
    if "user_id" not in session:
        return redirect(url_for("login"))

    msg = None
    error = None

    if request.method == "POST":
        actual = request.form.get("actual", "")
        nuevo = request.form.get("nuevo", "")
        confirmar = request.form.get("confirmar", "")

        if not nuevo or len(nuevo) < 6:
            error = "El nuevo password debe tener al menos 6 caracteres"
        elif nuevo != confirmar:
            error = "El nuevo password no coincide"
        else:
            conn = get_db()
            user = conn.execute(
                "SELECT * FROM usuarios WHERE id=?",
                (session["user_id"],)
            ).fetchone()

            if not user or not check_password_hash(user["password"], actual):
                error = "Password actual incorrecto"
            else:
                conn.execute("""
                    UPDATE usuarios
                    SET password=?
                    WHERE id=?
                """, (generate_password_hash(nuevo), session["user_id"]))
                conn.commit()
                msg = "Password actualizado correctamente"

            conn.close()

    return render_template(
        "cambiar_password.html",
        empresa=EMPRESA,
        logo=LOGO,
        mensaje=msg,
        error=error
    )


if __name__ == "__main__":
    app.run(debug=True)
