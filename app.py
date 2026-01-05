from flask import Flask, render_template, request, redirect, url_for, session, abort
import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------------------------
# APP CONFIG
# ---------------------------------
app = Flask(__name__)
app.secret_key = "super_secreto_demo"
app.permanent_session_lifetime = timedelta(hours=8)

EMPRESA = "Altasolucion"
LOGO = "logo.png"

DB = "database.db"


# ---------------------------------
# DB
# ---------------------------------
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
        CREATE TABLE IF NOT EXISTS actividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            fecha TEXT,
            cliente TEXT,
            comentarios TEXT,
            proxima_visita TEXT
        )
    """)

    # Admin
    conn.execute("""
        INSERT OR IGNORE INTO usuarios
        (usuario, nombre, apellido, email, password, rol, activo, fecha_creacion)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "admin", "Admin", "Sistema", "admin@demo.com",
        generate_password_hash("admin123"),
        "admin", 1, datetime.now().strftime("%Y-%m-%d %H:%M")
    ))

    # Demo vendedor
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


# ---------------------------------
# CONTEXT
# ---------------------------------
@app.context_processor
def inject_now():
    return {"now": lambda: datetime.now().strftime("%Y-%m-%d %H:%M")}


# ---------------------------------
# LOGIN / LOGOUT
# ---------------------------------
@app.route("/")
def inicio():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        usuario = request.form["usuario"]
        password = request.form["password"]

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM usuarios WHERE usuario=? AND activo=1",
            (usuario,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
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


# ---------------------------------
# DASHBOARD
# ---------------------------------
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


# ---------------------------------
# USUARIOS (ADMIN)
# ---------------------------------
@app.route("/usuarios")
def usuarios():
    if session.get("rol") != "admin":
        return redirect(url_for("dashboard"))

    conn = get_db()
    usuarios = conn.execute(
        "SELECT * FROM usuarios ORDER BY fecha_creacion DESC"
    ).fetchall()
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        request.form["usuario"],
        request.form["nombre"],
        request.form["apellido"],
        request.form["email"],
        generate_password_hash(request.form["password"]),
        request.form["rol"],
        1,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))
    conn.commit()
    conn.close()

    return redirect(url_for("usuarios"))


@app.route("/usuarios/actualizar", methods=["POST"])
def actualizar_usuario():
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
    conn.close()

    return redirect(url_for("usuarios"))


# ---------------------------------
# CAMBIAR PASSWORD (USUARIO)
# ---------------------------------
@app.route("/cambiar-password", methods=["GET", "POST"])
def cambiar_password():
    if "user_id" not in session:
        return redirect(url_for("login"))

    msg = None
    error = None

    if request.method == "POST":
        actual = request.form["actual"]
        nuevo = request.form["nuevo"]
        confirmar = request.form["confirmar"]

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM usuarios WHERE id=?",
            (session["user_id"],)
        ).fetchone()

        if not check_password_hash(user["password"], actual):
            error = "Password actual incorrecto"
        elif nuevo != confirmar:
            error = "El nuevo password no coincide"
        else:
            conn.execute("""
                UPDATE usuarios SET password=? WHERE id=?
            """, (
                generate_password_hash(nuevo),
                session["user_id"]
            ))
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


# ---------------------------------
# VISITAS (placeholder estable)
# ---------------------------------
@app.route("/visitas")
def visitas():
    if "user_id" not in session:
        return redirect(url_for("login"))

    return render_template(
        "visitas.html",
        empresa=EMPRESA,
        logo=LOGO
    )


# ---------------------------------
# RUN LOCAL
# ---------------------------------
if __name__ == "__main__":
    app.run(debug=True)
