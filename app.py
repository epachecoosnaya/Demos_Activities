from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import datetime

app = Flask(__name__)

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
        CREATE TABLE IF NOT EXISTS actividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT,
            cliente TEXT,
            tipo TEXT,
            comentario TEXT
        )
    """)
    conn.commit()
    conn.close()


@app.route("/")
def inicio():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["usuario"] == "demo" and request.form["password"] == "1234":
            return redirect(url_for("dashboard"))

    return render_template("login.html", empresa=EMPRESA, logo=LOGO)


@app.route("/dashboard")
def dashboard():
    conn = get_db()
    actividades = conn.execute(
        "SELECT * FROM actividades ORDER BY fecha DESC"
    ).fetchall()
    conn.close()

    return render_template(
        "dashboard.html",
        empresa=EMPRESA,
        logo=LOGO,
        actividades=actividades
    )


@app.route("/actividad/nueva", methods=["POST"])
def nueva_actividad():
    conn = get_db()
    conn.execute("""
        INSERT INTO actividades (fecha, cliente, tipo, comentario)
        VALUES (?, ?, ?, ?)
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        request.form["cliente"],
        request.form["tipo"],
        request.form["comentario"]
    ))
    conn.commit()
    conn.close()

    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    init_db()
    app.run()
