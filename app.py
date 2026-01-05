from flask import Flask, render_template, request, redirect, url_for, session, abort
import sqlite3
from datetime import datetime, timedelta
import secrets

app = Flask(__name__)
app.secret_key = "super_secreto_demo"
app.permanent_session_lifetime = timedelta(hours=8)

EMPRESA = "Altasolucion"
LOGO = "logo.png"

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
            email TEXT UNIQUE,
            password TEXT,
            rol TEXT,
            activo INTEGER,
            fecha_creacion TEXT,
            reset_token TEXT,
            reset_expira TEXT
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

    # Usuarios base
    conn.execute("""
        INSERT OR IGNORE INTO usuarios
        (usuario, nombre, apellido, email, password, rol, activo, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "admin", "Admin", "Sistema", "admin@demo.com",
        "admin123", "admin", 1, datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    conn.execute("""
        INSERT OR IGNORE INTO usuarios
        (usuario, nombre, apellido, email, password, rol, activo, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "demo", "Demo", "Vendedor", "demo@demo.com",
        "1234", "vendedor", 1, datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    conn.commit()


init_db()


@app.context_processor
def inject_now():
    return {"now": lambda: datetime.now().strftime("%Y-%m-%d %H:%M")}

# -------------------------
# LOGIN / LOGOUT
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
        rol=session["rol"],
        login_time=session["login_time"]
    )

# -------------------------
# USUARIOS (ADMIN)
# -------------------------
@app.route("/usuarios")
def usuarios():
    if session.get("rol") != "admin":
        return redirect(url_for("dashboard"))

    conn = get_db()
    usuarios = conn.execute("SELECT * FROM usuarios ORDER BY fecha_creacion DESC").fetchall()

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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        request.form["usuario"],
        request.form["nombre"],
        request.form["apellido"],
        request.form["email"],
        request.form["password"],
        request.form["rol"],
        1,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    conn.commit()
    return redirect(url_for("usuarios"))


@app.route("/usuarios/guardar", methods=["POST"])
def guardar_usuario():
    if session.get("rol") != "admin":
        abort(403)

    conn = get_db()
    conn.execute("""
        UPDATE usuarios SET
        nombre=?,
        apellido=?,
        email=?,
        rol=?,
        activo=?
        WHERE id=?
    """, (
        request.form["nombre"],
        request.form["apellido"],
        request.form["email"],
        request.form["rol"],
        int(request.form.get("activo", 0)),
        request.form["id"]
    ))

    conn.commit()
    return redirect(url_for("usuarios"))

# -------------------------
# VISITAS
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

    return render_template(
        "visitas.html",
        empresa=EMPRESA,
        logo=LOGO,
        actividades=actividades,
        rol=session["rol"]
    )


@app.route("/actividad/nueva", methods=["POST"])
def nueva_actividad():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()
    conn.execute("""
        INSERT INTO actividades
        (usuario_id, fecha, cliente, comentarios, proxima_visita)
        VALUES (?, ?, ?, ?, ?)
    """, (
        session["user_id"],
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        request.form["cliente"],
        request.form["comentarios"],
        request.form["proxima_visita"]
    ))

    conn.commit()
    return redirect(url_for("visitas"))
