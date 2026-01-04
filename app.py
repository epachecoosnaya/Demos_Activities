from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = "super_secreto_demo"

EMPRESA = "Altasolucion"
LOGO = "logo.png"
DB = "actividades.db"


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
        password TEXT,
        rol TEXT
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
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
    )
    """)

    # Usuario demo inicial
    user = conn.execute("SELECT * FROM usuarios WHERE usuario='demo'").fetchone()
    if not user:
        conn.execute(
            "INSERT INTO usuarios (usuario, password, rol) VALUES (?, ?, ?)",
            ("demo", "1234", "vendedor")
        )

    conn.commit()
    conn.close()


@app.route("/", methods=["GET"])
def inicio():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form["usuario"]
        password = request.form["password"]

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM usuarios WHERE usuario=? AND password=?",
            (usuario, password)
        ).fetchone()
        conn.close()

        if user:
            session["user_id"] = user["id"]
            session["usuario"] = user["usuario"]
            session["rol"] = user["rol"]
            return redirect(url_for("dashboard"))

    return render_template("login.html", empresa=EMPRESA, logo=LOGO)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


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
    else:
        actividades = conn.execute("""
            SELECT *
            FROM actividades
            WHERE usuario_id=?
            ORDER BY fecha DESC
        """, (session["user_id"],)).fetchall()

    conn.close()

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
    conn.close()

    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    init_db()
    app.run()
