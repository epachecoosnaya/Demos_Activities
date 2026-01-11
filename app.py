from flask import Flask, render_template, request, redirect, url_for, session, abort, flash
import sqlite3, os
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# -------------------------
# APP CONFIG
# -------------------------
app = Flask(__name__)
app.secret_key = "super_secreto_demo"
app.permanent_session_lifetime = timedelta(hours=8)

EMPRESA = "Altasolucion"
LOGO = "logo.png"

# En Render, ":memory:" te rompe todo porque reinicia y no persiste.
# Usamos archivo en /tmp (en free puede reiniciarse, pero al menos no se borra en cada request).
DB_PATH = os.environ.get("DB_PATH", "/tmp/actividades.db")

UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "static/uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

# -------------------------
# DB HELPERS
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
            usuario TEXT UNIQUE NOT NULL,
            nombre TEXT,
            apellido TEXT,
            email TEXT UNIQUE,
            password TEXT NOT NULL,
            rol TEXT NOT NULL,          -- 'admin' | 'vendedor'
            activo INTEGER NOT NULL DEFAULT 1,
            fecha_creacion TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS actividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            cliente TEXT NOT NULL,
            comentarios TEXT NOT NULL,
            proxima_visita TEXT,
            FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS fotos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actividad_id INTEGER NOT NULL,
            archivo TEXT NOT NULL,
            FOREIGN KEY(actividad_id) REFERENCES actividades(id)
        )
    """)

    # Seed admin/demo si no existen
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn.execute("""
        INSERT OR IGNORE INTO usuarios (usuario, nombre, apellido, email, password, rol, activo, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
    """, ("admin", "Admin", "Sistema", "admin@demo.com", generate_password_hash("admin123"), "admin", now))

    conn.execute("""
        INSERT OR IGNORE INTO usuarios (usuario, nombre, apellido, email, password, rol, activo, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
    """, ("demo", "Demo", "Vendedor", "demo@demo.com", generate_password_hash("1234"), "vendedor", now))

    conn.commit()
    conn.close()

init_db()

def allowed_file(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS

# -------------------------
# CONTEXT (now())
# -------------------------
@app.context_processor
def inject_now():
    return {"now": lambda: datetime.now().strftime("%Y-%m-%d %H:%M")}

# -------------------------
# AUTH
# -------------------------
@app.route("/", methods=["GET"])
def root():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        u = (request.form.get("usuario") or "").strip()
        p = request.form.get("password") or ""

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
        rol=session.get("rol"),
        login_time=session.get("login_time")
    )

# -------------------------
# CAMBIAR PASSWORD (USUARIO LOGUEADO)
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

        if len(nuevo) < 6:
            error = "El password nuevo debe tener mínimo 6 caracteres"
        elif nuevo != confirmar:
            error = "El nuevo password no coincide"
        else:
            conn = get_db()
            user = conn.execute("SELECT * FROM usuarios WHERE id=?", (session["user_id"],)).fetchone()

            if not user or not check_password_hash(user["password"], actual):
                error = "Password actual incorrecto"
            else:
                conn.execute(
                    "UPDATE usuarios SET password=? WHERE id=?",
                    (generate_password_hash(nuevo), session["user_id"])
                )
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

# -------------------------
# USUARIOS (ADMIN)
# -------------------------
@app.route("/usuarios", methods=["GET"])
def usuarios():
    if "user_id" not in session:
        return redirect(url_for("login"))
    if session.get("rol") != "admin":
        return redirect(url_for("dashboard"))

    conn = get_db()
    rows = conn.execute("""
        SELECT id, usuario, nombre, apellido, email, rol, activo, fecha_creacion
        FROM usuarios
        ORDER BY fecha_creacion DESC
    """).fetchall()
    conn.close()

    return render_template(
        "usuarios.html",
        empresa=EMPRESA,
        logo=LOGO,
        usuarios=rows
    )

@app.route("/usuarios/crear", methods=["POST"])
def crear_usuario():
    if "user_id" not in session:
        return redirect(url_for("login"))
    if session.get("rol") != "admin":
        abort(403)

    usuario = (request.form.get("usuario") or "").strip()
    nombre = (request.form.get("nombre") or "").strip()
    apellido = (request.form.get("apellido") or "").strip()
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    rol = request.form.get("rol") or "vendedor"

    if not usuario or not nombre or not apellido or not email or not password:
        flash("Todos los campos son obligatorios para crear usuario.", "danger")
        return redirect(url_for("usuarios"))

    if rol not in ("admin", "vendedor"):
        rol = "vendedor"

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO usuarios (usuario, nombre, apellido, email, password, rol, activo, fecha_creacion)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        """, (
            usuario, nombre, apellido, email,
            generate_password_hash(password),
            rol,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ))
        conn.commit()
        flash("Usuario creado correctamente.", "success")
    except sqlite3.IntegrityError:
        flash("Ese usuario o email ya existe.", "danger")
    finally:
        conn.close()

    return redirect(url_for("usuarios"))

@app.route("/usuarios/guardar", methods=["POST"])
def guardar_usuario():
    if "user_id" not in session:
        return redirect(url_for("login"))
    if session.get("rol") != "admin":
        abort(403)

    uid = request.form.get("id")
    nombre = (request.form.get("nombre") or "").strip()
    apellido = (request.form.get("apellido") or "").strip()
    email = (request.form.get("email") or "").strip()
    rol = request.form.get("rol") or "vendedor"
    activo = 1 if request.form.get("activo") else 0

    if rol not in ("admin", "vendedor"):
        rol = "vendedor"

    conn = get_db()
    try:
        conn.execute("""
            UPDATE usuarios
            SET nombre=?, apellido=?, email=?, rol=?, activo=?
            WHERE id=?
        """, (nombre, apellido, email, rol, activo, uid))
        conn.commit()
        flash("Usuario actualizado.", "success")
    except sqlite3.IntegrityError:
        flash("No se pudo guardar: email duplicado.", "danger")
    finally:
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

    if session.get("rol") == "admin":
        rows = conn.execute("""
            SELECT a.*, u.usuario
            FROM actividades a
            JOIN usuarios u ON u.id = a.usuario_id
            ORDER BY a.fecha DESC
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT a.*
            FROM actividades a
            WHERE a.usuario_id=?
            ORDER BY a.fecha DESC
        """, (session["user_id"],)).fetchall()

    # Fotos por actividad
    actividad_ids = [r["id"] for r in rows]
    fotos_map = {}
    if actividad_ids:
        q_marks = ",".join(["?"] * len(actividad_ids))
        fotos = conn.execute(f"""
            SELECT actividad_id, archivo
            FROM fotos
            WHERE actividad_id IN ({q_marks})
            ORDER BY id ASC
        """, actividad_ids).fetchall()

        for f in fotos:
            fotos_map.setdefault(f["actividad_id"], []).append(f["archivo"])

    conn.close()

    return render_template(
        "visitas.html",
        empresa=EMPRESA,
        logo=LOGO,
        rol=session.get("rol"),
        visitas=rows,          # para tu visitas.html actual (más simple)
        actividades=rows,      # por si estás usando el otro template
        fotos_map=fotos_map    # para que luego muestres thumbnails si quieres
    )

@app.route("/visitas/nueva", methods=["POST"])
def nueva_visita():
    if "user_id" not in session:
        abort(403)

    cliente = (request.form.get("cliente") or "").strip()
    comentarios = (request.form.get("comentarios") or "").strip()
    proxima = request.form.get("proxima_visita") or None

    if not cliente or not comentarios:
        return "Cliente y comentarios son obligatorios", 400

    fotos = request.files.getlist("fotos")
    fotos = [f for f in fotos if f and f.filename]

    if len(fotos) < 2:
        return "Debes subir mínimo 2 fotos", 400

    # Validación extensiones
    for f in fotos:
        if not allowed_file(f.filename):
            return "Formato de imagen inválido (usa png/jpg/jpeg/webp)", 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO actividades (usuario_id, fecha, cliente, comentarios, proxima_visita)
        VALUES (?, ?, ?, ?, ?)
    """, (
        session["user_id"],
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        cliente,
        comentarios,
        proxima
    ))
    actividad_id = cur.lastrowid

    carpeta_rel = f"uploads/actividad_{actividad_id}"
    carpeta_abs = os.path.join("static", carpeta_rel)
    os.makedirs(carpeta_abs, exist_ok=True)

    for f in fotos:
        base = secure_filename(f.filename)
        # Evita colisiones
        nombre_final = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{base}"
        ruta_abs = os.path.join(carpeta_abs, nombre_final)
        f.save(ruta_abs)

        ruta_rel = f"/static/{carpeta_rel}/{nombre_final}"  # para usar directo en <img src="">
        cur.execute("INSERT INTO fotos (actividad_id, archivo) VALUES (?, ?)", (actividad_id, ruta_rel))

    conn.commit()
    conn.close()

    return redirect(url_for("visitas"))

# -------------------------
# MAIN
# -------------------------
if __name__ == "__main__":
    app.run(debug=True)
