import os, uuid, base64, json
from datetime import datetime, timedelta, date
from flask import Flask, render_template, request, redirect, url_for, session, abort, flash, jsonify
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

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

BUCKET_FOTOS  = "fotos"
BUCKET_FIRMAS = "firmas"
BUCKET_AVA    = "avatares"
ALLOWED_EXT   = {"png", "jpg", "jpeg", "webp"}

# ── PERMISOS BASE POR ROL (fallback si no hay permisos en BD) ─
PERMISOS_ROL = {
    "admin":      {"ver":True,  "crear":True,  "editar":True,  "eliminar":True},
    "gerente":    {"ver":True,  "crear":False, "editar":False, "eliminar":False},
    "supervisor": {"ver":True,  "crear":False, "editar":False, "eliminar":False},
    "vendedor":   {"ver":True,  "crear":True,  "editar":False, "eliminar":False},
}

MODULOS = ["visitas","calendario","clientes","usuarios","reportes","configuracion","permisos"]

def get_permisos_usuario(uid, modulo):
    """Obtiene permisos de un usuario para un módulo. Admin siempre tiene todo."""
    if session.get("rol") == "admin":
        return {"ver":True,"crear":True,"editar":True,"eliminar":True}
    try:
        p = query("SELECT * FROM permisos_usuario WHERE usuario_id=%s AND modulo=%s",
                  (uid, modulo), fetchone=True)
        if p:
            return {"ver":bool(p["puede_ver"]),"crear":bool(p["puede_crear"]),
                    "editar":bool(p["puede_editar"]),"eliminar":bool(p["puede_eliminar"])}
    except Exception:
        pass
    # Fallback a permisos por rol
    rol = session.get("rol","vendedor")
    return PERMISOS_ROL.get(rol, {"ver":True,"crear":False,"editar":False,"eliminar":False})

def tiene_permiso(accion, modulo="visitas"):
    """Chequea si el usuario actual tiene un permiso específico en un módulo."""
    uid = session.get("user_id")
    if not uid: return False
    if session.get("rol") == "admin": return True
    p = get_permisos_usuario(uid, modulo)
    return p.get(accion, False)

# ── DB ────────────────────────────────────────────────────
def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor,
                            options="-c statement_timeout=30000")
    return conn

def query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    conn = get_db(); cur = conn.cursor()
    cur.execute(sql, params)
    result = None
    if fetchone:  result = cur.fetchone()
    if fetchall:  result = cur.fetchall()
    if commit:    conn.commit()
    cur.close(); conn.close()
    return result

def init_db():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS usuarios (
        id SERIAL PRIMARY KEY, usuario TEXT UNIQUE NOT NULL,
        nombre TEXT DEFAULT '', apellido TEXT DEFAULT '',
        email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
        rol TEXT DEFAULT 'vendedor', activo INTEGER DEFAULT 1,
        fecha_creacion TEXT DEFAULT '',
        telefono TEXT DEFAULT '', zona TEXT DEFAULT '', foto_url TEXT DEFAULT '',
        supervisor_id INTEGER DEFAULT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS actividades (
        id SERIAL PRIMARY KEY, usuario_id INTEGER REFERENCES usuarios(id),
        fecha TEXT NOT NULL, cliente TEXT NOT NULL,
        comentarios TEXT DEFAULT '', proxima_visita TEXT DEFAULT NULL,
        firma_archivo TEXT DEFAULT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS fotos (
        id SERIAL PRIMARY KEY, actividad_id INTEGER REFERENCES actividades(id),
        archivo TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS eventos (
        id SERIAL PRIMARY KEY, usuario_id INTEGER REFERENCES usuarios(id),
        titulo TEXT NOT NULL, descripcion TEXT DEFAULT '',
        fecha_inicio TEXT NOT NULL, fecha_fin TEXT DEFAULT NULL,
        hora_inicio TEXT DEFAULT '', hora_fin TEXT DEFAULT '',
        tipo TEXT DEFAULT 'visita', color TEXT DEFAULT '#714B67',
        cliente TEXT DEFAULT '', ubicacion TEXT DEFAULT '',
        todo_el_dia INTEGER DEFAULT 0, creado_en TEXT DEFAULT ''
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS config (
        id INTEGER PRIMARY KEY, empresa TEXT DEFAULT 'Altasolucion',
        logo_url TEXT DEFAULT '', color_primario TEXT DEFAULT '#714B67',
        descripcion TEXT DEFAULT ''
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS solicitudes_reset (
        id SERIAL PRIMARY KEY, usuario_id INTEGER REFERENCES usuarios(id),
        email TEXT, fecha TEXT, atendido INTEGER DEFAULT 0
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS clientes (
        id SERIAL PRIMARY KEY,
        nombre TEXT NOT NULL, empresa TEXT DEFAULT '', cargo TEXT DEFAULT '',
        email TEXT DEFAULT '', telefono TEXT DEFAULT '', telefono2 TEXT DEFAULT '',
        direccion TEXT DEFAULT '', ciudad TEXT DEFAULT '', estado_dir TEXT DEFAULT '',
        pais TEXT DEFAULT 'Mexico', codigo_postal TEXT DEFAULT '',
        rfc TEXT DEFAULT '', razon_social TEXT DEFAULT '', uso_cfdi TEXT DEFAULT '',
        clasificacion TEXT DEFAULT 'prospecto', estado_semaforo TEXT DEFAULT 'verde',
        vendedor_id INTEGER REFERENCES usuarios(id),
        notas TEXT DEFAULT '', sitio_web TEXT DEFAULT '', industria TEXT DEFAULT '',
        empleados TEXT DEFAULT '', fuente TEXT DEFAULT '',
        activo INTEGER DEFAULT 1, creado_por INTEGER REFERENCES usuarios(id),
        fecha_creacion TEXT DEFAULT '', fecha_actualizacion TEXT DEFAULT ''
    )""")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cur.execute("""INSERT INTO usuarios (usuario,nombre,apellido,email,password,rol,activo,fecha_creacion)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (usuario) DO NOTHING""",
        ("admin","Admin","Sistema","admin@demo.com",generate_password_hash("admin123"),"admin",1,now))
    cur.execute("""INSERT INTO usuarios (usuario,nombre,apellido,email,password,rol,activo,fecha_creacion)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (usuario) DO NOTHING""",
        ("demo","Demo","Vendedor","demo@demo.com",generate_password_hash("1234"),"vendedor",1,now))
    conn.commit(); cur.close(); conn.close()

init_db()

# ── STORAGE ───────────────────────────────────────────────
def allowed_file(f): return "." in f and f.rsplit(".",1)[1].lower() in ALLOWED_EXT

def upload_foto(file_storage, actividad_id):
    filename = secure_filename(file_storage.filename)
    if not allowed_file(filename): raise ValueError("Formato no permitido")
    ext  = filename.rsplit(".",1)[1].lower()
    name = f"actividad_{actividad_id}/{uuid.uuid4().hex}.{ext}"
    data = file_storage.read()
    supabase.storage.from_(BUCKET_FOTOS).upload(name, data, {"content-type": f"image/{ext}"})
    return supabase.storage.from_(BUCKET_FOTOS).get_public_url(name)

def upload_firma(dataurl, actividad_id):
    if not dataurl or not dataurl.startswith("data:image"): raise ValueError("Firma invalida")
    _, b64 = dataurl.split(",", 1)
    name = f"actividad_{actividad_id}/{uuid.uuid4().hex}.png"
    supabase.storage.from_(BUCKET_FIRMAS).upload(name, base64.b64decode(b64), {"content-type":"image/png"})
    return supabase.storage.from_(BUCKET_FIRMAS).get_public_url(name)

def upload_avatar(file_storage, uid):
    ext  = secure_filename(file_storage.filename).rsplit(".",1)[1].lower()
    name = f"perfil_{uid}_{uuid.uuid4().hex}.{ext}"
    supabase.storage.from_(BUCKET_AVA).upload(name, file_storage.read(), {"content-type":f"image/{ext}"})
    return supabase.storage.from_(BUCKET_AVA).get_public_url(name)

# ── SESSION HELPERS ───────────────────────────────────────
def logged_in(): return "user_id" in session
def is_admin():  return session.get("rol") == "admin"
def can_see_all(): return session.get("rol") in ["admin","gerente"]

@app.context_processor
def inject_globals():
    uid = session.get("user_id")
    def get_perms(modulo):
        if not uid: return {}
        return get_permisos_usuario(uid, modulo)
    return {
        "now": lambda: datetime.now().strftime("%d/%m/%Y %H:%M"),
        "perms": get_perms("visitas"),
        "get_perms": get_perms,
    }

# ── LOGIN ─────────────────────────────────────────────────
@app.route("/")
def inicio(): return redirect(url_for("login"))

@app.route("/login", methods=["GET","POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("usuario","").strip()
        p = request.form.get("password","")
        user = query("SELECT * FROM usuarios WHERE usuario=%s AND activo=1",(u,),fetchone=True)
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
    session.clear(); return redirect(url_for("login"))

# ── DASHBOARD ─────────────────────────────────────────────
@app.route("/dashboard")
def dashboard():
    if not logged_in(): return redirect(url_for("login"))
    uid   = session["user_id"]
    today = datetime.now().strftime("%Y-%m-%d")
    if can_see_all():
        tv = query("SELECT COUNT(*) AS c FROM actividades",fetchone=True)["c"]
        vh = query("SELECT COUNT(*) AS c FROM actividades WHERE fecha LIKE %s",(today+"%",),fetchone=True)["c"]
        tu = query("SELECT COUNT(*) AS c FROM usuarios WHERE activo=1",fetchone=True)["c"]
        tf = query("SELECT COUNT(*) AS c FROM fotos",fetchone=True)["c"]
        vr = query("""SELECT a.id,a.fecha,u.usuario,a.cliente,a.comentarios FROM actividades a
                      JOIN usuarios u ON u.id=a.usuario_id ORDER BY a.fecha DESC LIMIT 5""",fetchall=True)
        # Eventos de hoy
        ev_hoy = query("SELECT COUNT(*) AS c FROM eventos WHERE fecha_inicio=%s",(today,),fetchone=True)["c"]
    else:
        tv = query("SELECT COUNT(*) AS c FROM actividades WHERE usuario_id=%s",(uid,),fetchone=True)["c"]
        vh = query("SELECT COUNT(*) AS c FROM actividades WHERE usuario_id=%s AND fecha LIKE %s",(uid,today+"%"),fetchone=True)["c"]
        tu = 0
        tf = query("""SELECT COUNT(*) AS c FROM fotos f JOIN actividades a ON f.actividad_id=a.id
                      WHERE a.usuario_id=%s""",(uid,),fetchone=True)["c"]
        vr = query("""SELECT a.id,a.fecha,u.usuario,a.cliente,a.comentarios FROM actividades a
                      JOIN usuarios u ON u.id=a.usuario_id WHERE a.usuario_id=%s
                      ORDER BY a.fecha DESC LIMIT 5""",(uid,),fetchall=True)
        ev_hoy = query("SELECT COUNT(*) AS c FROM eventos WHERE usuario_id=%s AND fecha_inicio=%s",(uid,today),fetchone=True)["c"]

    # Próximos eventos (3)
    proximos = query("""SELECT titulo,fecha_inicio,hora_inicio,tipo FROM eventos
        WHERE usuario_id=%s AND fecha_inicio >= %s ORDER BY fecha_inicio,hora_inicio LIMIT 3""",
        (uid, today), fetchall=True) if not can_see_all() else query(
        """SELECT e.titulo,e.fecha_inicio,e.hora_inicio,e.tipo,u.usuario FROM eventos e
           JOIN usuarios u ON u.id=e.usuario_id WHERE e.fecha_inicio >= %s
           ORDER BY e.fecha_inicio,e.hora_inicio LIMIT 5""",(today,),fetchall=True)

    stats = {"total_visitas":tv,"visitas_hoy":vh,"total_usuarios":tu,"total_fotos":tf,"eventos_hoy":ev_hoy}
    return render_template("dashboard.html", empresa=EMPRESA, logo=LOGO,
                           rol=session["rol"], stats=stats, visitas_recientes=vr, proximos=proximos)

# ── VISITAS ───────────────────────────────────────────────
@app.route("/visitas")
def visitas():
    if not logged_in(): return redirect(url_for("login"))
    uid = session["user_id"]
    rol = session["rol"]
    base = """SELECT a.id,a.fecha,u.usuario,a.cliente,a.comentarios,
                     a.proxima_visita,a.firma_archivo,
                     (SELECT COUNT(*) FROM fotos f WHERE f.actividad_id=a.id) AS fotos_count
              FROM actividades a JOIN usuarios u ON u.id=a.usuario_id"""
    if can_see_all():
        acts = query(base+" ORDER BY a.fecha DESC",fetchall=True)
    elif rol == "supervisor":
        # Supervisor ve a sus subordinados
        subs = query("SELECT id FROM usuarios WHERE supervisor_id=%s",(uid,),fetchall=True)
        ids  = [s["id"] for s in subs] + [uid]
        ph   = ",".join(["%s"]*len(ids))
        acts = query(f"{base} WHERE a.usuario_id IN ({ph}) ORDER BY a.fecha DESC",tuple(ids),fetchall=True)
    else:
        acts = query(base+" WHERE a.usuario_id=%s ORDER BY a.fecha DESC",(uid,),fetchall=True)
    return render_template("visitas.html", empresa=EMPRESA, logo=LOGO, actividades=acts)

@app.route("/visitas/guardar", methods=["POST"])
def guardar_visita():
    if not logged_in(): return redirect(url_for("login"))
    if not tiene_permiso("crear", "visitas"):
        flash("No tienes permiso para crear visitas.","danger")
        return redirect(url_for("visitas"))
    cliente    = request.form.get("cliente","").strip()
    comentarios= request.form.get("comentarios","").strip()
    proxima    = request.form.get("proxima_visita","").strip() or None
    firma_data = request.form.get("firma_data","").strip()
    fotos      = request.files.getlist("fotos")
    if not cliente or not comentarios:
        flash("Cliente y comentarios son obligatorios.","danger"); return redirect(url_for("visitas"))
    fotos_validas = [f for f in fotos if f and f.filename]
    if len(fotos_validas) < 2:
        flash("Debes subir 2 fotos obligatorias.","danger"); return redirect(url_for("visitas"))
    if not firma_data or not firma_data.startswith("data:image"):
        flash("La firma es obligatoria.","danger"); return redirect(url_for("visitas"))
    conn = get_db(); cur = conn.cursor()
    cur.execute("""INSERT INTO actividades (usuario_id,fecha,cliente,comentarios,proxima_visita,firma_archivo)
                   VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                (session["user_id"],datetime.now().strftime("%Y-%m-%d %H:%M"),cliente,comentarios,proxima,None))
    actividad_id = cur.fetchone()["id"]
    try:
        firma_url = upload_firma(firma_data, actividad_id)
        cur.execute("UPDATE actividades SET firma_archivo=%s WHERE id=%s",(firma_url,actividad_id))
    except Exception as e:
        conn.rollback(); conn.close(); flash(f"Error guardando firma: {e}","danger"); return redirect(url_for("visitas"))
    try:
        for f in fotos_validas[:2]:
            url = upload_foto(f, actividad_id)
            cur.execute("INSERT INTO fotos (actividad_id,archivo) VALUES (%s,%s)",(actividad_id,url))
    except Exception as e:
        conn.rollback(); conn.close(); flash(f"Error guardando fotos: {e}","danger"); return redirect(url_for("visitas"))
    conn.commit(); cur.close(); conn.close()
    flash("Visita registrada correctamente","success")
    return redirect(url_for("visitas"))

@app.route("/visitas/eliminar/<int:actividad_id>", methods=["POST"])
def eliminar_visita(actividad_id):
    if not logged_in(): return redirect(url_for("login"))
    if not tiene_permiso("eliminar", "visitas"):
        flash("No tienes permiso para eliminar visitas.","danger"); return redirect(url_for("visitas"))
    query("DELETE FROM fotos WHERE actividad_id=%s",(actividad_id,),commit=True)
    query("DELETE FROM actividades WHERE id=%s",(actividad_id,),commit=True)
    flash("Visita eliminada","success")
    return redirect(url_for("visitas"))

@app.route("/visitas/detalle/<int:actividad_id>")
def detalle_visita(actividad_id):
    if not logged_in(): return redirect(url_for("login"))
    act = query("""SELECT a.*,u.usuario FROM actividades a JOIN usuarios u ON u.id=a.usuario_id WHERE a.id=%s""",
                (actividad_id,),fetchone=True)
    if not act: abort(404)
    if (not can_see_all()) and act["usuario_id"] != session["user_id"]: abort(403)
    fotos = query("SELECT * FROM fotos WHERE actividad_id=%s ORDER BY id",(actividad_id,),fetchall=True)
    return render_template("visitas_detalle.html", empresa=EMPRESA, logo=LOGO, act=act, fotos=fotos)

# ── CALENDARIO ────────────────────────────────────────────
@app.route("/calendario")
def calendario():
    if not logged_in(): return redirect(url_for("login"))
    uid = session["user_id"]
    # Para admin/gerente: selector de usuario
    if can_see_all():
        users = query("SELECT id,usuario,nombre,apellido,rol FROM usuarios WHERE activo=1 ORDER BY nombre",fetchall=True)
    elif session["rol"] == "supervisor":
        users = query("SELECT id,usuario,nombre,apellido,rol FROM usuarios WHERE supervisor_id=%s OR id=%s ORDER BY nombre",(uid,uid),fetchall=True)
    else:
        users = []
    return render_template("calendario.html", empresa=EMPRESA, logo=LOGO, users=users)

@app.route("/calendario/eventos")
def calendario_eventos():
    if not logged_in(): return redirect(url_for("login"))
    uid      = session["user_id"]
    rol      = session["rol"]
    ver_uid  = request.args.get("usuario_id", uid)
    start    = request.args.get("start","")
    end      = request.args.get("end","")

    # Permisos de visibilidad
    if can_see_all():
        pass  # puede ver cualquier usuario
    elif rol == "supervisor":
        subs = [s["id"] for s in query("SELECT id FROM usuarios WHERE supervisor_id=%s",(uid,),fetchall=True)]
        if int(ver_uid) not in subs and int(ver_uid) != uid:
            ver_uid = uid
    else:
        ver_uid = uid

    eventos = query("""SELECT e.*,u.usuario AS user_name FROM eventos e
                       JOIN usuarios u ON u.id=e.usuario_id
                       WHERE e.usuario_id=%s AND e.fecha_inicio >= %s AND e.fecha_inicio <= %s
                       ORDER BY e.fecha_inicio,e.hora_inicio""",
                    (ver_uid, start[:10] if start else "2000-01-01",
                     end[:10] if end else "2099-12-31"), fetchall=True)

    result = []
    for e in eventos:
        color = e.get("color","#714B67")
        fi = e["fecha_inicio"]
        hi = e.get("hora_inicio","") or "00:00"
        ff = e.get("fecha_fin") or fi
        hf = e.get("hora_fin","") or "23:59"
        result.append({
            "id": e["id"],
            "title": e["titulo"],
            "start": f"{fi}T{hi}" if hi else fi,
            "end":   f"{ff}T{hf}" if hf else ff,
            "color": color,
            "extendedProps": {
                "descripcion": e.get("descripcion",""),
                "cliente":     e.get("cliente",""),
                "ubicacion":   e.get("ubicacion",""),
                "tipo":        e.get("tipo","visita"),
                "usuario":     e.get("user_name",""),
                "todo_el_dia": e.get("todo_el_dia",0),
            }
        })
    return jsonify(result)

@app.route("/calendario/crear", methods=["POST"])
def calendario_crear():
    if not logged_in(): return jsonify({"ok":False,"msg":"No autenticado"}), 401
    if not tiene_permiso("crear", "visitas"):
        return jsonify({"ok":False,"msg":"Sin permiso"}), 403
    data = request.get_json()
    uid  = session["user_id"]
    try:
        query("""INSERT INTO eventos (usuario_id,titulo,descripcion,fecha_inicio,fecha_fin,
                 hora_inicio,hora_fin,tipo,color,cliente,ubicacion,todo_el_dia,creado_en)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              (uid, data.get("titulo","Sin título"), data.get("descripcion",""),
               data.get("fecha_inicio"), data.get("fecha_fin",""),
               data.get("hora_inicio",""), data.get("hora_fin",""),
               data.get("tipo","visita"), data.get("color","#714B67"),
               data.get("cliente",""), data.get("ubicacion",""),
               1 if data.get("todo_el_dia") else 0,
               datetime.now().strftime("%Y-%m-%d %H:%M")), commit=True)
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)}), 500

@app.route("/calendario/eliminar/<int:evento_id>", methods=["POST"])
def calendario_eliminar(evento_id):
    if not logged_in(): return jsonify({"ok":False}), 401
    ev = query("SELECT * FROM eventos WHERE id=%s",(evento_id,),fetchone=True)
    if not ev: return jsonify({"ok":False}), 404
    if ev["usuario_id"] != session["user_id"] and not tiene_permiso("eliminar"):
        return jsonify({"ok":False,"msg":"Sin permiso"}), 403
    query("DELETE FROM eventos WHERE id=%s",(evento_id,),commit=True)
    return jsonify({"ok":True})

# ── USUARIOS ──────────────────────────────────────────────
@app.route("/usuarios")
def usuarios():
    if not logged_in(): return redirect(url_for("login"))
    if not is_admin(): abort(403)
    ul = query("""SELECT u.id,u.usuario,u.nombre,u.apellido,u.email,u.rol,u.activo,
                  u.fecha_creacion,u.telefono,u.zona,s.usuario AS supervisor_nombre
                  FROM usuarios u LEFT JOIN usuarios s ON s.id=u.supervisor_id
                  ORDER BY u.fecha_creacion DESC""",fetchall=True)
    all_users = query("SELECT id,usuario,nombre FROM usuarios WHERE activo=1 ORDER BY nombre",fetchall=True)
    return render_template("usuarios.html", empresa=EMPRESA, logo=LOGO, usuarios=ul, all_users=all_users)

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
    telefono = request.form.get("telefono","").strip()
    zona     = request.form.get("zona","").strip()
    sup_id   = request.form.get("supervisor_id","").strip() or None
    if not usuario or not email or not password:
        flash("Usuario, email y password son obligatorios.","danger"); return redirect(url_for("usuarios"))
    try:
        query("""INSERT INTO usuarios (usuario,nombre,apellido,email,password,rol,activo,fecha_creacion,telefono,zona,supervisor_id)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              (usuario,nombre,apellido,email,generate_password_hash(password),
               rol,1,datetime.now().strftime("%Y-%m-%d %H:%M"),telefono,zona,sup_id),commit=True)
        flash("Usuario creado","success")
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
    sup_id   = request.form.get("supervisor_id","").strip() or None
    try:
        if new_pw:
            query("UPDATE usuarios SET nombre=%s,apellido=%s,email=%s,rol=%s,activo=%s,password=%s,supervisor_id=%s WHERE id=%s",
                  (nombre,apellido,email,rol,activo,generate_password_hash(new_pw),sup_id,uid),commit=True)
        else:
            query("UPDATE usuarios SET nombre=%s,apellido=%s,email=%s,rol=%s,activo=%s,supervisor_id=%s WHERE id=%s",
                  (nombre,apellido,email,rol,activo,sup_id,uid),commit=True)
        flash("Usuario actualizado","success")
    except Exception:
        flash("Email ya está en uso.","danger")
    return redirect(url_for("usuarios"))

# ── PERFIL ────────────────────────────────────────────────
@app.route("/perfil", methods=["GET","POST"])
def perfil():
    if not logged_in(): return redirect(url_for("login"))
    uid  = session["user_id"]
    user = query("SELECT * FROM usuarios WHERE id=%s",(uid,),fetchone=True)
    if request.method == "POST":
        accion = request.form.get("accion","")
        if accion == "perfil":
            nombre   = request.form.get("nombre","").strip()
            apellido = request.form.get("apellido","").strip()
            email    = request.form.get("email","").strip()
            telefono = request.form.get("telefono","").strip()
            zona     = request.form.get("zona","").strip()
            foto_url = user.get("foto_url") or ""
            foto = request.files.get("foto_perfil")
            if foto and foto.filename and allowed_file(foto.filename):
                try: foto_url = upload_avatar(foto, uid)
                except Exception as e: flash(f"Error subiendo foto: {e}","danger")
            try:
                query("UPDATE usuarios SET nombre=%s,apellido=%s,email=%s,telefono=%s,zona=%s,foto_url=%s WHERE id=%s",
                      (nombre,apellido,email,telefono,zona,foto_url,uid),commit=True)
                flash("Perfil actualizado","success")
            except Exception: flash("El email ya esta en uso.","danger")
        elif accion == "password":
            actual   = request.form.get("password_actual","")
            nueva    = request.form.get("password_nueva","")
            confirma = request.form.get("password_confirma","")
            if not check_password_hash(user["password"],actual): flash("La contrasena actual es incorrecta.","danger")
            elif nueva != confirma: flash("Las contrasenas no coinciden.","danger")
            elif len(nueva) < 4: flash("Minimo 4 caracteres.","danger")
            else:
                query("UPDATE usuarios SET password=%s WHERE id=%s",(generate_password_hash(nueva),uid),commit=True)
                flash("Contrasena cambiada","success")
        return redirect(url_for("perfil"))
    historial = query("""SELECT fecha,cliente,comentarios FROM actividades
                         WHERE usuario_id=%s ORDER BY fecha DESC LIMIT 10""",(uid,),fetchall=True)
    return render_template("perfil.html", empresa=EMPRESA, logo=LOGO, user=user, historial=historial)

# ── CONFIGURACION ─────────────────────────────────────────
@app.route("/configuracion", methods=["GET","POST"])
def configuracion():
    if not logged_in(): return redirect(url_for("login"))
    if not is_admin(): abort(403)
    config = query("SELECT * FROM config WHERE id=1",fetchone=True)
    if not config:
        query("INSERT INTO config (id,empresa,logo_url,color_primario,descripcion) VALUES (1,%s,%s,%s,%s)",
              (EMPRESA,"","#714B67",""),commit=True)
        config = query("SELECT * FROM config WHERE id=1",fetchone=True)
    if request.method == "POST":
        empresa     = request.form.get("empresa","").strip() or EMPRESA
        color       = request.form.get("color_primario","#714B67").strip()
        descripcion = request.form.get("descripcion","").strip()
        logo_url    = config.get("logo_url","")
        logo = request.files.get("logo")
        if logo and logo.filename and allowed_file(logo.filename):
            try: logo_url = upload_avatar(logo, "logo")
            except Exception as e: flash(f"Error: {e}","danger")
        query("UPDATE config SET empresa=%s,logo_url=%s,color_primario=%s,descripcion=%s WHERE id=1",
              (empresa,logo_url,color,descripcion),commit=True)
        flash("Configuracion guardada","success")
        return redirect(url_for("configuracion"))
    stats = {
        "usuarios": query("SELECT COUNT(*) AS c FROM usuarios WHERE activo=1",fetchone=True)["c"],
        "visitas":  query("SELECT COUNT(*) AS c FROM actividades",fetchone=True)["c"],
        "fotos":    query("SELECT COUNT(*) AS c FROM fotos",fetchone=True)["c"],
        "eventos":  query("SELECT COUNT(*) AS c FROM eventos",fetchone=True)["c"],
    }
    return render_template("configuracion.html", empresa=EMPRESA, logo=LOGO, config=config, stats=stats)

# ── OLVIDE PASSWORD ───────────────────────────────────────
@app.route("/olvide-password", methods=["GET","POST"])
def olvide_password():
    msg = None
    if request.method == "POST":
        email = request.form.get("email","").strip()
        user  = query("SELECT * FROM usuarios WHERE email=%s AND activo=1",(email,),fetchone=True)
        msg   = "Si el email existe en el sistema, el administrador recibira tu solicitud."
        if user:
            try:
                query("INSERT INTO solicitudes_reset (usuario_id,email,fecha) VALUES (%s,%s,%s)",
                      (user["id"],email,datetime.now().strftime("%Y-%m-%d %H:%M")),commit=True)
            except Exception: pass
    return render_template("olvide_password.html", empresa=EMPRESA, logo=LOGO, msg=msg)


# ── PERFILES Y PERMISOS ───────────────────────────────────
@app.route("/permisos")
def permisos_modulo():
    if not logged_in(): return redirect(url_for("login"))
    if not is_admin(): abort(403)

    usuarios_list = query("""SELECT id,usuario,nombre,apellido,rol,activo
                             FROM usuarios ORDER BY nombre""", fetchall=True)

    # Construir matriz: {uid: {modulo: {ver,crear,editar,eliminar}}}
    all_perms = query("SELECT * FROM permisos_usuario", fetchall=True) or []
    perms_map = {}
    for p in all_perms:
        uid = p["usuario_id"]
        if uid not in perms_map: perms_map[uid] = {}
        perms_map[uid][p["modulo"]] = {
            "ver": bool(p["puede_ver"]),
            "crear": bool(p["puede_crear"]),
            "editar": bool(p["puede_editar"]),
            "eliminar": bool(p["puede_eliminar"]),
        }

    # Para usuarios sin permisos en BD, usar defaults de rol
    for u in usuarios_list:
        uid = u["id"]
        if uid not in perms_map:
            perms_map[uid] = {}
        rol = u["rol"]
        base = PERMISOS_ROL.get(rol, {"ver":True,"crear":False,"editar":False,"eliminar":False})
        for m in MODULOS:
            if m not in perms_map[uid]:
                perms_map[uid][m] = base.copy()

    return render_template("permisos.html", empresa=EMPRESA, logo=LOGO,
                           usuarios=usuarios_list, modulos=MODULOS, perms_map=perms_map)


@app.route("/permisos/guardar", methods=["POST"])
def permisos_guardar():
    if not logged_in(): return redirect(url_for("login"))
    if not is_admin(): abort(403)

    data = request.get_json()
    if not data: return jsonify({"ok": False, "msg": "Sin datos"}), 400

    uid    = data.get("usuario_id")
    modulo = data.get("modulo")
    accion = data.get("accion")  # ver/crear/editar/eliminar
    valor  = 1 if data.get("valor") else 0

    col_map = {"ver":"puede_ver","crear":"puede_crear",
               "editar":"puede_editar","eliminar":"puede_eliminar"}
    col = col_map.get(accion)
    if not col or modulo not in MODULOS:
        return jsonify({"ok": False, "msg": "Parametro invalido"}), 400

    try:
        # Upsert
        existing = query("SELECT id FROM permisos_usuario WHERE usuario_id=%s AND modulo=%s",
                         (uid, modulo), fetchone=True)
        if existing:
            query(f"UPDATE permisos_usuario SET {col}=%s WHERE usuario_id=%s AND modulo=%s",
                  (valor, uid, modulo), commit=True)
        else:
            # Insert con defaults del rol
            u = query("SELECT rol FROM usuarios WHERE id=%s", (uid,), fetchone=True)
            base = PERMISOS_ROL.get(u["rol"] if u else "vendedor",
                                    {"ver":1,"crear":0,"editar":0,"eliminar":0})
            vals = {k: 1 if v else 0 for k,v in base.items()}
            vals[accion] = valor
            query("""INSERT INTO permisos_usuario
                     (usuario_id,modulo,puede_ver,puede_crear,puede_editar,puede_eliminar)
                     VALUES (%s,%s,%s,%s,%s,%s)""",
                  (uid, modulo, vals["ver"], vals["crear"],
                   vals["editar"], vals["eliminar"]), commit=True)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@app.route("/permisos/reset/<int:uid>", methods=["POST"])
def permisos_reset(uid):
    """Resetea permisos de un usuario a los defaults de su rol."""
    if not logged_in(): return redirect(url_for("login"))
    if not is_admin(): abort(403)
    u = query("SELECT rol FROM usuarios WHERE id=%s", (uid,), fetchone=True)
    if not u: abort(404)
    base = PERMISOS_ROL.get(u["rol"], {"ver":True,"crear":False,"editar":False,"eliminar":False})
    query("DELETE FROM permisos_usuario WHERE usuario_id=%s", (uid,), commit=True)
    for m in MODULOS:
        query("""INSERT INTO permisos_usuario
                 (usuario_id,modulo,puede_ver,puede_crear,puede_editar,puede_eliminar)
                 VALUES (%s,%s,%s,%s,%s,%s)""",
              (uid, m, 1 if base["ver"] else 0, 1 if base["crear"] else 0,
               1 if base["editar"] else 0, 1 if base["eliminar"] else 0), commit=True)
    flash("Permisos restablecidos al rol por defecto","success")
    return redirect(url_for("permisos_modulo"))



# ── CLIENTES / CRM ────────────────────────────────────────
CLASIFICACIONES = ["prospecto","cliente activo","cliente inactivo","ex-cliente","partner"]
SEMAFOROS = {"verde":"#16a34a","amarillo":"#f59e0b","rojo":"#c5221f"}
INDUSTRIAS = ["Tecnología","Manufactura","Comercio","Servicios","Salud","Educación",
              "Construcción","Alimentos","Transporte","Finanzas","Otro"]
FUENTES = ["Referido","Web","Redes sociales","Llamada en frío","Evento","Otro"]

@app.route("/clientes")
def clientes():
    if not logged_in(): return redirect(url_for("login"))
    uid = session["user_id"]
    rol = session["rol"]
    buscar = request.args.get("q","").strip()
    clasificacion = request.args.get("clasificacion","")
    semaforo = request.args.get("semaforo","")

    base = """SELECT c.*,u.nombre AS vendedor_nombre, u.usuario AS vendedor_usuario,
              (SELECT COUNT(*) FROM actividades a WHERE a.cliente=c.nombre) AS total_visitas,
              (SELECT MAX(a.fecha) FROM actividades a WHERE a.cliente=c.nombre) AS ultima_visita,
              (SELECT MIN(a.proxima_visita) FROM actividades a WHERE a.cliente=c.nombre
               AND a.proxima_visita >= CURRENT_DATE::text) AS proxima_visita
              FROM clientes c LEFT JOIN usuarios u ON u.id=c.vendedor_id
              WHERE c.activo=1"""
    params = []

    if not can_see_all() and rol != "supervisor":
        base += " AND c.vendedor_id=%s"; params.append(uid)

    if buscar:
        base += " AND (c.nombre ILIKE %s OR c.empresa ILIKE %s OR c.email ILIKE %s)"
        params += [f"%{buscar}%",f"%{buscar}%",f"%{buscar}%"]
    if clasificacion:
        base += " AND c.clasificacion=%s"; params.append(clasificacion)
    if semaforo:
        base += " AND c.estado_semaforo=%s"; params.append(semaforo)

    base += " ORDER BY c.fecha_actualizacion DESC, c.fecha_creacion DESC"
    lista = query(base, tuple(params), fetchall=True) or []

    vendedores = query("SELECT id,nombre,usuario FROM usuarios WHERE activo=1 ORDER BY nombre",fetchall=True) or []
    return render_template("clientes.html", empresa=EMPRESA, logo=LOGO,
                           clientes=lista, vendedores=vendedores,
                           clasificaciones=CLASIFICACIONES, industrias=INDUSTRIAS,
                           fuentes=FUENTES, semaforos=SEMAFOROS,
                           q=buscar, fil_clas=clasificacion, fil_sem=semaforo)

@app.route("/clientes/crear", methods=["POST"])
def crear_cliente():
    if not logged_in(): return redirect(url_for("login"))
    if not tiene_permiso("crear","clientes"):
        flash("Sin permiso para crear clientes.","danger"); return redirect(url_for("clientes"))
    uid = session["user_id"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    nombre = request.form.get("nombre","").strip()
    if not nombre:
        flash("El nombre es obligatorio.","danger"); return redirect(url_for("clientes"))
    try:
        query("""INSERT INTO clientes
            (nombre,empresa,cargo,email,telefono,telefono2,direccion,ciudad,estado_dir,
             pais,codigo_postal,rfc,razon_social,uso_cfdi,clasificacion,estado_semaforo,
             vendedor_id,notas,sitio_web,industria,empleados,fuente,
             activo,creado_por,fecha_creacion,fecha_actualizacion)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (nombre,
             request.form.get("empresa","").strip(),
             request.form.get("cargo","").strip(),
             request.form.get("email","").strip(),
             request.form.get("telefono","").strip(),
             request.form.get("telefono2","").strip(),
             request.form.get("direccion","").strip(),
             request.form.get("ciudad","").strip(),
             request.form.get("estado_dir","").strip(),
             request.form.get("pais","México").strip(),
             request.form.get("codigo_postal","").strip(),
             request.form.get("rfc","").strip().upper(),
             request.form.get("razon_social","").strip(),
             request.form.get("uso_cfdi","").strip(),
             request.form.get("clasificacion","prospecto"),
             request.form.get("estado_semaforo","verde"),
             request.form.get("vendedor_id") or uid,
             request.form.get("notas","").strip(),
             request.form.get("sitio_web","").strip(),
             request.form.get("industria","").strip(),
             request.form.get("empleados","").strip(),
             request.form.get("fuente","").strip(),
             1, uid, now, now), commit=True)
        flash("Cliente creado correctamente ✅","success")
    except Exception as e:
        flash(f"Error: {e}","danger")
    return redirect(url_for("clientes"))

@app.route("/clientes/<int:cliente_id>")
def detalle_cliente(cliente_id):
    if not logged_in(): return redirect(url_for("login"))
    c = query("""SELECT c.*,u.nombre AS vendedor_nombre,u.usuario AS vendedor_usuario
                 FROM clientes c LEFT JOIN usuarios u ON u.id=c.vendedor_id
                 WHERE c.id=%s AND c.activo=1""",(cliente_id,),fetchone=True)
    if not c: abort(404)
    uid = session["user_id"]
    if not can_see_all() and c["vendedor_id"] != uid: abort(403)

    # Historial de visitas relacionadas al cliente
    visitas = query("""SELECT a.*,u.usuario AS vendedor FROM actividades a
                       JOIN usuarios u ON u.id=a.usuario_id
                       WHERE a.cliente ILIKE %s ORDER BY a.fecha DESC LIMIT 20""",
                    (f"%{c['nombre']}%",), fetchall=True) or []

    # Próxima visita
    proxima = query("""SELECT a.*,u.usuario AS vendedor FROM actividades a
                       JOIN usuarios u ON u.id=a.usuario_id
                       WHERE a.cliente ILIKE %s AND a.proxima_visita >= CURRENT_DATE::text
                       ORDER BY a.proxima_visita LIMIT 1""",
                    (f"%{c['nombre']}%",), fetchone=True)

    vendedores = query("SELECT id,nombre,usuario FROM usuarios WHERE activo=1 ORDER BY nombre",fetchall=True) or []
    return render_template("cliente_detalle.html", empresa=EMPRESA, logo=LOGO,
                           c=c, visitas=visitas, proxima=proxima,
                           vendedores=vendedores, clasificaciones=CLASIFICACIONES,
                           industrias=INDUSTRIAS, fuentes=FUENTES, semaforos=SEMAFOROS)

@app.route("/clientes/<int:cliente_id>/editar", methods=["POST"])
def editar_cliente(cliente_id):
    if not logged_in(): return redirect(url_for("login"))
    if not tiene_permiso("editar","clientes"):
        flash("Sin permiso para editar clientes.","danger")
        return redirect(url_for("detalle_cliente", cliente_id=cliente_id))
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        query("""UPDATE clientes SET
            nombre=%s,empresa=%s,cargo=%s,email=%s,telefono=%s,telefono2=%s,
            direccion=%s,ciudad=%s,estado_dir=%s,pais=%s,codigo_postal=%s,
            rfc=%s,razon_social=%s,uso_cfdi=%s,clasificacion=%s,estado_semaforo=%s,
            vendedor_id=%s,notas=%s,sitio_web=%s,industria=%s,empleados=%s,
            fuente=%s,fecha_actualizacion=%s WHERE id=%s""",
            (request.form.get("nombre","").strip(),
             request.form.get("empresa","").strip(),
             request.form.get("cargo","").strip(),
             request.form.get("email","").strip(),
             request.form.get("telefono","").strip(),
             request.form.get("telefono2","").strip(),
             request.form.get("direccion","").strip(),
             request.form.get("ciudad","").strip(),
             request.form.get("estado_dir","").strip(),
             request.form.get("pais","México").strip(),
             request.form.get("codigo_postal","").strip(),
             request.form.get("rfc","").strip().upper(),
             request.form.get("razon_social","").strip(),
             request.form.get("uso_cfdi","").strip(),
             request.form.get("clasificacion","prospecto"),
             request.form.get("estado_semaforo","verde"),
             request.form.get("vendedor_id") or session["user_id"],
             request.form.get("notas","").strip(),
             request.form.get("sitio_web","").strip(),
             request.form.get("industria","").strip(),
             request.form.get("empleados","").strip(),
             request.form.get("fuente","").strip(),
             now, cliente_id), commit=True)
        flash("Cliente actualizado ✅","success")
    except Exception as e:
        flash(f"Error: {e}","danger")
    return redirect(url_for("detalle_cliente", cliente_id=cliente_id))

@app.route("/clientes/<int:cliente_id>/eliminar", methods=["POST"])
def eliminar_cliente(cliente_id):
    if not logged_in(): return redirect(url_for("login"))
    if not tiene_permiso("eliminar","clientes"):
        flash("Sin permiso para eliminar clientes.","danger"); return redirect(url_for("clientes"))
    query("UPDATE clientes SET activo=0 WHERE id=%s",(cliente_id,),commit=True)
    flash("Cliente eliminado","success")
    return redirect(url_for("clientes"))


# ── BÚSQUEDA DE CLIENTES (autocomplete) ───────────────────
@app.route("/clientes/buscar")
def buscar_clientes():
    if not logged_in(): return jsonify([])
    q   = request.args.get("q","").strip()
    uid = session["user_id"]
    rol = session["rol"]
    if len(q) < 1: return jsonify([])

    # Limpiar el término — quitar asteriscos y espacios extra
    q_clean = q.replace("*","").replace("?","").strip()
    if not q_clean: return jsonify([])

    resultados = []
    param = f"%{q_clean}%"

    # 1. Buscar en tabla clientes
    sql_clientes = """SELECT id, nombre, empresa, telefono, clasificacion, estado_semaforo,
                      'clientes' AS fuente
                      FROM clientes WHERE activo=1
                      AND (nombre ILIKE %s OR empresa ILIKE %s)"""
    params = [param, param]
    if not can_see_all() and rol not in ["supervisor"]:
        sql_clientes += " AND (vendedor_id=%s OR vendedor_id IS NULL)"
        params.append(uid)
    sql_clientes += " ORDER BY nombre LIMIT 8"
    rows = query(sql_clientes, tuple(params), fetchall=True) or []
    for r in rows:
        resultados.append({
            "id":            r["id"],
            "nombre":        r["nombre"],
            "empresa":       r["empresa"] or "",
            "telefono":      r["telefono"] or "",
            "clasificacion": r["clasificacion"] or "cliente",
            "semaforo":      r["estado_semaforo"] or "verde",
            "fuente":        "CRM",
        })

    # 2. Buscar en tabla sap_business_partners (si existe)
    nombres_ya = {r["nombre"].lower() for r in resultados}
    try:
        # Detectar columnas disponibles en sap_business_partners
        sap_rows = query("""SELECT * FROM sap_business_partners
                            WHERE "CardName" ILIKE %s
                            OR "CardForeignName" ILIKE %s
                            LIMIT 8""", (param, param), fetchall=True) or []
        for r in sap_rows:
            nombre = r.get("CardName") or r.get("cardname") or ""
            if not nombre or nombre.lower() in nombres_ya:
                continue
            resultados.append({
                "id":            None,
                "nombre":        nombre,
                "empresa":       r.get("CardForeignName") or r.get("cardforeignname") or nombre,
                "telefono":      r.get("Phone1") or r.get("phone1") or "",
                "clasificacion": "SAP",
                "semaforo":      "verde",
                "fuente":        "SAP",
            })
            nombres_ya.add(nombre.lower())
    except Exception:
        pass  # La tabla SAP puede no existir o tener otro esquema

    # Ordenar por nombre y limitar a 10
    resultados.sort(key=lambda x: x["nombre"].lower())
    return jsonify(resultados[:10])

# ── ERROR HANDLERS ────────────────────────────────────────
@app.errorhandler(403)
def error_403(e):
    return render_template("403.html"), 403

@app.errorhandler(404)
def error_404(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def error_500(e):
    return render_template("404.html"), 500

if __name__ == "__main__":
    app.run(debug=True)
