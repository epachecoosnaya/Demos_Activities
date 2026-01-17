from flask import Flask, render_template, request, redirect, url_for, session, abort, g
import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import os


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "super_secreto_demo")
app.permanent_session_lifetime = timedelta(hours=8)

EMPRESA = "Altasolucion"
LOGO = "logo.png"

# ✅ DB persistente (archivo), NO :memory:
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "actividades.db"))


# -------------------------
# DB helpers
# -------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


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
            rol TEXT NOT NULL,
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
            firma TEXT,
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

    # ✅ Admin por defecto
    conn.execute("""
        INSERT OR IGNORE INTO usuarios
        (usuario, nombre, apellido, email, password, rol, activo, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "admin", "Admin", "Sistema", "admin@demo.com",
        generate_password_hash("admin123"),
        "admin", 1, datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    # ✅ Demo por defecto
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


@app.before_request
def _ensure_db():
    # Se ejecuta en cada request y asegura que DB + usuarios base existan
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
        u = request.form.get("usuario", "").strip()
        p = request.form.get("password", "")

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
            session["login_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            return redirect(url_for("dashboard"))
        else:
            error = "Credenciales incorrectas"

    return render_template("login.html", empresa=EMPRESA, logo=LOGO, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def require_login():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return None


# -------------------------
# DASHBOARD
# -------------------------
@app.route("/dashboard")
def dashboard():
    r = require_login()
    if r:
        return r

    return render_template(
        "dashboard.html",
        empresa=EMPRESA,
        logo=LOGO,
        rol=session.get("rol"),
        login_time=session.get("login_time")
    )


# -------------------------
# CAMBIAR PASSWORD (MI CUENTA)
# -------------------------
@app.route("/cambiar-password", methods=["GET", "POST"])
def cambiar_password():
    r = require_login()
    if r:
        return r

    msg = None
    error = None

    if request.method == "POST":
        actual = request.form.get("actual", "")
        nuevo = request.form.get("nuevo", "")
        confirmar = request.form.get("confirmar", "")

        if not nuevo or len(nuevo) < 4:
            error = "El nuevo password es muy corto"
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
                conn.execute(
                    "UPDATE usuarios SET password=? WHERE id=?",
                    (generate_password_hash(nuevo), session["user_id"])
                )
                conn.commit()
                msg = "Password actualizado correctamente"

    return render_template(
        "cambiar_password.html",
        empresa=EMPRESA,
        logo=LOGO,
        mensaje=msg,
        error=error
    )


# -------------------------
# VISITAS
# -------------------------
@app.route("/visitas")
def visitas():
    r = require_login()
    if r:
        return r

    conn = get_db()

    if session.get("rol") == "admin":
        actividades = conn.execute("""
            SELECT a.*, u.usuario
            FROM actividades a
            JOIN usuarios u ON u.id = a.usuario_id
            ORDER BY a.fecha DESC
        """).fetchall()
    else:
        actividades = conn.execute("""
            SELECT a.*, u.usuario
            FROM actividades a
            JOIN usuarios u ON u.id = a.usuario_id
            WHERE a.usuario_id=?
            ORDER BY a.fecha DESC
        """, (session["user_id"],)).fetchall()

    return render_template(
        "visitas.html",
        empresa=EMPRESA,
        logo=LOGO,
        rol=session.get("rol"),
        actividades=actividades
    )


@app.route("/visitas/nueva", methods=["POST"])
def nueva_actividad():
    r = require_login()
    if r:
        return r

    cliente = request.form.get("cliente", "").strip()
    comentarios = request.form.get("comentarios", "").strip()
    proxima_visita = request.form.get("proxima_visita", "").strip()

    if not cliente or not comentarios:
        # Mantén simple: regresa a visitas (tu UI puede mostrar alert después)
        return redirect(url_for("visitas"))

    conn = get_db()
    conn.execute("""
        INSERT INTO actividades (usuario_id, fecha, cliente, comentarios, proxima_visita)
        VALUES (?, ?, ?, ?, ?)
    """, (
        session["user_id"],
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        cliente,
        comentarios,
        proxima_visita
    ))
    conn.commit()

    return redirect(url_for("visitas"))


# -------------------------
# USUARIOS (ADMIN)
# -------------------------
@app.route("/usuarios")
def usuarios():
    r = require_login()
    if r:
        return r

    if session.get("rol") != "admin":
        return redirect(url_for("dashboard"))

    conn = get_db()
    usuarios_list = conn.execute("""
        SELECT * FROM usuarios
        ORDER BY fecha_creacion DESC
    """).fetchall()

    return render_template(
        "usuarios.html",
        empresa=EMPRESA,
        logo=LOGO,
        usuarios=usuarios_list
    )


@app.route("/usuarios/crear", methods=["POST"])
def crear_usuario():
    r = require_login()
    if r:
        return r
    if session.get("rol") != "admin":
        abort(403)

    usuario = request.form.get("usuario", "").strip()
    nombre = request.form.get("nombre", "").strip()
    apellido = request.form.get("apellido", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()
    rol = request.form.get("rol", "vendedor").strip()

    if not usuario or not email or not password:
        return redirect(url_for("usuarios"))

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
    except sqlite3.IntegrityError:
        # usuario o email duplicado
        pass

    return redirect(url_for("usuarios"))


@app.route("/usuarios/guardar", methods=["POST"])
def guardar_usuario():
    r = require_login()
    if r:
        return r
    if session.get("rol") != "admin":
        abort(403)

    user_id = request.form.get("id")
    nombre = request.form.get("nombre", "").strip()
    apellido = request.form.get("apellido", "").strip()
    email = request.form.get("email", "").strip()
    rol = request.form.get("rol", "vendedor").strip()
    activo = 1 if request.form.get("activo") == "1" else 0

    conn = get_db()
    try:
        conn.execute("""
            UPDATE usuarios
            SET nombre=?, apellido=?, email=?, rol=?, activo=?
            WHERE id=?
        """, (nombre, apellido, email, rol, activo, user_id))
        conn.commit()
    except sqlite3.IntegrityError:
        # email duplicado
        pass

    return redirect(url_for("usuarios"))


if __name__ == "__main__":
    app.run(debug=True)
