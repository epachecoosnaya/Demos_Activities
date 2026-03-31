from flask import Flask, render_template, request, redirect, url_for, session, abort, flash
import sqlite3
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os, base64, uuid

app = Flask(__name__)
app.secret_key = "super_secreto_demo"
app.permanent_session_lifetime = timedelta(hours=8)

EMPRESA = "Altasolucion"
LOGO = "logo.png"
DB_PATH = "database.db"
UPLOAD_FOLDER = os.path.join("static", "uploads")
PHOTOS_FOLDER = os.path.join(UPLOAD_FOLDER, "photos")
SIG_FOLDER = os.path.join(UPLOAD_FOLDER, "signatures")
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}

os.makedirs(PHOTOS_FOLDER, exist_ok=True)
os.makedirs(SIG_FOLDER, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT UNIQUE,
        nombre TEXT, apellido TEXT, email TEXT UNIQUE, password TEXT,
        rol TEXT, activo INTEGER, fecha_creacion TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS actividades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER,
        fecha TEXT, cliente TEXT, comentarios TEXT, proxima_visita TEXT,
        firma_archivo TEXT, FOREIGN KEY(usuario_id) REFERENCES usuarios(id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS fotos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, actividad_id INTEGER, archivo TEXT,
        FOREIGN KEY(actividad_id) REFERENCES actividades(id))""")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn.execute("INSERT OR IGNORE INTO usuarios (usuario,nombre,apellido,email,password,rol,activo,fecha_creacion) VALUES (?,?,?,?,?,?,?,?)",
        ("admin","Admin","Sistema","admin@demo.com", generate_password_hash("admin123"), "admin",1,now))
    conn.execute("INSERT OR IGNORE INTO usuarios (usuario,nombre,apellido,email,password,rol,activo,fecha_creacion) VALUES (?,?,?,?,?,?,?,?)",
        ("demo","Demo","Vendedor","demo@demo.com", generate_password_hash("1234"), "vendedor",1,now))
    conn.commit()
    conn.close()


init_db()


def logged_in(): return "user_id" in session
def is_admin(): return session.get("rol") == "admin"
def allowed_file(f): return "." in f and f.rsplit(".",1)[1].lower() in ALLOWED_EXT


def save_signature_dataurl(dataurl, actividad_id):
    if not dataurl or not dataurl.startswith("data:image"): raise ValueError("Firma inválida")
    header, b64 = dataurl.split(",", 1)
    if "image/png" not in header: raise ValueError("La firma debe ser PNG")
    raw = base64.b64decode(b64)
    fname = f"firma_{actividad_id}_{uuid.uuid4().hex}.png"
    with open(os.path.join(SIG_FOLDER, fname), "wb") as f: f.write(raw)
    return os.path.join("uploads","signatures",fname).replace("\\","/")


def save_photo(file_storage, actividad_id):
    filename = secure_filename(file_storage.filename)
    if not allowed_file(filename): raise ValueError("Archivo no permitido")
    ext = filename.rsplit(".",1)[1].lower()
    fname = f"foto_{actividad_id}_{uuid.uuid4().hex}.{ext}"
    file_storage.save(os.path.join(PHOTOS_FOLDER, fname))
    return os.path.join("uploads","photos",fname).replace("\\","/")


def get_stats(user_id=None, is_admin_user=False):
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    if is_admin_user:
        tv = conn.execute("SELECT COUNT(*) FROM actividades").fetchone()[0]
        vh = conn.execute("SELECT COUNT(*) FROM actividades WHERE fecha LIKE ?", (today+"%",)).fetchone()[0]
        tu = conn.execute("SELECT COUNT(*) FROM usuarios WHERE activo=1").fetchone()[0]
        tf = conn.execute("SELECT COUNT(*) FROM fotos").fetchone()[0]
    else:
        tv = conn.execute("SELECT COUNT(*) FROM actividades WHERE usuario_id=?", (user_id,)).fetchone()[0]
        vh = conn.execute("SELECT COUNT(*) FROM actividades WHERE usuario_id=? AND fecha LIKE ?", (user_id, today+"%")).fetchone()[0]
        tu = 0
        tf = conn.execute("SELECT COUNT(*) FROM fotos f JOIN actividades a ON f.actividad_id=a.id WHERE a.usuario_id=?", (user_id,)).fetchone()[0]
    conn.close()
    return {"total_visitas":tv, "visitas_hoy":vh, "total_usuarios":tu, "total_fotos":tf}


@app.context_processor
def inject_globals():
    return {"now": lambda: datetime.now().strftime("%d/%m/%Y %H:%M")}


@app.route("/")
def inicio(): return redirect(url_for("login"))


@app.route("/login", methods=["GET","POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("usuario","").strip()
        p = request.form.get("password","")
        conn = get_db()
        user = conn.execute("SELECT * FROM usuarios WHERE usuario=? AND activo=1", (u,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password"], p):
            session.permanent = True
            session["user_id"] = user["id"]
            session["usuario"] = user["usuario"]
            session["rol"] = user["rol"]
            return redirect(url_for("dashboard"))
        else:
            error = "Credenciales incorrectas"
    return render_template("login.html", empresa=EMPRESA, logo=LOGO, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    if not logged_in(): return redirect(url_for("login"))
    uid = session["user_id"]
    admin = is_admin()
    stats = get_stats(user_id=uid, is_admin_user=admin)
    conn = get_db()
    if admin:
        vr = conn.execute("""SELECT a.id,a.fecha,u.usuario,a.cliente,a.comentarios FROM actividades a
            JOIN usuarios u ON u.id=a.usuario_id ORDER BY a.fecha DESC LIMIT 5""").fetchall()
    else:
        vr = conn.execute("""SELECT a.id,a.fecha,u.usuario,a.cliente,a.comentarios FROM actividades a
            JOIN usuarios u ON u.id=a.usuario_id WHERE a.usuario_id=? ORDER BY a.fecha DESC LIMIT 5""", (uid,)).fetchall()
    conn.close()
    return render_template("dashboard.html", empresa=EMPRESA, logo=LOGO, rol=session["rol"], stats=stats, visitas_recientes=vr)


@app.route("/visitas")
def visitas():
    if not logged_in(): return redirect(url_for("login"))
    conn = get_db()
    q = """SELECT a.id,a.fecha,u.usuario,a.cliente,a.comentarios,a.proxima_visita,a.firma_archivo,
           (SELECT COUNT(*) FROM fotos f WHERE f.actividad_id=a.id) AS fotos_count
           FROM actividades a JOIN usuarios u ON u.id=a.usuario_id"""
    if is_admin():
        actividades = conn.execute(q + " ORDER BY a.fecha DESC").fetchall()
    else:
        actividades = conn.execute(q + " WHERE a.usuario_id=? ORDER BY a.fecha DESC", (session["user_id"],)).fetchall()
    conn.close()
    return render_template("visitas.html", empresa=EMPRESA, logo=LOGO, actividades=actividades)


@app.route("/visitas/guardar", methods=["POST"])
def guardar_visita():
    if not logged_in(): return redirect(url_for("login"))
    cliente = request.form.get("cliente","").strip()
    comentarios = request.form.get("comentarios","").strip()
    proxima = request.form.get("proxima_visita","").strip() or None
    firma_data = request.form.get("firma_data","").strip()
    fotos = request.files.getlist("fotos")

    if not cliente or not comentarios:
        flash("Cliente y comentarios son obligatorios.", "danger")
        return redirect(url_for("visitas"))

    fotos_validas = [f for f in fotos if f and f.filename]
    if len(fotos_validas) < 2:
        flash("Debes subir 2 fotos obligatorias.", "danger")
        return redirect(url_for("visitas"))

    if not firma_data or not firma_data.startswith("data:image"):
        flash("La firma es obligatoria.", "danger")
        return redirect(url_for("visitas"))

    conn = get_db(); cur = conn.cursor()
    cur.execute("INSERT INTO actividades (usuario_id,fecha,cliente,comentarios,proxima_visita,firma_archivo) VALUES (?,?,?,?,?,?)",
        (session["user_id"], datetime.now().strftime("%Y-%m-%d %H:%M"), cliente, comentarios, proxima, None))
    actividad_id = cur.lastrowid

    try:
        firma_rel = save_signature_dataurl(firma_data, actividad_id)
    except Exception:
        conn.rollback(); conn.close()
        flash("Error guardando la firma.", "danger")
        return redirect(url_for("visitas"))

    cur.execute("UPDATE actividades SET firma_archivo=? WHERE id=?", (firma_rel, actividad_id))

    try:
        for f in fotos_validas[:2]:
            rel = save_photo(f, actividad_id)
            cur.execute("INSERT INTO fotos (actividad_id,archivo) VALUES (?,?)", (actividad_id, rel))
    except Exception:
        conn.rollback(); conn.close()
        flash("Error guardando fotos.", "danger")
        return redirect(url_for("visitas"))

    conn.commit(); conn.close()
    flash("Visita registrada correctamente ✅", "success")
    return redirect(url_for("visitas"))


@app.route("/visitas/detalle/<int:actividad_id>")
def detalle_visita(actividad_id):
    if not logged_in(): return redirect(url_for("login"))
    conn = get_db()
    act = conn.execute("SELECT a.*,u.usuario FROM actividades a JOIN usuarios u ON u.id=a.usuario_id WHERE a.id=?", (actividad_id,)).fetchone()
    if not act: conn.close(); abort(404)
    if (not is_admin()) and act["usuario_id"] != session["user_id"]: conn.close(); abort(403)
    fotos = conn.execute("SELECT * FROM fotos WHERE actividad_id=? ORDER BY id ASC", (actividad_id,)).fetchall()
    conn.close()
    return render_template("visitas_detalle.html", empresa=EMPRESA, logo=LOGO, act=act, fotos=fotos)


@app.route("/usuarios")
def usuarios():
    if not logged_in(): return redirect(url_for("login"))
    if not is_admin(): abort(403)
    conn = get_db()
    ul = conn.execute("SELECT id,usuario,nombre,apellido,email,rol,activo,fecha_creacion FROM usuarios ORDER BY fecha_creacion DESC").fetchall()
    conn.close()
    return render_template("usuarios.html", empresa=EMPRESA, logo=LOGO, usuarios=ul)


@app.route("/usuarios/crear", methods=["POST"])
def crear_usuario():
    if not logged_in(): return redirect(url_for("login"))
    if not is_admin(): abort(403)
    usuario = request.form.get("usuario","").strip()
    nombre = request.form.get("nombre","").strip()
    apellido = request.form.get("apellido","").strip()
    email = request.form.get("email","").strip()
    password = request.form.get("password","")
    rol = request.form.get("rol","vendedor")
    if not usuario or not email or not password:
        flash("Usuario, email y password son obligatorios.", "danger"); return redirect(url_for("usuarios"))
    conn = get_db()
    try:
        conn.execute("INSERT INTO usuarios (usuario,nombre,apellido,email,password,rol,activo,fecha_creacion) VALUES (?,?,?,?,?,?,?,?)",
            (usuario,nombre,apellido,email,generate_password_hash(password),rol,1,datetime.now().strftime("%Y-%m-%d %H:%M")))
        conn.commit(); flash("Usuario creado ✅","success")
    except sqlite3.IntegrityError:
        flash("Usuario o email ya existe.","danger")
    finally: conn.close()
    return redirect(url_for("usuarios"))


@app.route("/usuarios/actualizar", methods=["POST"])
def actualizar_usuario():
    if not logged_in(): return redirect(url_for("login"))
    if not is_admin(): abort(403)
    uid = request.form.get("id")
    nombre = request.form.get("nombre","").strip()
    apellido = request.form.get("apellido","").strip()
    email = request.form.get("email","").strip()
    rol = request.form.get("rol","vendedor")
    activo = 1 if request.form.get("activo")=="1" else 0
    new_password = request.form.get("new_password","").strip()
    if not uid:
        flash("ID inválido.","danger"); return redirect(url_for("usuarios"))
    conn = get_db()
    try:
        if new_password:
            conn.execute("UPDATE usuarios SET nombre=?,apellido=?,email=?,rol=?,activo=?,password=? WHERE id=?",
                (nombre,apellido,email,rol,activo,generate_password_hash(new_password),uid))
        else:
            conn.execute("UPDATE usuarios SET nombre=?,apellido=?,email=?,rol=?,activo=? WHERE id=?",
                (nombre,apellido,email,rol,activo,uid))
        conn.commit(); flash("Usuario actualizado ✅","success")
    except sqlite3.IntegrityError:
        flash("Email ya está en uso.","danger")
    finally: conn.close()
    return redirect(url_for("usuarios"))


if __name__ == "__main__":
    app.run(debug=True)
