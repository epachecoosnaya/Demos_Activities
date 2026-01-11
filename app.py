from flask import Flask, render_template, request, redirect, url_for, session, abort, flash
import sqlite3, os, base64, uuid
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "super_secreto_demo"
app.permanent_session_lifetime = timedelta(hours=8)

EMPRESA = "Altasolucion"
LOGO = "logo.png"

DB = ":memory:"
db_conn = None

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}


# -------------------------
# DB
# -------------------------
def get_db():
    global db_conn
    if db_conn is None:
        db_conn = sqlite3.connect(DB, check_same_thread=False)
        db_conn.row_factory = sqlite3.Row
    return db_conn


def column_exists(conn, table, column):
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c["name"] == column for c in cols)


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

    # Migración segura: agregar firma_archivo si no existe
    if not column_exists(conn, "actividades", "firma_archivo"):
        conn.execute("ALTER TABLE actividades ADD COLUMN firma_archivo TEXT")

    # Admin
    conn.execute("""
        INSERT OR IGNORE INTO usuarios
        (usuario, nombre, apellido, email, password, rol, activo)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        "admin", "Admin", "Sistema", "admin@demo.com",
        generate_password_hash("admin123"),
        "admin", 1
    ))

    # Demo vendedor
    conn.execute("""
        INSERT OR IGNORE INTO usuarios
        (usuario, nombre, apellido, email, password, rol, activo)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        "demo", "Demo", "Vendedor", "demo@demo.com",
        generate_password_hash("1234"),
        "vendedor", 1
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
# LOGIN / LOGOUT
# -------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        u = request.form.get("usuario", "").strip()
        p = request.form.get("password", "").strip()

        conn = get_db()
        user = conn.execute("""
            SELECT * FROM usuarios WHERE usuario=? AND activo=1
        """, (u,)).fetchone()

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
# VISITAS (LISTA)
# -------------------------
@app.route("/visitas")
def visitas():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()

    if session.get("rol") == "admin":
        actividades = conn.execute("""
            SELECT a.*, u.usuario
            FROM actividades a
            JOIN usuarios u ON u.id = a.usuario_id
            ORDER BY a.id DESC
        """).fetchall()
    else:
        actividades = conn.execute("""
            SELECT a.*, u.usuario
            FROM actividades a
            JOIN usuarios u ON u.id = a.usuario_id
            WHERE a.usuario_id=?
            ORDER BY a.id DESC
        """, (session["user_id"],)).fetchall()

    # Fotos por actividad
    fotos_map = {}
    for a in actividades:
        fotos = conn.execute("""
            SELECT * FROM fotos WHERE actividad_id=? ORDER BY id ASC
        """, (a["id"],)).fetchall()
        fotos_map[a["id"]] = fotos

    return render_template(
        "visitas.html",
        empresa=EMPRESA,
        logo=LOGO,
        rol=session.get("rol"),
        actividades=actividades,
        fotos_map=fotos_map
    )


def allowed_file(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXT


# -------------------------
# VISITAS (CREAR) - valida 2 fotos + firma
# -------------------------
@app.route("/visitas/nueva", methods=["POST"])
def nueva_visita():
    if "user_id" not in session:
        return redirect(url_for("login"))

    cliente = request.form.get("cliente", "").strip()
    comentarios = request.form.get("comentarios", "").strip()
    proxima_visita = request.form.get("proxima_visita", "").strip()

    # Fotos
    files = request.files.getlist("fotos")
    files_valid = [f for f in files if f and f.filename and allowed_file(f.filename)]

    if len(files_valid) < 2:
        flash("Debes subir mínimo 2 fotos válidas (jpg/png/webp).", "danger")
        return redirect(url_for("visitas"))

    # Firma (base64)
    firma_data = request.form.get("firma_data", "").strip()
    if not firma_data.startswith("data:image/png;base64,"):
        flash("La firma es obligatoria. Vuelve a registrar la visita y firma.", "danger")
        return redirect(url_for("visitas"))

    # Guardar actividad
    conn = get_db()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")

    cur = conn.execute("""
        INSERT INTO actividades (usuario_id, fecha, cliente, comentarios, proxima_visita, firma_archivo)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (session["user_id"], fecha, cliente, comentarios, proxima_visita, None))
    actividad_id = cur.lastrowid

    # Guardar fotos
    for idx, f in enumerate(files_valid, start=1):
        original = secure_filename(f.filename)
        ext = original.rsplit(".", 1)[1].lower()
        fname = f"actividad_{actividad_id}_{idx}_{uuid.uuid4().hex}.{ext}"
        path = os.path.join(UPLOAD_FOLDER, fname)
        f.save(path)

        conn.execute("""
            INSERT INTO fotos (actividad_id, archivo)
            VALUES (?, ?)
        """, (actividad_id, fname))

    # Guardar firma
    try:
        b64 = firma_data.split(",", 1)[1]
        firma_bytes = base64.b64decode(b64)
        firma_name = f"firma_{actividad_id}_{uuid.uuid4().hex}.png"
        firma_path = os.path.join(UPLOAD_FOLDER, firma_name)
        with open(firma_path, "wb") as out:
            out.write(firma_bytes)

        conn.execute("""
            UPDATE actividades SET firma_archivo=? WHERE id=?
        """, (firma_name, actividad_id))
    except Exception:
        # Si falla la firma, no rompas con 500: avisa y redirige
        flash("Ocurrió un error guardando la firma. Intenta de nuevo.", "danger")
        conn.commit()
        return redirect(url_for("visitas"))

    conn.commit()
    flash("Visita registrada correctamente ✅", "success")
    return redirect(url_for("visitas"))


# -------------------------
# CAMBIAR PASSWORD (USUARIO)
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

        if nuevo != confirmar:
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
                    UPDATE usuarios SET password=? WHERE id=?
                """, (generate_password_hash(nuevo), session["user_id"]))
                conn.commit()
                msg = "Password actualizado correctamente"

    return render_template(
        "cambiar_password.html",
        empresa=EMPRESA,
        logo=LOGO,
        mensaje=msg,
        error=error
    )


if __name__ == "__main__":
    app.run(debug=True)
