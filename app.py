from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

# Configuración DEMO (luego DB)
EMPRESA = "Altasolucion"
LOGO = "logo.png"  # si no existe, no se muestra

@app.route("/")
def inicio():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form["usuario"]
        password = request.form["password"]

        if usuario == "demo" and password == "1234":
            return redirect(url_for("dashboard"))

    return render_template(
        "login.html",
        empresa=EMPRESA,
        logo=LOGO,
        titulo="Login"
    )

@app.route("/dashboard")
def dashboard():
    return render_template(
        "dashboard.html",
        empresa=EMPRESA,
        logo=LOGO,
        titulo="Dashboard"
    )

if __name__ == "__main__":
    app.run()
