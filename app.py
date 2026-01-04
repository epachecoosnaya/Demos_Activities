from flask import Flask

app = Flask(__name__)

@app.route("/")
def inicio():
    return "<h1>Portal de Actividades</h1><p>Primer deploy funcionando</p>"

if __name__ == "__main__":
    app.run()
