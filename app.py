from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "super_secreto_demo"

# -------------------------
# Configuración general
# -------------------------
EMPRESA = "Altasolucion"
LOGO = "logo.png"

# Sesión válida por 8 horas
app.permanent_session_lifetime = timedelta(hours=8)

# SQLite en memoria (Render FREE / demos)
DB = ":memory:"
db_conn = None


# -------------------------
# Base de datos
# -------------------------
def get_db():
    global db_conn
    if db_conn is None:
        db_conn = sqlite3.connect(DB, check_same_thread=False)
        db_conn.row_factory = sqlite3.Row
    return db_conn


def init_db():
    conn = get_db()

    # Usuarios
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE,
            email TEXT UNIQUE,
            password TEXT,
            rol TEXT,
            activo INTEGER,
            fecha_creacion TEXT
        )
    """)

    # Actividades
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

    # Usuario vendedor demo
    conn.execute("""
        INSERT OR IGNORE INTO usuarios
        (usuario, email, password, rol, activo, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        "demo",
        "demo@demo.com",
        "1234",
        "vendedor",
        1,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    # Usuario admin
    conn.execute("""
        INSERT OR IGNORE INTO usuarios
        (usuario, email, password, rol, activo, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        "admin",
        "admin@demo.com",
        "admin123",
        "admin",
        1,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    conn.commit()


init_db()


# -------------------------
# Contexto global
# -------------------------
@app.context_processor
def inject_now():
    return {
        "now": lambda: datetime.now().strftime("%Y-%m-%d %H:%M")
    }


# -------------------------
# Autenticación
# -------------------------
@app.route("/", methods=["GET"])
def inicio():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        usuario = request.form["usuario"]
        password = request.form["password"]

        conn = get_db()
        user = conn.execute("""
            SELECT * FROM usuarios
            WHERE usuario=? AND password=? AND activo=1
        """, (usuario, password)).fetchone()

        if user:
            session.permanent = True
            session["user_id"] = user["id"]
            session["usuario"] = user["usuario"]
            session["rol"] = user["rol"]
            session["login_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            return redirect(url_for("dashboard"))
        else:
            error = "Credenciales incorrectas o usuario inactivo"

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

    conn = get_db()

    if session["rol"] == "admin":
        actividades = conn.execute("""
            SELECT a.*, u.usuario
            FROM actividades a
            JOIN usuarios u ON u.id = a.usuario_id
            ORDER BY fecha DESC
        """).fetchall()

        usuarios = conn.execute("""
            SELECT id, usuario, email, rol, activo, fecha_creacion
            FROM usuarios
            ORDER BY fecha_creacion DESC
        """).fetchall()
    else:
        actividades = conn.execute("""
            SELECT *
            FROM actividades
            WHERE usuario_id=?
            ORDER BY fecha DESC
        """, (session["user_id"],)).fetchall()
        usuarios = []

    return render_template(
        "dashboard.html",
        empresa=EMPRESA,
        logo=LOGO,
        actividades=actividades,
        usuarios=usuarios,
        rol=session["rol"],
        login_time=session.get("login_time")
    )


# -------------------------
# Actividades
# -------------------------
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
        request.form.get("proxima_visita")
    ))

    conn.commit()
    return redirect(url_for("dashboard"))


# -------------------------
# Usuarios (ADMIN)
# -------------------------
@app.route("/usuarios/crear", methods=["POST"])
def crear_usuario():
    if session.get("rol") != "admin":
        return redirect(url_for("dashboard"))

    conn = get_db()
    conn.execute("""
        INSERT INTO usuarios
        (usuario, email, password, rol, activo, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        request.form["usuario"],
        request.form["email"],
        request.form["password"],
        request.form["rol"],
        1,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    conn.commit()
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(debug=True)
