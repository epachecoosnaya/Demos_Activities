import os, uuid, base64
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, abort, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import psycopg2
from psycopg2.extras import RealDictCursor
from supabase import create_client, Client

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "super_secreto_demo_cambiar")
app.permanent_session_lifetime = timedelta(hours=8)

EMPRESA = "Altasolucion"
LOGO    = "logo.png"

# ── Supabase ──────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

BUCKET_FOTOS   = "fotos"
BUCKET_FIRMAS  = "firmas"
ALLOWED_EXT    = {"png", "jpg", "jpeg", "webp"}


# ── DB helpers ────────────────────────────────────────────
def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute(sql, params)
    result = None
    if fetchone:  result = cur.fetchone()
    if fetchall:  result = cur.fetchall()
    if commit:    conn.commit()
    cur.close(); conn.close()
    return result

def init_db():
    """Crea tablas si no existen y usuario admin por defecto."""
    conn = get_db(); cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id            SERIAL PRIMARY KEY,
            usuario       TEXT UNIQUE NOT NULL,
            nombre        TEXT DEFAULT '',
            apellido      TEXT DEFAULT '',
            email         TEXT UNIQUE NOT NULL,
            password      TEXT NOT NULL,
            rol           TEXT DEFAULT 'vendedor',
            activo        INTEGER DEFAULT 1,
            fecha_creacion TEXT DEFAULT ''
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS actividades (
            id             SERIAL PRIMARY KEY,
            usuario_id     INTEGER REFERENCES usuarios(id),
            fecha          TEXT NOT NULL,
            cliente        TEXT NOT NULL,
            comentarios    TEXT DEFAULT '',
            proxima_visita TEXT DEFAULT NULL,
            firma_archivo  TEXT DEFAULT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS fotos (
            id           SERIAL PRIMARY KEY,
            actividad_id INTEGER REFERENCES actividades(id),
            archivo      TEXT NOT NULL
        )
    """)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cur.execute("""
        INSERT INTO usuarios (usuario,nombre,apellido,email,password,rol,activo,fecha_creacion)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (usuario) DO NOTHING
    """, ("admin","Admin","Sistema","admin@demo.com",
          generate_password_hash("admin123"), "admin", 1, now))
    cur.execute("""
        INSERT INTO usuarios (usuario,nombre,apellido,email,password,rol,activo,fecha_creacion)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (usuario) DO NOTHING
    """, ("demo","Demo","Vendedor","demo@demo.com",
          generate_password_hash("1234"), "vendedor", 1, now))

    conn.commit(); cur.close(); conn.close()

init_db()


# ── Storage helpers ───────────────────────────────────────
def allowed_file(filename):
    return "." in filename and filename.rsplit(".",1)[1].lower() in ALLOWED_EXT

def upload_foto(file_storage, actividad_id):
    filename = secure_filename(file_storage.filename)
    if not allowed_file(filename):
        raise ValueError("Formato no permitido")
    ext  = filename.rsplit(".",1)[1].lower()
    name = f"actividad_{actividad_id}/{uuid.uuid4().hex}.{ext}"
    data = file_storage.read()
    supabase.storage.from_(BUCKET_FOTOS).upload(
        name, data, {"content-type": f"image/{ext}"}
    )
    public_url = supabase.storage.from_(BUCKET_FOTOS).get_public_url(name)
    return public_url

def upload_firma(dataurl, actividad_id):
    if not dataurl or not dataurl.startswith("data:image"):
        raise ValueError("Firma inválida")
    _, b64 = dataurl.split(",", 1)
    raw    = base64.b64decode(b64)
    name   = f"actividad_{actividad_id}/{uuid.uuid4().hex}.png"
    supabase.storage.from_(BUCKET_FIRMAS).upload(
        name, raw, {"content-type": "image/png"}
    )
    public_url = supabase.storage.from_(BUCKET_FIRMAS).get_public_url(name)
    return public_url


# ── Helpers de sesión ─────────────────────────────────────
def logged_in(): return "user_id" in session
def is_admin():  return session.get("rol") == "admin"
def can_see_all(): return session.get("rol") in ["admin","gerente","supervisor"]

@app.context_processor
def inject_globals():
    return {"now": lambda: datetime.now().strftime("%d/%m/%Y %H:%M")}


# ── LOGIN / LOGOUT ────────────────────────────────────────
@app.route("/")
def inicio(): return redirect(url_for("login"))

@app.route("/login", methods=["GET","POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("usuario","").strip()
        p = request.form.get("password","")
        user = query(
            "SELECT * FROM usuarios WHERE usuario=%s AND activo=1",
            (u,), fetchone=True
        )
        if user and check_password_hash(user["password"], p):
            session.permanent = True
            session["user_id"] = user["id"]
            session["usuario"] = user["usuario"]
            session["rol"]     = user["rol"]
            return redirect(url_for("dashboard"))
        error = "Credenciales incorrectas"
    return render_template("login.html", empresa=EMPRESA, logo=LOGO, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── DASHBOARD ─────────────────────────────────────────────
@app.route("/dashboard")
def dashboard():
    if not logged_in(): return redirect(url_for("login"))
    uid   = session["user_id"]
    admin = can_see_all()
    today = datetime.now().strftime("%Y-%m-%d")

    if admin:
        tv = query("SELECT COUNT(*) AS c FROM actividades", fetchone=True)["c"]
        vh = query("SELECT COUNT(*) AS c FROM actividades WHERE fecha LIKE %s",
                   (today+"%",), fetchone=True)["c"]
        tu = query("SELECT COUNT(*) AS c FROM usuarios WHERE activo=1", fetchone=True)["c"]
        tf = query("SELECT COUNT(*) AS c FROM fotos", fetchone=True)["c"]
        vr = query("""SELECT a.id,a.fecha,u.usuario,a.cliente,a.comentarios
                      FROM actividades a JOIN usuarios u ON u.id=a.usuario_id
                      ORDER BY a.fecha DESC LIMIT 5""", fetchall=True)
    else:
        tv = query("SELECT COUNT(*) AS c FROM actividades WHERE usuario_id=%s",
                   (uid,), fetchone=True)["c"]
        vh = query("SELECT COUNT(*) AS c FROM actividades WHERE usuario_id=%s AND fecha LIKE %s",
                   (uid, today+"%"), fetchone=True)["c"]
        tu = 0
        tf = query("""SELECT COUNT(*) AS c FROM fotos f
                      JOIN actividades a ON f.actividad_id=a.id
                      WHERE a.usuario_id=%s""", (uid,), fetchone=True)["c"]
        vr = query("""SELECT a.id,a.fecha,u.usuario,a.cliente,a.comentarios
                      FROM actividades a JOIN usuarios u ON u.id=a.usuario_id
                      WHERE a.usuario_id=%s ORDER BY a.fecha DESC LIMIT 5""",
                   (uid,), fetchall=True)

    stats = {"total_visitas":tv,"visitas_hoy":vh,"total_usuarios":tu,"total_fotos":tf}
    return render_template("dashboard.html", empresa=EMPRESA, logo=LOGO,
                           rol=session["rol"], stats=stats, visitas_recientes=vr)


# ── VISITAS ───────────────────────────────────────────────
@app.route("/visitas")
def visitas():
    if not logged_in(): return redirect(url_for("login"))
    uid = session["user_id"]
    base = """SELECT a.id,a.fecha,u.usuario,a.cliente,a.comentarios,
                     a.proxima_visita,a.firma_archivo,
                     (SELECT COUNT(*) FROM fotos f WHERE f.actividad_id=a.id) AS fotos_count
              FROM actividades a JOIN usuarios u ON u.id=a.usuario_id"""
    if can_see_all():
        acts = query(base + " ORDER BY a.fecha DESC", fetchall=True)
    else:
        acts = query(base + " WHERE a.usuario_id=%s ORDER BY a.fecha DESC",
                     (uid,), fetchall=True)
    return render_template("visitas.html", empresa=EMPRESA, logo=LOGO, actividades=acts)

@app.route("/visitas/guardar", methods=["POST"])
def guardar_visita():
    if not logged_in(): return redirect(url_for("login"))
    cliente    = request.form.get("cliente","").strip()
    comentarios= request.form.get("comentarios","").strip()
    proxima    = request.form.get("proxima_visita","").strip() or None
    firma_data = request.form.get("firma_data","").strip()
    fotos      = request.files.getlist("fotos")

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

    # Insertar actividad
    conn = get_db(); cur = conn.cursor()
    cur.execute("""INSERT INTO actividades
                   (usuario_id,fecha,cliente,comentarios,proxima_visita,firma_archivo)
                   VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                (session["user_id"], datetime.now().strftime("%Y-%m-%d %H:%M"),
                 cliente, comentarios, proxima, None))
    actividad_id = cur.fetchone()["id"]

    # Subir firma a Supabase Storage
    try:
        firma_url = upload_firma(firma_data, actividad_id)
        cur.execute("UPDATE actividades SET firma_archivo=%s WHERE id=%s",
                    (firma_url, actividad_id))
    except Exception as e:
        conn.rollback(); conn.close()
        flash(f"Error guardando firma: {e}", "danger")
        return redirect(url_for("visitas"))

    # Subir fotos a Supabase Storage
    try:
        for f in fotos_validas[:2]:
            url = upload_foto(f, actividad_id)
            cur.execute("INSERT INTO fotos (actividad_id,archivo) VALUES (%s,%s)",
                        (actividad_id, url))
    except Exception as e:
        conn.rollback(); conn.close()
        flash(f"Error guardando fotos: {e}", "danger")
        return redirect(url_for("visitas"))

    conn.commit(); cur.close(); conn.close()
    flash("Visita registrada correctamente ✅", "success")
    return redirect(url_for("visitas"))

@app.route("/visitas/detalle/<int:actividad_id>")
def detalle_visita(actividad_id):
    if not logged_in(): return redirect(url_for("login"))
    act = query("""SELECT a.*,u.usuario FROM actividades a
                   JOIN usuarios u ON u.id=a.usuario_id WHERE a.id=%s""",
                (actividad_id,), fetchone=True)
    if not act: abort(404)
    if (not can_see_all()) and act["usuario_id"] != session["user_id"]: abort(403)
    fotos = query("SELECT * FROM fotos WHERE actividad_id=%s ORDER BY id",
                  (actividad_id,), fetchall=True)
    return render_template("visitas_detalle.html", empresa=EMPRESA, logo=LOGO,
                           act=act, fotos=fotos)


# ── USUARIOS ──────────────────────────────────────────────
@app.route("/usuarios")
def usuarios():
    if not logged_in(): return redirect(url_for("login"))
    if not is_admin(): abort(403)
    ul = query("""SELECT id,usuario,nombre,apellido,email,rol,activo,fecha_creacion
                  FROM usuarios ORDER BY fecha_creacion DESC""", fetchall=True)
    return render_template("usuarios.html", empresa=EMPRESA, logo=LOGO, usuarios=ul)

@app.route("/usuarios/crear", methods=["POST"])
def crear_usuario():
    if not logged_in(): return redirect(url_for("login"))
    if not is_admin(): abort(403)
    usuario  = request.form.get("usuario","").strip()
    nombre   = request.form.get("nombre","").strip()
    apellido = request.form.get("apellido","").strip()
    email    = request.form.get("email","").strip()
    password = request.form.get("password","")
    rol      = request.form.get("rol","vendedor")
    if not usuario or not email or not password:
        flash("Usuario, email y password son obligatorios.", "danger")
        return redirect(url_for("usuarios"))
    try:
        query("""INSERT INTO usuarios
                 (usuario,nombre,apellido,email,password,rol,activo,fecha_creacion)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
              (usuario,nombre,apellido,email,
               generate_password_hash(password),
               rol, 1, datetime.now().strftime("%Y-%m-%d %H:%M")), commit=True)
        flash("Usuario creado ✅","success")
    except Exception:
        flash("Usuario o email ya existe.","danger")
    return redirect(url_for("usuarios"))

@app.route("/usuarios/actualizar", methods=["POST"])
def actualizar_usuario():
    if not logged_in(): return redirect(url_for("login"))
    if not is_admin(): abort(403)
    uid      = request.form.get("id")
    nombre   = request.form.get("nombre","").strip()
    apellido = request.form.get("apellido","").strip()
    email    = request.form.get("email","").strip()
    rol      = request.form.get("rol","vendedor")
    activo   = 1 if request.form.get("activo")=="1" else 0
    new_pw   = request.form.get("new_password","").strip()
    try:
        if new_pw:
            query("""UPDATE usuarios SET nombre=%s,apellido=%s,email=%s,
                     rol=%s,activo=%s,password=%s WHERE id=%s""",
                  (nombre,apellido,email,rol,activo,
                   generate_password_hash(new_pw),uid), commit=True)
        else:
            query("""UPDATE usuarios SET nombre=%s,apellido=%s,email=%s,
                     rol=%s,activo=%s WHERE id=%s""",
                  (nombre,apellido,email,rol,activo,uid), commit=True)
        flash("Usuario actualizado ✅","success")
    except Exception:
        flash("Email ya está en uso.","danger")
    return redirect(url_for("usuarios"))


if __name__ == "__main__":
    app.run(debug=True)
