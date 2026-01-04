from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = "super_secreto_demo"

# -------------------------
# Configuración general
# -------------------------
EMPRESA = "Altasolucion"
LOGO = "logo.png"

# SQLite en memoria (Render FREE friendly)
DB = ":memory:"

# Mantener UNA sola conexión viva
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

    # Tabla usuarios
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT UNIQUE,
            password TEXT,
            rol TEXT
        )
    """)

    # Tabla actividades
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

    # Usuario demo SIEMPRE disponible
    conn.execute("""
        INSERT OR IGNORE INTO usuarios (usuario, password, rol)
        VALUES (?, ?, ?)
    """, ("demo", "1234", "vendedor"))

    conn.commit()


# Usuario admin
conn.execute("""
    INSERT OR IGNORE INTO usuarios (usuario, password, rol)
    VALUES (?, ?, ?)
""", ("admin", "admin123", "admin"))


# Inicializar DB al arrancar la app
init_db()


# -------------------------
# Rutas
# -------------------------
@app.route("/")
def inicio():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        usuario = request.form.get("usuario")
        password = request.form.get("password")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM usuarios WHERE usuario=? AND password=?",
            (usuario, password)
        ).fetchone()

        if user:
            session["user_id"] = user["id"]
            session["usuario"] = user["usuario"]
            session["rol"] = user["rol"]
            return redirect(url_for("dashboard"))
        else:
            error = "Usuario o contraseña incorrectos"

    return render_template(
        "login.html",
        empresa=EMPRESA,
        logo=LOGO,
        error=error
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db()

    actividades = conn.execute("""
        SELECT *
        FROM actividades
        WHERE usuario_id=?
        ORDER BY fecha DESC
    """, (session["user_id"],)).fetchall()

    return render_template(
        "dashboard.html",
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
        INSERT INTO actividades (
            usuario_id, fecha, cliente, comentarios, proxima_visita
        ) VALUES (?, ?, ?, ?, ?)
    """, (
        session["user_id"],
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        request.form["cliente"],
        request.form["comentarios"],
        request.form["proxima_visita"]
    ))

    conn.commit()
    return redirect(url_for("dashboard"))


# -------------------------
# Arranque local (Render usa gunicorn)
# -------------------------
if __name__ == "__main__":
    app.run(debug=True)
