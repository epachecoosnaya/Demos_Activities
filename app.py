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

# ── SAP Service Layer config ──────────────────────────────
SAP_BASE_URL   = os.environ.get("SAP_BASE_URL","").rstrip("/")
SAP_COMPANY_DB = os.environ.get("SAP_COMPANY_DB","")
SAP_USER       = os.environ.get("SAP_USER","")
SAP_PASSWORD   = os.environ.get("SAP_PASSWORD","")
SAP_VERIFY_SSL = os.environ.get("SAP_VERIFY_SSL","false").lower() == "true"

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

MODULOS = ["visitas","calendario","clientes","servicios","cotizaciones","almacenes","articulos","inventario","compras","ventas","usuarios","reportes","configuracion","permisos"]

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
    cur.execute("""CREATE TABLE IF NOT EXISTS cotizaciones (
        id SERIAL PRIMARY KEY, folio TEXT UNIQUE,
        cliente_id INTEGER REFERENCES clientes(id),
        cliente_nombre TEXT DEFAULT '', estatus TEXT DEFAULT 'borrador',
        validez_dias INTEGER DEFAULT 15, moneda TEXT DEFAULT 'MXN',
        descuento_global NUMERIC(5,2) DEFAULT 0,
        subtotal NUMERIC(18,2) DEFAULT 0,
        descuento_monto NUMERIC(18,2) DEFAULT 0,
        impuesto NUMERIC(18,2) DEFAULT 0,
        total NUMERIC(18,2) DEFAULT 0,
        notas TEXT DEFAULT '', condiciones TEXT DEFAULT '',
        creado_por INTEGER REFERENCES usuarios(id),
        fecha_creacion TEXT DEFAULT '', fecha_actualizacion TEXT DEFAULT '',
        fecha_vencimiento TEXT DEFAULT ''
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS cotizaciones_items (
        id SERIAL PRIMARY KEY,
        cotizacion_id INTEGER REFERENCES cotizaciones(id) ON DELETE CASCADE,
        item_code TEXT, item_nombre TEXT, uom TEXT DEFAULT '',
        cantidad NUMERIC(18,3) DEFAULT 1,
        precio_unitario NUMERIC(18,2) DEFAULT 0,
        descuento NUMERIC(5,2) DEFAULT 0,
        subtotal NUMERIC(18,2) DEFAULT 0
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS llamadas_servicio (
        id SERIAL PRIMARY KEY, folio TEXT UNIQUE,
        cliente_id INTEGER REFERENCES clientes(id),
        cliente_nombre TEXT DEFAULT '',
        item_code TEXT, item_nombre TEXT DEFAULT '',
        serial_number TEXT DEFAULT '', problema TEXT NOT NULL,
        prioridad TEXT DEFAULT 'media', estatus TEXT DEFAULT 'abierta',
        tecnico_id INTEGER REFERENCES usuarios(id),
        fecha_atencion TEXT DEFAULT '', fecha_cierre TEXT DEFAULT '',
        creado_por INTEGER REFERENCES usuarios(id),
        fecha_creacion TEXT DEFAULT '', fecha_actualizacion TEXT DEFAULT ''
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS llamadas_seguimiento (
        id SERIAL PRIMARY KEY,
        llamada_id INTEGER REFERENCES llamadas_servicio(id) ON DELETE CASCADE,
        usuario_id INTEGER REFERENCES usuarios(id),
        accion TEXT NOT NULL, nota TEXT DEFAULT '',
        estatus_anterior TEXT DEFAULT '', estatus_nuevo TEXT DEFAULT '',
        fecha TEXT DEFAULT ''
    )""")
    conn.commit(); cur.close(); conn.close()

init_db()

# ── SAP SERVICE LAYER HELPERS ─────────────────────────────
import requests as _req
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def sap_login():
    """Abre sesión en SAP Service Layer. Retorna session o None."""
    if not SAP_BASE_URL or not SAP_USER:
        return None
    try:
        s = _req.Session()
        s.verify = SAP_VERIFY_SSL
        r = s.post(f"{SAP_BASE_URL}/Login", json={
            "CompanyDB": SAP_COMPANY_DB,
            "UserName":  SAP_USER,
            "Password":  SAP_PASSWORD,
        }, timeout=15)
        r.raise_for_status()
        s.cookies.set("B1SESSION", r.json()["SessionId"])
        return s
    except Exception as e:
        return None

def sap_logout(s):
    if s:
        try: s.post(f"{SAP_BASE_URL}/Logout", timeout=5)
        except: pass

def sap_get_bp_code(cliente_nombre):
    """Busca el CardCode del cliente en sap_business_partners por nombre."""
    if not cliente_nombre:
        return None
    row = query("""SELECT card_code FROM sap_business_partners
                   WHERE card_name ILIKE %s LIMIT 1""",
                (cliente_nombre,), fetchone=True)
    return row["card_code"] if row else None

def sap_get_item_info(item_code):
    """Obtiene info del artículo para el payload SAP."""
    if not item_code:
        return None
    return query("SELECT * FROM sap_items WHERE item_code=%s",
                 (item_code,), fetchone=True)

def crear_service_call_sap(llamada: dict) -> tuple[bool, str, int | None]:
    """
    Crea una Service Call en SAP B1 via Service Layer.
    Retorna (ok, mensaje, doc_entry).
    """
    s = sap_login()
    if not s:
        return False, "No se pudo conectar a SAP Service Layer", None

    try:
        # Buscar CardCode del cliente
        card_code = sap_get_bp_code(llamada.get("cliente_nombre",""))

        # SAP B1 HANA: Priority usa letras L/M/H, Status usa enteros
        prio_map   = {"baja":"L","media":"M","alta":"H","urgente":"H"}
        status_map = {"abierta":-2,"en proceso":-2,"resuelta":-1,"cerrada":-1}

        subject = f"[{llamada.get('folio','')}] {llamada.get('problema','')[:80]}"
        payload = {
            "Subject":     subject,
            "Description": llamada.get("problema",""),
            "Priority":    prio_map.get(llamada.get("prioridad","media"), "M"),
            "Status":      status_map.get(llamada.get("estatus","abierta"), -2),
            "Origin":      -1,   # Sin origen específico
        }

        if card_code:
            payload["CustomerCode"] = card_code

        if llamada.get("item_code"):
            payload["ItemCode"] = llamada["item_code"]
            # Solo serial si existe y no está vacío
            serial = (llamada.get("serial_number") or "").strip()
            if serial:
                payload["ManufacturerSerialNum"] = serial
                payload["InternalSerialNum"]     = serial

        if llamada.get("fecha_atencion"):
            payload["ResponseByDate"] = llamada["fecha_atencion"]

        r = s.post(f"{SAP_BASE_URL}/ServiceCalls", json=payload, timeout=20)

        if r.status_code in [200, 201]:
            doc_entry = r.json().get("ServiceCallID") or r.json().get("CallID")
            return True, f"Service Call creada en SAP (ID: {doc_entry})", doc_entry
        else:
            msg = r.json().get("error",{}).get("message","Error desconocido")
            return False, f"SAP rechazó la llamada: {msg}", None

    except Exception as e:
        return False, f"Error al conectar con SAP: {str(e)}", None
    finally:
        sap_logout(s)

def actualizar_service_call_sap(doc_entry: int, nuevo_estatus: str, nota: str = "") -> tuple[bool, str]:
    """Actualiza el estatus de una Service Call en SAP."""
    if not doc_entry:
        return False, "Sin DocEntry SAP"
    s = sap_login()
    if not s:
        return False, "No se pudo conectar a SAP"
    try:
        status_map = {"abierta":-2,"en proceso":-2,"resuelta":-1,"cerrada":-1}
        payload = {"Status": status_map.get(nuevo_estatus, -2)}
        # Remove empty keys
        if nota:
            payload["Resolution"] = nota
        r = s.patch(f"{SAP_BASE_URL}/ServiceCalls({doc_entry})", json=payload, timeout=20)
        if r.status_code in [200, 201, 204]:
            return True, "SAP actualizado"
        msg = r.json().get("error",{}).get("message","Error") if r.content else "Error"
        return False, f"SAP: {msg}"
    except Exception as e:
        return False, str(e)
    finally:
        sap_logout(s)

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

    tipo_cliente  = request.args.get("tipo_cliente","")  # C=Cliente, L=Lead, S=Proveedor

    base = """SELECT c.*,u.nombre AS vendedor_nombre, u.usuario AS vendedor_usuario,
              (SELECT COUNT(*) FROM actividades a WHERE a.cliente=c.nombre) AS total_visitas,
              (SELECT MAX(a.fecha) FROM actividades a WHERE a.cliente=c.nombre) AS ultima_visita,
              (SELECT MIN(a.proxima_visita) FROM actividades a WHERE a.cliente=c.nombre
               AND a.proxima_visita >= CURRENT_DATE::text) AS proxima_visita
              FROM clientes c LEFT JOIN usuarios u ON u.id=c.vendedor_id
              WHERE c.activo=1
              AND (c.tipo_cliente IN ('C','L') OR c.tipo_cliente IS NULL OR c.tipo_cliente = '')"""
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
    if tipo_cliente:
        base += " AND c.tipo_cliente=%s"; params.append(tipo_cliente)

    # Paginación
    page     = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    if per_page not in [20, 50, 100]: per_page = 20
    offset   = (page - 1) * per_page

    # Total count — query simple separada
    count_base = "SELECT COUNT(*) AS total FROM clientes c WHERE c.activo=1 AND (c.tipo_cliente IN ('C','L') OR c.tipo_cliente IS NULL OR c.tipo_cliente = '')"
    count_params = []
    if not can_see_all() and rol != "supervisor":
        count_base += " AND c.vendedor_id=%s"; count_params.append(uid)
    if buscar:
        count_base += " AND (c.nombre ILIKE %s OR c.empresa ILIKE %s OR c.email ILIKE %s)"
        count_params += [f"%{buscar}%",f"%{buscar}%",f"%{buscar}%"]
    if clasificacion:
        count_base += " AND c.clasificacion=%s"; count_params.append(clasificacion)
    if semaforo:
        count_base += " AND c.estado_semaforo=%s"; count_params.append(semaforo)
    if tipo_cliente:
        count_base += " AND c.tipo_cliente=%s"; count_params.append(tipo_cliente)
    total_row = query(count_base, tuple(count_params), fetchone=True)
    total     = total_row["total"] if total_row else 0
    total_pages = max(1, -(-total // per_page))

    base += " ORDER BY c.fecha_actualizacion DESC, c.fecha_creacion DESC"
    base += f" LIMIT {per_page} OFFSET {offset}"
    lista = query(base, tuple(params), fetchall=True) or []

    vendedores = query("SELECT id,nombre,usuario FROM usuarios WHERE activo=1 ORDER BY nombre",fetchall=True) or []
    return render_template("clientes.html", empresa=EMPRESA, logo=LOGO,
                           clientes=lista, vendedores=vendedores,
                           clasificaciones=CLASIFICACIONES, industrias=INDUSTRIAS,
                           fuentes=FUENTES, semaforos=SEMAFOROS,
                           q=buscar, fil_clas=clasificacion, fil_sem=semaforo,
                           fil_tipo=tipo_cliente,
                           page=page, per_page=per_page, total=total, total_pages=total_pages)

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




# ── COTIZACIONES ──────────────────────────────────────────
ESTATUS_COT = ["borrador","enviada","aceptada","rechazada","vencida"]
IVA = 0.16

def gen_folio_cot():
    count = query("SELECT COUNT(*) AS c FROM cotizaciones", fetchone=True)["c"]
    return f"COT-{(count+1):04d}"

def calcular_totales(items, descuento_global=0):
    subtotal = sum(
        float(i.get("cantidad",1)) * float(i.get("precio_unitario",0)) *
        (1 - float(i.get("descuento",0))/100)
        for i in items
    )
    desc_monto = subtotal * (float(descuento_global)/100)
    base       = subtotal - desc_monto
    impuesto   = round(base * IVA, 2)
    total      = round(base + impuesto, 2)
    return round(subtotal,2), round(desc_monto,2), impuesto, total

@app.route("/cotizaciones")
def cotizaciones():
    if not logged_in(): return redirect(url_for("login"))
    uid = session["user_id"]
    rol = session["rol"]
    q   = request.args.get("q","").strip()
    fil_est = request.args.get("estatus","")

    base = """SELECT c.*,u.nombre AS creador_nombre
              FROM cotizaciones c LEFT JOIN usuarios u ON u.id=c.creado_por
              WHERE 1=1"""
    params = []
    if not can_see_all() and rol != "supervisor":
        base += " AND c.creado_por=%s"; params.append(uid)
    if q:
        base += " AND (c.folio ILIKE %s OR c.cliente_nombre ILIKE %s)"
        params += [f"%{q}%", f"%{q}%"]
    if fil_est:
        base += " AND c.estatus=%s"; params.append(fil_est)
    base += " ORDER BY c.fecha_creacion DESC"
    lista = query(base, tuple(params), fetchall=True) or []

    return render_template("cotizaciones.html", empresa=EMPRESA, logo=LOGO,
                           cotizaciones=lista, estatus_cot=ESTATUS_COT,
                           q=q, fil_est=fil_est)

@app.route("/cotizaciones/crear", methods=["POST"])
def crear_cotizacion():
    if not logged_in(): return redirect(url_for("login"))
    if not tiene_permiso("crear","cotizaciones"):
        flash("Sin permiso.","danger"); return redirect(url_for("cotizaciones"))
    uid  = session["user_id"]
    now  = datetime.now().strftime("%Y-%m-%d %H:%M")
    from datetime import timedelta
    valida = (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d")

    cliente_id     = request.form.get("cliente_id") or None
    cliente_nombre = request.form.get("cliente_nombre","").strip()
    notas          = request.form.get("notas","").strip()
    condiciones    = request.form.get("condiciones","").strip()
    descuento_gbl  = float(request.form.get("descuento_global","0") or 0)
    validez        = int(request.form.get("validez_dias","15") or 15)

    # Items enviados como JSON
    import json as _json
    items_raw = request.form.get("items_json","[]")
    try: items = _json.loads(items_raw)
    except: items = []

    subtotal, desc_monto, impuesto, total = calcular_totales(items, descuento_gbl)
    folio = gen_folio_cot()

    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""INSERT INTO cotizaciones
            (folio,cliente_id,cliente_nombre,estatus,validez_dias,moneda,
             descuento_global,subtotal,descuento_monto,impuesto,total,
             notas,condiciones,creado_por,fecha_creacion,fecha_actualizacion,fecha_vencimiento)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (folio,cliente_id,cliente_nombre,"borrador",validez,"MXN",
             descuento_gbl,subtotal,desc_monto,impuesto,total,
             notas,condiciones,uid,now,now,valida))
        cot_id = cur.fetchone()["id"]
        for it in items:
            cant  = float(it.get("cantidad",1))
            precio= float(it.get("precio_unitario",0))
            desc  = float(it.get("descuento",0))
            sub   = round(cant * precio * (1 - desc/100), 2)
            cur.execute("""INSERT INTO cotizaciones_items
                (cotizacion_id,item_code,item_nombre,uom,cantidad,precio_unitario,descuento,subtotal)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (cot_id,it.get("item_code",""),it.get("item_nombre",""),
                 it.get("uom",""),cant,precio,desc,sub))
        conn.commit(); cur.close(); conn.close()
        flash(f"Cotización {folio} creada ✅","success")
        return redirect(url_for("detalle_cotizacion", cotizacion_id=cot_id))
    except Exception as e:
        flash(f"Error: {e}","danger")
        return redirect(url_for("cotizaciones"))

@app.route("/cotizaciones/<int:cotizacion_id>")
def detalle_cotizacion(cotizacion_id):
    if not logged_in(): return redirect(url_for("login"))
    cot = query("""SELECT c.*,u.nombre AS creador_nombre
                   FROM cotizaciones c LEFT JOIN usuarios u ON u.id=c.creado_por
                   WHERE c.id=%s""",(cotizacion_id,),fetchone=True)
    if not cot: abort(404)
    items = query("SELECT * FROM cotizaciones_items WHERE cotizacion_id=%s ORDER BY id",
                  (cotizacion_id,),fetchall=True) or []
    return render_template("cotizacion_detalle.html", empresa=EMPRESA, logo=LOGO,
                           cot=cot, items=items, estatus_cot=ESTATUS_COT, IVA=IVA)

@app.route("/cotizaciones/<int:cotizacion_id>/actualizar-estatus", methods=["POST"])
def actualizar_estatus_cotizacion(cotizacion_id):
    if not logged_in(): return redirect(url_for("login"))
    nuevo = request.form.get("estatus","borrador")
    now   = datetime.now().strftime("%Y-%m-%d %H:%M")
    query("UPDATE cotizaciones SET estatus=%s,fecha_actualizacion=%s WHERE id=%s",
          (nuevo,now,cotizacion_id),commit=True)
    flash("Estatus actualizado","success")
    return redirect(url_for("detalle_cotizacion", cotizacion_id=cotizacion_id))

@app.route("/cotizaciones/<int:cotizacion_id>/pdf")
def cotizacion_pdf(cotizacion_id):
    if not logged_in(): return redirect(url_for("login"))
    cot = query("""SELECT c.*,u.nombre AS creador_nombre
                   FROM cotizaciones c LEFT JOIN usuarios u ON u.id=c.creado_por
                   WHERE c.id=%s""",(cotizacion_id,),fetchone=True)
    if not cot: abort(404)
    items = query("SELECT * FROM cotizaciones_items WHERE cotizacion_id=%s ORDER BY id",
                  (cotizacion_id,),fetchall=True) or []
    config = query("SELECT * FROM config WHERE id=1",fetchone=True) or {}
    return render_template("cotizacion_pdf.html",
                           cot=cot, items=items, empresa=EMPRESA,
                           config=config, IVA=IVA)

@app.route("/cotizaciones/<int:cotizacion_id>/duplicar", methods=["POST"])
def duplicar_cotizacion(cotizacion_id):
    if not logged_in(): return redirect(url_for("login"))
    cot   = query("SELECT * FROM cotizaciones WHERE id=%s",(cotizacion_id,),fetchone=True)
    if not cot: abort(404)
    items = query("SELECT * FROM cotizaciones_items WHERE cotizacion_id=%s ORDER BY id",
                  (cotizacion_id,),fetchall=True) or []
    uid   = session["user_id"]
    now   = datetime.now().strftime("%Y-%m-%d %H:%M")
    folio = gen_folio_cot()
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""INSERT INTO cotizaciones
            (folio,cliente_id,cliente_nombre,estatus,validez_dias,moneda,
             descuento_global,subtotal,descuento_monto,impuesto,total,
             notas,condiciones,creado_por,fecha_creacion,fecha_actualizacion,fecha_vencimiento)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (folio,cot["cliente_id"],cot["cliente_nombre"],"borrador",
             cot["validez_dias"],cot["moneda"],cot["descuento_global"],
             cot["subtotal"],cot["descuento_monto"],cot["impuesto"],cot["total"],
             cot["notas"],cot["condiciones"],uid,now,now,cot["fecha_vencimiento"]))
        new_id = cur.fetchone()["id"]
        for it in items:
            cur.execute("""INSERT INTO cotizaciones_items
                (cotizacion_id,item_code,item_nombre,uom,cantidad,precio_unitario,descuento,subtotal)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (new_id,it["item_code"],it["item_nombre"],it["uom"],
                 it["cantidad"],it["precio_unitario"],it["descuento"],it["subtotal"]))
        conn.commit(); cur.close(); conn.close()
        flash(f"Cotización duplicada como {folio} ✅","success")
        return redirect(url_for("detalle_cotizacion", cotizacion_id=new_id))
    except Exception as e:
        flash(f"Error: {e}","danger")
        return redirect(url_for("cotizaciones"))

# ── SERVICIOS ─────────────────────────────────────────────
PRIORIDADES  = ["baja","media","alta","urgente"]
ESTATUS_SVC  = ["abierta","en proceso","resuelta","cerrada"]
COLOR_PRIO   = {"baja":"#6c757d","media":"#1a56db","alta":"#e65100","urgente":"#c5221f"}
COLOR_EST    = {"abierta":"#1a56db","en proceso":"#e65100","resuelta":"#1e7e34","cerrada":"#6c757d"}
BG_PRIO      = {"baja":"#f8f9fa","media":"#e8f0fe","alta":"#fff3e0","urgente":"#fce8e6"}
BG_EST       = {"abierta":"#e8f0fe","en proceso":"#fff3e0","resuelta":"#e6f4ea","cerrada":"#f8f9fa"}

def gen_folio():
    count = query("SELECT COUNT(*) AS c FROM llamadas_servicio", fetchone=True)["c"]
    return f"SVC-{(count+1):04d}"

@app.route("/servicios")
def servicios():
    if not logged_in(): return redirect(url_for("login"))
    uid = session["user_id"]
    rol = session["rol"]
    filtro_est  = request.args.get("estatus","")
    filtro_prio = request.args.get("prioridad","")
    filtro_tec  = request.args.get("tecnico","")
    q           = request.args.get("q","").strip()

    base = """SELECT ls.*,
              u.nombre AS tecnico_nombre, u.usuario AS tecnico_usuario,
              c.nombre AS cliente_nombre_join
              FROM llamadas_servicio ls
              LEFT JOIN usuarios u ON u.id=ls.tecnico_id
              LEFT JOIN clientes c ON c.id=ls.cliente_id
              WHERE 1=1"""
    params = []

    # Vendedor solo ve sus llamadas (donde es técnico o las creó)
    if not can_see_all() and rol not in ["supervisor"]:
        base += " AND (ls.tecnico_id=%s OR ls.creado_por=%s)"
        params += [uid, uid]

    if filtro_est:  base += " AND ls.estatus=%s";       params.append(filtro_est)
    if filtro_prio: base += " AND ls.prioridad=%s";     params.append(filtro_prio)
    if filtro_tec:  base += " AND ls.tecnico_id=%s";    params.append(filtro_tec)
    if q:
        base += " AND (ls.folio ILIKE %s OR ls.cliente_nombre ILIKE %s OR ls.item_nombre ILIKE %s OR ls.problema ILIKE %s)"
        params += [f"%{q}%"]*4

    base += " ORDER BY CASE ls.prioridad WHEN 'urgente' THEN 1 WHEN 'alta' THEN 2 WHEN 'media' THEN 3 ELSE 4 END, ls.fecha_creacion DESC"
    llamadas = query(base, tuple(params), fetchall=True) or []

    tecnicos = query("SELECT id,nombre,usuario FROM usuarios WHERE activo=1 ORDER BY nombre", fetchall=True) or []
    return render_template("servicios.html", empresa=EMPRESA, logo=LOGO,
                           llamadas=llamadas, tecnicos=tecnicos,
                           prioridades=PRIORIDADES, estatus_svc=ESTATUS_SVC,
                           color_prio=COLOR_PRIO, color_est=COLOR_EST,
                           bg_prio=BG_PRIO, bg_est=BG_EST,
                           fil_est=filtro_est, fil_prio=filtro_prio,
                           fil_tec=filtro_tec, q=q)

@app.route("/servicios/crear", methods=["POST"])
def crear_servicio():
    if not logged_in(): return redirect(url_for("login"))
    if not tiene_permiso("crear","servicios"):
        flash("Sin permiso para crear llamadas de servicio.","danger")
        return redirect(url_for("servicios"))
    uid  = session["user_id"]
    now  = datetime.now().strftime("%Y-%m-%d %H:%M")
    folio = gen_folio()

    cliente_id     = request.form.get("cliente_id") or None
    cliente_nombre = request.form.get("cliente_nombre","").strip()
    item_code      = request.form.get("item_code","").strip() or None
    item_nombre    = request.form.get("item_nombre","").strip()
    serial_number  = request.form.get("serial_number","").strip()
    problema       = request.form.get("problema","").strip()
    prioridad      = request.form.get("prioridad","media")
    tecnico_id     = request.form.get("tecnico_id") or uid
    fecha_atencion = request.form.get("fecha_atencion","").strip()

    if not problema:
        flash("El problema es obligatorio.","danger"); return redirect(url_for("servicios"))

    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""INSERT INTO llamadas_servicio
            (folio,cliente_id,cliente_nombre,item_code,item_nombre,serial_number,
             problema,prioridad,estatus,tecnico_id,fecha_atencion,
             creado_por,fecha_creacion,fecha_actualizacion)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (folio,cliente_id,cliente_nombre,item_code,item_nombre,serial_number,
             problema,prioridad,"abierta",tecnico_id,fecha_atencion,uid,now,now))
        llamada_id = cur.fetchone()["id"]
        # Log inicial
        cur.execute("""INSERT INTO llamadas_seguimiento
            (llamada_id,usuario_id,accion,nota,estatus_anterior,estatus_nuevo,fecha)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (llamada_id,uid,"Llamada creada","","-","abierta",now))
        conn.commit(); cur.close(); conn.close()
        # ── Intentar crear en SAP ──────────────────────
        now_sap = datetime.now().strftime("%Y-%m-%d %H:%M")
        llamada_dict = {
            "folio":          folio,
            "cliente_nombre": cliente_nombre,
            "item_code":      item_code,
            "item_nombre":    item_nombre,
            "serial_number":  serial_number,
            "problema":       problema,
            "prioridad":      prioridad,
            "estatus":        "abierta",
            "fecha_atencion": fecha_atencion,
        }
        sap_ok, sap_msg, sap_doc = crear_service_call_sap(llamada_dict)
        sap_status = "ok" if sap_ok else "error"

        query("""UPDATE llamadas_servicio SET
                 sap_doc_entry=%s, sap_sync_status=%s,
                 sap_sync_msg=%s, sap_sync_fecha=%s
                 WHERE id=%s""",
              (sap_doc, sap_status, sap_msg, now_sap, llamada_id), commit=True)

        # Log SAP en seguimiento
        query("""INSERT INTO llamadas_seguimiento
                 (llamada_id,usuario_id,accion,nota,estatus_anterior,estatus_nuevo,fecha)
                 VALUES (%s,%s,%s,%s,%s,%s,%s)""",
              (llamada_id, uid,
               f"SAP: {'✅ '+sap_msg if sap_ok else '❌ '+sap_msg}",
               "", "abierta", "abierta", now_sap), commit=True)

        if sap_ok:
            flash(f"Llamada {folio} creada ✅ — SAP ID: {sap_doc}","success")
        else:
            flash(f"Llamada {folio} guardada en portal ⚠️ — SAP: {sap_msg}","warning")

    except Exception as e:
        flash(f"Error: {e}","danger")
    return redirect(url_for("servicios"))

@app.route("/servicios/<int:llamada_id>")
def detalle_servicio(llamada_id):
    if not logged_in(): return redirect(url_for("login"))
    uid = session["user_id"]
    ls = query("""SELECT ls.*,
                  u.nombre AS tecnico_nombre,
                  c2.nombre AS creador_nombre,
                  cl.nombre AS cliente_obj_nombre,
                  cl.empresa AS cliente_empresa,
                  cl.telefono AS cliente_tel
                  FROM llamadas_servicio ls
                  LEFT JOIN usuarios u ON u.id=ls.tecnico_id
                  LEFT JOIN usuarios c2 ON c2.id=ls.creado_por
                  LEFT JOIN clientes cl ON cl.id=ls.cliente_id
                  WHERE ls.id=%s""", (llamada_id,), fetchone=True)
    if not ls: abort(404)
    if not can_see_all() and ls["tecnico_id"] != uid and ls["creado_por"] != uid:
        abort(403)
    seguimiento = query("""SELECT sg.*,u.nombre AS user_nombre,u.usuario AS user_usuario
                           FROM llamadas_seguimiento sg
                           JOIN usuarios u ON u.id=sg.usuario_id
                           WHERE sg.llamada_id=%s ORDER BY sg.fecha DESC""",
                        (llamada_id,), fetchall=True) or []
    # Info del artículo
    item = None
    if ls.get("item_code"):
        item = query("SELECT * FROM sap_items WHERE item_code=%s",(ls["item_code"],),fetchone=True)
    # Seriales del artículo
    seriales = []
    if ls.get("item_code"):
        seriales = query("""SELECT serial_number,warehouse_code,status,expiry_date
                            FROM sap_item_serial WHERE item_code=%s AND serial_number IS NOT NULL
                            ORDER BY serial_number LIMIT 50""",
                         (ls["item_code"],), fetchall=True) or []
    tecnicos = query("SELECT id,nombre FROM usuarios WHERE activo=1 ORDER BY nombre",fetchall=True) or []
    return render_template("servicio_detalle.html", empresa=EMPRESA, logo=LOGO,
                           ls=ls, seguimiento=seguimiento, item=item, seriales=seriales,
                           tecnicos=tecnicos, prioridades=PRIORIDADES, estatus_svc=ESTATUS_SVC,
                           color_prio=COLOR_PRIO, color_est=COLOR_EST,
                           bg_prio=BG_PRIO, bg_est=BG_EST)

@app.route("/servicios/<int:llamada_id>/actualizar", methods=["POST"])
def actualizar_servicio(llamada_id):
    if not logged_in(): return redirect(url_for("login"))
    uid  = session["user_id"]
    now  = datetime.now().strftime("%Y-%m-%d %H:%M")
    ls   = query("SELECT * FROM llamadas_servicio WHERE id=%s",(llamada_id,),fetchone=True)
    if not ls: abort(404)
    if not can_see_all() and ls["tecnico_id"] != uid and ls["creado_por"] != uid:
        abort(403)

    nuevo_estatus = request.form.get("estatus", ls["estatus"])
    nueva_prio    = request.form.get("prioridad", ls["prioridad"])
    nuevo_tec     = request.form.get("tecnico_id", ls["tecnico_id"])
    nota          = request.form.get("nota","").strip()
    fecha_cierre  = now[:10] if nuevo_estatus in ["resuelta","cerrada"] and ls["estatus"] not in ["resuelta","cerrada"] else ls.get("fecha_cierre","")

    cambios = []
    if nuevo_estatus != ls["estatus"]: cambios.append(f"Estatus: {ls['estatus']} → {nuevo_estatus}")
    if nueva_prio    != ls["prioridad"]: cambios.append(f"Prioridad: {ls['prioridad']} → {nueva_prio}")
    if str(nuevo_tec) != str(ls["tecnico_id"] or ""): cambios.append("Técnico reasignado")
    if nota: cambios.append(f"Nota: {nota}")

    try:
        query("""UPDATE llamadas_servicio SET estatus=%s,prioridad=%s,tecnico_id=%s,
                 fecha_cierre=%s,fecha_actualizacion=%s WHERE id=%s""",
              (nuevo_estatus,nueva_prio,nuevo_tec,fecha_cierre,now,llamada_id),commit=True)
        if cambios:
            query("""INSERT INTO llamadas_seguimiento
                     (llamada_id,usuario_id,accion,nota,estatus_anterior,estatus_nuevo,fecha)
                     VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                  (llamada_id,uid," | ".join(cambios),nota,ls["estatus"],nuevo_estatus,now),commit=True)
        # ── Sincronizar estatus a SAP si hay DocEntry ──
        if ls.get("sap_doc_entry") and nuevo_estatus != ls["estatus"]:
            sap_ok, sap_msg = actualizar_service_call_sap(ls["sap_doc_entry"], nuevo_estatus, nota)
            now_sap = datetime.now().strftime("%Y-%m-%d %H:%M")
            query("""UPDATE llamadas_servicio SET
                     sap_sync_status=%s, sap_sync_msg=%s, sap_sync_fecha=%s
                     WHERE id=%s""",
                  ("ok" if sap_ok else "error", sap_msg, now_sap, llamada_id), commit=True)

        flash("Llamada actualizada ✅","success")
    except Exception as e:
        flash(f"Error: {e}","danger")
    return redirect(url_for("detalle_servicio", llamada_id=llamada_id))

@app.route("/servicios/buscar-items")
def buscar_items():
    if not logged_in(): return jsonify([])
    q = request.args.get("q","").strip()
    if len(q) < 1: return jsonify([])
    rows = query("""SELECT item_code, item_name, item_group, uom, price
                    FROM sap_items WHERE active=true
                    AND (item_code ILIKE %s OR item_name ILIKE %s)
                    ORDER BY item_name LIMIT 10""",
                 (f"%{q}%",f"%{q}%"), fetchall=True) or []
    return jsonify([{
        "item_code":  r["item_code"],
        "item_name":  r["item_name"] or "",
        "item_group": r["item_group"] or "",
        "uom":        r["uom"] or "",
        "price":      float(r["price"] or 0),
    } for r in rows])

@app.route("/servicios/seriales/<item_code>")
def seriales_item(item_code):
    if not logged_in(): return jsonify([])
    rows = query("""SELECT serial_number, warehouse_code, status
                    FROM sap_item_serial WHERE item_code=%s
                    AND serial_number IS NOT NULL
                    ORDER BY serial_number LIMIT 50""",
                 (item_code,), fetchall=True) or []
    return jsonify([{
        "serial": r["serial_number"],
        "almacen": r["warehouse_code"] or "",
        "status": r["status"] or "",
    } for r in rows])


@app.route("/servicios/<int:llamada_id>/reintentar-sap", methods=["POST"])
def reintentar_sap(llamada_id):
    """Reintenta enviar la llamada a SAP cuando falló inicialmente."""
    if not logged_in(): return redirect(url_for("login"))
    if not tiene_permiso("editar","servicios"): abort(403)

    ls = query("SELECT * FROM llamadas_servicio WHERE id=%s",(llamada_id,),fetchone=True)
    if not ls: abort(404)

    uid = session["user_id"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    sap_ok, sap_msg, sap_doc = crear_service_call_sap(dict(ls))
    sap_status = "ok" if sap_ok else "error"

    query("""UPDATE llamadas_servicio SET
             sap_doc_entry=%s, sap_sync_status=%s,
             sap_sync_msg=%s, sap_sync_fecha=%s WHERE id=%s""",
          (sap_doc or ls.get("sap_doc_entry"),
           sap_status, sap_msg, now, llamada_id), commit=True)

    query("""INSERT INTO llamadas_seguimiento
             (llamada_id,usuario_id,accion,nota,estatus_anterior,estatus_nuevo,fecha)
             VALUES (%s,%s,%s,%s,%s,%s,%s)""",
          (llamada_id, uid,
           f"Reintento SAP: {'✅ '+sap_msg if sap_ok else '❌ '+sap_msg}",
           "", ls["estatus"], ls["estatus"], now), commit=True)

    if sap_ok:
        flash(f"✅ Enviado a SAP correctamente — ID: {sap_doc}","success")
    else:
        flash(f"❌ SAP rechazó: {sap_msg}","danger")
    return redirect(url_for("detalle_servicio", llamada_id=llamada_id))


@app.route("/proveedores/buscar")
def buscar_proveedores():
    """Busca clientes con tipo_cliente='S' (proveedores SAP)."""
    if not logged_in(): return jsonify([])
    q = request.args.get("q","").strip().replace("*","")
    if len(q) < 1: return jsonify([])
    param = f"%{q}%"
    rows = query("""SELECT id,nombre,empresa,telefono,tipo_cliente,fuente
                    FROM clientes WHERE activo=1
                    AND (tipo_cliente='S' OR tipo_cliente IS NULL OR tipo_cliente='')
                    AND (nombre ILIKE %s OR empresa ILIKE %s)
                    ORDER BY nombre LIMIT 10""",
                 (param,param), fetchall=True) or []
    return jsonify([{
        "id": r["id"],
        "nombre": r["nombre"],
        "empresa": r["empresa"] or "",
        "telefono": r["telefono"] or "",
        "fuente": r["fuente"] or "CRM",
    } for r in rows])

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

    # Buscar en tabla clientes — solo tipo C y L (excluir proveedores S)
    sql_clientes = """SELECT id, nombre, empresa, telefono, clasificacion,
                      estado_semaforo, fuente, tipo_cliente
                      FROM clientes WHERE activo=1
                      AND (nombre ILIKE %s OR empresa ILIKE %s)
                      AND (tipo_cliente IN ('C','L') OR tipo_cliente IS NULL OR tipo_cliente = '')"""
    params = [param, param]
    if not can_see_all() and rol not in ["supervisor"]:
        sql_clientes += " AND (vendedor_id=%s OR vendedor_id IS NULL)"
        params.append(uid)
    sql_clientes += " ORDER BY nombre LIMIT 10"
    rows = query(sql_clientes, tuple(params), fetchall=True) or []
    for r in rows:
        fuente = r.get("fuente") or "CRM"
        resultados.append({
            "id":            r["id"],
            "nombre":        r["nombre"],
            "empresa":       r["empresa"] or "",
            "telefono":      r["telefono"] or "",
            "clasificacion": r["clasificacion"] or "",
            "semaforo":      r["estado_semaforo"] or "verde",
            "fuente":        fuente,
        })

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

# ══════════════════════════════════════════════════════════
# ── ALMACENES ─────────────────────────────────────────────
# ══════════════════════════════════════════════════════════
TIPOS_ALMACEN = ["general","materia prima","producto terminado","herramienta","tránsito"]

@app.route("/almacenes")
def almacenes():
    if not logged_in(): return redirect(url_for("login"))
    lista = query("""SELECT a.*,u.nombre AS resp_nombre
                     FROM almacenes a LEFT JOIN usuarios u ON u.id=a.responsable_id
                     WHERE a.activo=true ORDER BY a.nombre""", fetchall=True) or []
    usuarios_list = query("SELECT id,nombre,usuario FROM usuarios WHERE activo=1 ORDER BY nombre",fetchall=True) or []
    return render_template("almacenes.html", empresa=EMPRESA, logo=LOGO,
                           almacenes=lista, usuarios=usuarios_list, tipos=TIPOS_ALMACEN)

@app.route("/almacenes/crear", methods=["POST"])
def crear_almacen():
    if not logged_in(): return redirect(url_for("login"))
    if not tiene_permiso("crear","almacenes"): abort(403)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    codigo = request.form.get("codigo","").strip().upper()
    nombre = request.form.get("nombre","").strip()
    if not codigo or not nombre:
        flash("Código y nombre son obligatorios.","danger"); return redirect(url_for("almacenes"))
    try:
        query("""INSERT INTO almacenes (codigo,nombre,descripcion,ubicacion,responsable_id,tipo,activo,fuente,fecha_creacion,fecha_actualizacion)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              (codigo,nombre,
               request.form.get("descripcion","").strip(),
               request.form.get("ubicacion","").strip(),
               request.form.get("responsable_id") or None,
               request.form.get("tipo","general"),
               True,"portal",now,now), commit=True)
        flash(f"Almacén {codigo} creado ✅","success")
    except Exception as e:
        flash(f"Error: {e}","danger")
    return redirect(url_for("almacenes"))

@app.route("/almacenes/editar/<int:almacen_id>", methods=["POST"])
def editar_almacen(almacen_id):
    if not logged_in(): return redirect(url_for("login"))
    if not tiene_permiso("editar","almacenes"): abort(403)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    activo = request.form.get("activo","true") == "true"
    query("""UPDATE almacenes SET nombre=%s,descripcion=%s,ubicacion=%s,
             responsable_id=%s,tipo=%s,activo=%s,fecha_actualizacion=%s WHERE id=%s""",
          (request.form.get("nombre","").strip(),
           request.form.get("descripcion","").strip(),
           request.form.get("ubicacion","").strip(),
           request.form.get("responsable_id") or None,
           request.form.get("tipo","general"),
           activo,now,almacen_id), commit=True)
    flash("Almacén actualizado ✅","success")
    return redirect(url_for("almacenes"))


@app.route("/almacenes/sync-sap", methods=["POST"])
def sync_almacenes_sap():
    """Sincroniza almacenes desde SAP Service Layer."""
    if not logged_in(): return redirect(url_for("login"))
    if not is_admin(): abort(403)
    s = sap_login()
    if not s:
        flash("No se pudo conectar a SAP Service Layer.","danger")
        return redirect(url_for("almacenes"))
    try:
        r = s.get(f"{SAP_BASE_URL}/Warehouses", params={"$select":"WarehouseCode,WarehouseName,Street,City,Active","$top":100}, timeout=20)
        r.raise_for_status()
        whs = r.json().get("value",[])
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        creados = 0; actualizados = 0
        for wh in whs:
            codigo = wh.get("WarehouseCode","")
            nombre = wh.get("WarehouseName","") or codigo
            activo = wh.get("Active","tYES") == "tYES"
            ubicacion = f"{wh.get('Street','')}, {wh.get('City','')}".strip(", ")
            existing = query("SELECT id FROM almacenes WHERE codigo=%s",(codigo,),fetchone=True)
            if existing:
                query("""UPDATE almacenes SET nombre=%s,ubicacion=%s,activo=%s,fecha_actualizacion=%s WHERE codigo=%s""",
                      (nombre,ubicacion,activo,now,codigo),commit=True)
                actualizados+=1
            else:
                try:
                    query("""INSERT INTO almacenes (codigo,nombre,descripcion,ubicacion,tipo,activo,fuente,fecha_creacion,fecha_actualizacion)
                             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                          (codigo,nombre,"",ubicacion,"general",activo,"SAP",now,now),commit=True)
                    creados+=1
                except: actualizados+=1
        sap_logout(s)
        flash(f"Sincronización SAP: {creados} nuevos, {actualizados} actualizados ✅","success")
    except Exception as e:
        flash(f"Error SAP: {e}","danger")
    return redirect(url_for("almacenes"))

# ── API Almacenes para dropdowns ──
@app.route("/almacenes/lista")
def almacenes_lista():
    if not logged_in(): return jsonify([])
    rows = query("SELECT id,codigo,nombre FROM almacenes WHERE activo=true ORDER BY nombre",fetchall=True) or []
    return jsonify([{"id":r["id"],"codigo":r["codigo"],"nombre":r["nombre"]} for r in rows])


# ══════════════════════════════════════════════════════════
# ── ARTÍCULOS ─────────────────────────════════════════════
# ══════════════════════════════════════════════════════════
@app.route("/articulos")
def articulos():
    if not logged_in(): return redirect(url_for("login"))
    q   = request.args.get("q","").strip()
    grp = request.args.get("grupo","")
    src = request.args.get("fuente","")
    page = int(request.args.get("page",1))
    per_page = int(request.args.get("per_page",50))
    if per_page not in [20,50,100]: per_page=50
    offset = (page-1)*per_page

    # Unificar sap_items + articulos propios
    base_art = """SELECT id,codigo,nombre,grupo,uom,precio_venta AS precio,activo,fuente,'portal' AS origen
                  FROM articulos WHERE activo=true"""
    base_sap = """SELECT item_code AS id,item_code AS codigo,item_name AS nombre,
                  item_group AS grupo,uom,price AS precio,active AS activo,'SAP' AS fuente,'sap' AS origen
                  FROM sap_items WHERE active=true"""
    params_art, params_sap = [],[]
    if q:
        base_art += " AND (codigo ILIKE %s OR nombre ILIKE %s)"; params_art+=[f"%{q}%",f"%{q}%"]
        base_sap += " AND (item_code ILIKE %s OR item_name ILIKE %s)"; params_sap+=[f"%{q}%",f"%{q}%"]
    if grp:
        base_art += " AND grupo=%s"; params_art.append(grp)
        base_sap += " AND item_group=%s"; params_sap.append(grp)

    arts = query(base_art,tuple(params_art),fetchall=True) or []
    saps = []
    if src != "portal":
        try: saps = query(base_sap,tuple(params_sap),fetchall=True) or []
        except: pass

    # Excluir de SAP los que ya están en portal (por item_code_sap)
    codigos_portal = {a["codigo"] for a in arts}
    saps_filtrados = [s for s in saps if s["codigo"] not in codigos_portal]

    todos = arts + saps_filtrados
    total = len(todos)
    total_pages = max(1,-(-total//per_page))
    lista = todos[offset:offset+per_page]

    grupos = list(set(a["grupo"] for a in todos if a.get("grupo")))
    grupos.sort()

    return render_template("articulos.html", empresa=EMPRESA, logo=LOGO,
                           articulos=lista, grupos=grupos, q=q,
                           fil_grupo=grp, fil_fuente=src,
                           page=page, per_page=per_page,
                           total=total, total_pages=total_pages)

@app.route("/articulos/crear", methods=["POST"])
def crear_articulo():
    if not logged_in(): return redirect(url_for("login"))
    if not tiene_permiso("crear","articulos"): abort(403)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    codigo = request.form.get("codigo","").strip().upper()
    nombre = request.form.get("nombre","").strip()
    if not codigo or not nombre:
        flash("Código y nombre son obligatorios.","danger"); return redirect(url_for("articulos"))
    try:
        query("""INSERT INTO articulos (codigo,nombre,descripcion,grupo,categoria,uom,
                 precio_compra,precio_venta,impuesto,activo,manage_serial,manage_batch,
                 fuente,item_code_sap,fecha_creacion,fecha_actualizacion)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              (codigo,nombre,
               request.form.get("descripcion","").strip(),
               request.form.get("grupo","").strip(),
               request.form.get("categoria","").strip(),
               request.form.get("uom","").strip(),
               float(request.form.get("precio_compra",0) or 0),
               float(request.form.get("precio_venta",0) or 0),
               float(request.form.get("impuesto",16) or 16),
               True,
               request.form.get("manage_serial","N"),
               request.form.get("manage_batch","N"),
               "portal",
               request.form.get("item_code_sap","").strip(),
               now,now), commit=True)
        flash(f"Artículo {codigo} creado ✅","success")
    except Exception as e:
        flash(f"Error: {e}","danger")
    return redirect(url_for("articulos"))

@app.route("/articulos/buscar-unificado")
def buscar_articulos_unificado():
    """Busca en articulos portal + sap_items para autocompletes."""
    if not logged_in(): return jsonify([])
    q = request.args.get("q","").strip().replace("*","")
    if len(q) < 1: return jsonify([])
    param = f"%{q}%"
    resultados = []
    # Portal
    rows = query("""SELECT codigo,nombre,uom,precio_venta AS precio,'portal' AS fuente
                    FROM articulos WHERE activo=true
                    AND (codigo ILIKE %s OR nombre ILIKE %s)
                    ORDER BY nombre LIMIT 8""",(param,param),fetchall=True) or []
    for r in rows:
        resultados.append({"codigo":r["codigo"],"nombre":r["nombre"],
                           "uom":r["uom"] or "","precio":float(r["precio"] or 0),"fuente":"portal"})
    # SAP
    codigos_ya = {r["codigo"] for r in resultados}
    try:
        sap = query("""SELECT item_code AS codigo,item_name AS nombre,uom,price AS precio,'SAP' AS fuente
                       FROM sap_items WHERE active=true
                       AND (item_code ILIKE %s OR item_name ILIKE %s)
                       ORDER BY item_name LIMIT 8""",(param,param),fetchall=True) or []
        for r in sap:
            if r["codigo"] not in codigos_ya:
                resultados.append({"codigo":r["codigo"],"nombre":r["nombre"],
                                   "uom":r["uom"] or "","precio":float(r["precio"] or 0),"fuente":"SAP"})
    except: pass
    return jsonify(resultados[:10])


# ══════════════════════════════════════════════════════════
# ── INVENTARIO / TOMA DE INVENTARIO ───────────────────────
# ══════════════════════════════════════════════════════════
@app.route("/inventario")
def inventario():
    if not logged_in(): return redirect(url_for("login"))
    almacen_id = request.args.get("almacen_id","")
    q = request.args.get("q","").strip()

    # Stock consolidado
    base = """SELECT i.*,a.codigo,a.nombre,a.uom,a.grupo,
              alm.nombre AS almacen_nombre, alm.codigo AS almacen_codigo
              FROM inventario i
              JOIN articulos a ON a.id=i.articulo_id
              JOIN almacenes alm ON alm.id=i.almacen_id
              WHERE a.activo=true"""
    params=[]
    if almacen_id: base+=" AND i.almacen_id=%s"; params.append(almacen_id)
    if q: base+=" AND (a.codigo ILIKE %s OR a.nombre ILIKE %s)"; params+=[f"%{q}%",f"%{q}%"]
    base+=" ORDER BY alm.nombre,a.nombre"
    stock = query(base,tuple(params),fetchall=True) or []

    # También mostrar SAP stock
    sap_stock=[]
    if not almacen_id:
        try:
            sap_stock = query("""SELECT w.item_code,i.item_name,w.warehouse_code,
                                 w.warehouse_name,w.in_stock,w.available
                                 FROM sap_item_warehouse w
                                 JOIN sap_items i ON i.item_code=w.item_code
                                 WHERE w.in_stock > 0
                                 ORDER BY w.item_code LIMIT 100""",fetchall=True) or []
        except: pass

    tomas = query("""SELECT t.*,alm.nombre AS almacen_nombre
                     FROM tomas_inventario t JOIN almacenes alm ON alm.id=t.almacen_id
                     ORDER BY t.fecha_creacion DESC LIMIT 10""",fetchall=True) or []
    almacenes_list = query("SELECT id,codigo,nombre FROM almacenes WHERE activo=true ORDER BY nombre",fetchall=True) or []

    return render_template("inventario.html", empresa=EMPRESA, logo=LOGO,
                           stock=stock, sap_stock=sap_stock, tomas=tomas,
                           almacenes=almacenes_list, almacen_id=almacen_id, q=q)

@app.route("/inventario/toma/crear", methods=["POST"])
def crear_toma():
    if not logged_in(): return redirect(url_for("login"))
    uid=session["user_id"]; now=datetime.now().strftime("%Y-%m-%d %H:%M")
    almacen_id = request.form.get("almacen_id")
    count = query("SELECT COUNT(*) AS c FROM tomas_inventario",fetchone=True)["c"]
    folio = f"INV-{(count+1):04d}"
    try:
        # Crear toma
        row = query("""INSERT INTO tomas_inventario (folio,almacen_id,estatus,observaciones,creado_por,fecha_creacion)
                       VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (folio,almacen_id,"borrador",
                     request.form.get("observaciones","").strip(),uid,now),
                    fetchone=True, commit=True)
        toma_id = row["id"]
        # Precargar con stock actual del almacén
        stock = query("""SELECT i.id AS articulo_id,i.stock_actual
                         FROM inventario i WHERE i.almacen_id=%s""",(almacen_id,),fetchall=True) or []
        for s in stock:
            query("""INSERT INTO tomas_inventario_lineas
                     (toma_id,articulo_id,stock_sistema,stock_contado,diferencia)
                     VALUES (%s,%s,%s,%s,%s)""",
                  (toma_id,s["articulo_id"],s["stock_actual"],0,0),commit=True)
        flash(f"Toma {folio} creada ✅","success")
        return redirect(url_for("detalle_toma",toma_id=toma_id))
    except Exception as e:
        flash(f"Error: {e}","danger"); return redirect(url_for("inventario"))

@app.route("/inventario/toma/<int:toma_id>")
def detalle_toma(toma_id):
    if not logged_in(): return redirect(url_for("login"))
    toma = query("""SELECT t.*,alm.nombre AS almacen_nombre FROM tomas_inventario t
                    JOIN almacenes alm ON alm.id=t.almacen_id WHERE t.id=%s""",(toma_id,),fetchone=True)
    if not toma: abort(404)
    lineas = query("""SELECT l.*,a.codigo,a.nombre,a.uom FROM tomas_inventario_lineas l
                      JOIN articulos a ON a.id=l.articulo_id
                      WHERE l.toma_id=%s ORDER BY a.nombre""",(toma_id,),fetchall=True) or []
    return render_template("toma_detalle.html", empresa=EMPRESA, logo=LOGO, toma=toma, lineas=lineas)

@app.route("/inventario/toma/<int:toma_id>/guardar", methods=["POST"])
def guardar_toma(toma_id):
    if not logged_in(): return redirect(url_for("login"))
    accion = request.form.get("accion","guardar")
    lineas_json = request.form.get("lineas_json","[]")
    import json as _json
    try: lineas = _json.loads(lineas_json)
    except: lineas=[]
    for l in lineas:
        contado = float(l.get("contado",0))
        sistema = float(l.get("sistema",0))
        diff = contado - sistema
        query("""UPDATE tomas_inventario_lineas SET stock_contado=%s,diferencia=%s,observacion=%s
                 WHERE id=%s""",(contado,diff,l.get("obs",""),l.get("id")),commit=True)
    if accion == "cerrar":
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        # Aplicar diferencias al inventario
        lineas_db = query("""SELECT l.*,a.id AS art_id FROM tomas_inventario_lineas l
                             JOIN articulos a ON a.id=l.articulo_id WHERE l.toma_id=%s""",(toma_id,),fetchall=True) or []
        toma = query("SELECT almacen_id FROM tomas_inventario WHERE id=%s",(toma_id,),fetchone=True)
        for l in lineas_db:
            query("""INSERT INTO inventario (articulo_id,almacen_id,stock_actual,ultima_actualizacion)
                     VALUES (%s,%s,%s,%s)
                     ON CONFLICT(articulo_id,almacen_id) DO UPDATE
                     SET stock_actual=%s,ultima_actualizacion=%s""",
                  (l["art_id"],toma["almacen_id"],l["stock_contado"],now,
                   l["stock_contado"],now),commit=True)
        query("UPDATE tomas_inventario SET estatus='cerrada',fecha_cierre=%s WHERE id=%s",
              (now,toma_id),commit=True)
        flash("Toma cerrada y stock actualizado ✅","success")
        return redirect(url_for("inventario"))
    flash("Conteos guardados","success")
    return redirect(url_for("detalle_toma",toma_id=toma_id))


# ══════════════════════════════════════════════════════════
# ── ÓRDENES DE COMPRA ─────────────────────────────────────
# ══════════════════════════════════════════════════════════
EST_OC = ["borrador","confirmada","recibida parcial","recibida","cancelada"]

def gen_folio_oc():
    c = query("SELECT COUNT(*) AS c FROM ordenes_compra",fetchone=True)["c"]
    return f"OC-{(c+1):04d}"

def sap_crear_orden_compra(oc, items):
    s = sap_login()
    if not s: return False,"No se pudo conectar a SAP",None
    try:
        lines = []
        for it in items:
            item_code = it.get("item_code") or it.get("codigo","")
            if not item_code: continue
            line = {"ItemCode":item_code,"Quantity":float(it.get("cantidad",1)),
                    "UnitPrice":float(it.get("precio_unitario",0))}
            if oc.get("almacen_codigo"): line["WarehouseCode"]=oc["almacen_codigo"]
            lines.append(line)
        payload = {"CardCode":oc.get("proveedor_cardcode",""),"DocDueDate":oc.get("fecha_entrega",""),
                   "DocumentLines":lines}
        if oc.get("notas"): payload["Comments"]=oc["notas"]
        r = s.post(f"{SAP_BASE_URL}/PurchaseOrders",json=payload,timeout=20)
        if r.status_code in [200,201]:
            de = r.json().get("DocEntry") or r.json().get("DocNum")
            return True,f"OC creada en SAP (DocEntry:{de})",de
        msg = r.json().get("error",{}).get("message","Error")
        return False,f"SAP: {msg}",None
    except Exception as e:
        return False,str(e),None
    finally:
        sap_logout(s)

@app.route("/compras")
def compras():
    if not logged_in(): return redirect(url_for("login"))
    fil_est = request.args.get("estatus","")
    q = request.args.get("q","").strip()
    base = """SELECT oc.*,u.nombre AS creador_nombre,alm.nombre AS almacen_nombre
              FROM ordenes_compra oc
              LEFT JOIN usuarios u ON u.id=oc.creado_por
              LEFT JOIN almacenes alm ON alm.id=oc.almacen_id
              WHERE 1=1"""
    params=[]
    if fil_est: base+=" AND oc.estatus=%s"; params.append(fil_est)
    if q: base+=" AND (oc.folio ILIKE %s OR oc.proveedor_nombre ILIKE %s)"; params+=[f"%{q}%",f"%{q}%"]
    base+=" ORDER BY oc.fecha_creacion DESC"
    lista = query(base,tuple(params),fetchall=True) or []
    almacenes_list = query("SELECT id,codigo,nombre FROM almacenes WHERE activo=true ORDER BY nombre",fetchall=True) or []
    return render_template("compras.html", empresa=EMPRESA, logo=LOGO,
                           ordenes=lista, estatus_oc=EST_OC,
                           almacenes=almacenes_list, fil_est=fil_est, q=q)

@app.route("/compras/crear", methods=["POST"])
def crear_orden_compra():
    if not logged_in(): return redirect(url_for("login"))
    if not tiene_permiso("crear","compras"): abort(403)
    uid=session["user_id"]; now=datetime.now().strftime("%Y-%m-%d %H:%M")
    import json as _json
    items_raw = request.form.get("items_json","[]")
    try: items = _json.loads(items_raw)
    except: items=[]
    if not items:
        flash("Agrega al menos un artículo.","danger"); return redirect(url_for("compras"))

    subtotal = sum(float(i["cantidad"])*float(i["precio_unitario"]) for i in items)
    impuesto = round(subtotal*0.16,2)
    total    = round(subtotal+impuesto,2)
    folio    = gen_folio_oc()
    proveedor_id     = request.form.get("proveedor_id") or None
    proveedor_nombre = request.form.get("proveedor_nombre","").strip()
    almacen_id       = request.form.get("almacen_id") or None
    fecha_entrega    = request.form.get("fecha_entrega","").strip()
    notas            = request.form.get("notas","").strip()

    try:
        conn=get_db(); cur=conn.cursor()
        cur.execute("""INSERT INTO ordenes_compra
            (folio,proveedor_id,proveedor_nombre,estatus,almacen_id,moneda,subtotal,impuesto,total,
             notas,fecha_entrega,sap_sync_status,creado_por,fecha_creacion,fecha_actualizacion)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (folio,proveedor_id,proveedor_nombre,"borrador",almacen_id,"MXN",
             subtotal,impuesto,total,notas,fecha_entrega,"pendiente",uid,now,now))
        oc_id = cur.fetchone()["id"]
        for it in items:
            sub = round(float(it["cantidad"])*float(it["precio_unitario"]),2)
            cur.execute("""INSERT INTO ordenes_compra_items
                (orden_id,item_code,item_nombre,uom,cantidad,precio_unitario,subtotal)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (oc_id,it["codigo"],it["nombre"],it.get("uom",""),
                 float(it["cantidad"]),float(it["precio_unitario"]),sub))
        conn.commit(); cur.close(); conn.close()

        # SAP
        almacen = query("SELECT codigo FROM almacenes WHERE id=%s",(almacen_id,),fetchone=True) if almacen_id else None
        # Buscar CardCode del proveedor
        prov_row = query("SELECT notas FROM clientes WHERE id=%s",(proveedor_id,),fetchone=True) if proveedor_id else None
        card_code=""
        if prov_row and prov_row.get("notas"):
            import re
            m=re.search(r"SAP CardCode:\s*(\S+)",prov_row["notas"] or "")
            if m: card_code=m.group(1)

        oc_data={"proveedor_cardcode":card_code,"fecha_entrega":fecha_entrega,
                 "notas":notas,"almacen_codigo":almacen["codigo"] if almacen else ""}
        sap_ok,sap_msg,sap_de = sap_crear_orden_compra(oc_data,items)
        sap_st = "ok" if sap_ok else "error"
        query("UPDATE ordenes_compra SET sap_doc_entry=%s,sap_sync_status=%s,sap_sync_msg=%s WHERE id=%s",
              (sap_de,sap_st,sap_msg,oc_id),commit=True)

        if sap_ok: flash(f"OC {folio} creada ✅ SAP ID:{sap_de}","success")
        else: flash(f"OC {folio} guardada en portal ⚠ SAP: {sap_msg}","warning")
        return redirect(url_for("detalle_compra",oc_id=oc_id))
    except Exception as e:
        flash(f"Error: {e}","danger"); return redirect(url_for("compras"))

@app.route("/compras/<int:oc_id>")
def detalle_compra(oc_id):
    if not logged_in(): return redirect(url_for("login"))
    oc = query("""SELECT oc.*,u.nombre AS creador_nombre,alm.nombre AS almacen_nombre,alm.codigo AS almacen_codigo
                  FROM ordenes_compra oc
                  LEFT JOIN usuarios u ON u.id=oc.creado_por
                  LEFT JOIN almacenes alm ON alm.id=oc.almacen_id
                  WHERE oc.id=%s""",(oc_id,),fetchone=True)
    if not oc: abort(404)
    items = query("SELECT * FROM ordenes_compra_items WHERE orden_id=%s ORDER BY id",(oc_id,),fetchall=True) or []
    entradas = query("""SELECT e.*,u.nombre AS creador FROM entradas_mercancia e
                        LEFT JOIN usuarios u ON u.id=e.creado_por
                        WHERE e.orden_compra_id=%s ORDER BY e.fecha_creacion DESC""",(oc_id,),fetchall=True) or []
    almacenes_list = query("SELECT id,codigo,nombre FROM almacenes WHERE activo=true ORDER BY nombre",fetchall=True) or []
    return render_template("compra_detalle.html", empresa=EMPRESA, logo=LOGO,
                           oc=oc, items=items, entradas=entradas,
                           almacenes=almacenes_list, estatus_oc=EST_OC)

@app.route("/compras/<int:oc_id>/estatus", methods=["POST"])
def actualizar_estatus_compra(oc_id):
    if not logged_in(): return redirect(url_for("login"))
    nuevo = request.form.get("estatus","borrador")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    query("UPDATE ordenes_compra SET estatus=%s,fecha_actualizacion=%s WHERE id=%s",(nuevo,now,oc_id),commit=True)
    flash("Estatus actualizado","success")
    return redirect(url_for("detalle_compra",oc_id=oc_id))


# ══════════════════════════════════════════════════════════
# ── ENTRADAS DE MERCANCÍA ─────────────────────────────────
# ══════════════════════════════════════════════════════════
def gen_folio_entrada():
    c = query("SELECT COUNT(*) AS c FROM entradas_mercancia",fetchone=True)["c"]
    return f"ENT-{(c+1):04d}"

def sap_crear_goods_receipt(entrada, items):
    """Crea un GoodsReceipt (entrada de mercancía) en SAP via PurchaseDeliveryNotes."""
    s = sap_login()
    if not s: return False,"No se pudo conectar a SAP",None
    try:
        lines=[]
        for it in items:
            line={"ItemCode":it["item_code"],"Quantity":float(it["cantidad_recibida"]),
                  "UnitPrice":float(it["precio_unitario"] or 0)}
            if entrada.get("almacen_codigo"): line["WarehouseCode"]=entrada["almacen_codigo"]
            if it.get("numero_serie"): line["SerialNumbers"]=[{"ManufacturerSerialNumber":it["numero_serie"]}]
            lines.append(line)
        payload={"DocDate":datetime.now().strftime("%Y-%m-%d"),"DocumentLines":lines}
        if entrada.get("sap_oc_entry"): payload["BaseType"]=22; payload["BaseEntry"]=entrada["sap_oc_entry"]
        r = s.post(f"{SAP_BASE_URL}/PurchaseDeliveryNotes",json=payload,timeout=20)
        if r.status_code in [200,201]:
            de=r.json().get("DocEntry") or r.json().get("DocNum")
            return True,f"Entrada registrada en SAP (DocEntry:{de})",de
        msg=r.json().get("error",{}).get("message","Error")
        return False,f"SAP: {msg}",None
    except Exception as e: return False,str(e),None
    finally: sap_logout(s)

@app.route("/compras/<int:oc_id>/entrada/crear", methods=["POST"])
def crear_entrada(oc_id):
    if not logged_in(): return redirect(url_for("login"))
    if not tiene_permiso("crear","compras"): abort(403)
    uid=session["user_id"]; now=datetime.now().strftime("%Y-%m-%d %H:%M")
    import json as _json
    items_raw=request.form.get("items_json","[]")
    try: items=_json.loads(items_raw)
    except: items=[]

    oc = query("SELECT * FROM ordenes_compra WHERE id=%s",(oc_id,),fetchone=True)
    if not oc: abort(404)
    almacen_id = request.form.get("almacen_id") or oc.get("almacen_id")
    folio = gen_folio_entrada()

    try:
        conn=get_db(); cur=conn.cursor()
        cur.execute("""INSERT INTO entradas_mercancia
            (folio,orden_compra_id,almacen_id,estatus,notas,sap_sync_status,
             creado_por,fecha_creacion,fecha_recepcion)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (folio,oc_id,almacen_id,"recibida",
             request.form.get("notas","").strip(),
             "pendiente",uid,now,now))
        ent_id=cur.fetchone()["id"]
        for it in items:
            recibido=float(it.get("recibido",0))
            cur.execute("""INSERT INTO entradas_mercancia_items
                (entrada_id,item_code,item_nombre,uom,cantidad_pedida,cantidad_recibida,precio_unitario,numero_serie,numero_lote)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (ent_id,it["codigo"],it["nombre"],it.get("uom",""),
                 float(it.get("pedido",0)),recibido,
                 float(it.get("precio",0)),it.get("serie",""),it.get("lote","")))
            # Actualizar stock
            if almacen_id and recibido>0:
                art=query("SELECT id FROM articulos WHERE codigo=%s",(it["codigo"],),fetchone=True)
                if art:
                    cur.execute("""INSERT INTO inventario (articulo_id,almacen_id,stock_actual,ultima_actualizacion)
                                   VALUES (%s,%s,%s,%s)
                                   ON CONFLICT(articulo_id,almacen_id) DO UPDATE
                                   SET stock_actual=inventario.stock_actual+%s,ultima_actualizacion=%s""",
                                (art["id"],almacen_id,recibido,now,recibido,now))
        # Actualizar estatus OC
        cur.execute("UPDATE ordenes_compra SET estatus='recibida',fecha_actualizacion=%s WHERE id=%s",(now,oc_id))
        conn.commit(); cur.close(); conn.close()

        # SAP
        almacen=query("SELECT codigo FROM almacenes WHERE id=%s",(almacen_id,),fetchone=True) if almacen_id else None
        ent_data={"almacen_codigo":almacen["codigo"] if almacen else "","sap_oc_entry":oc.get("sap_doc_entry")}
        sap_ok,sap_msg,sap_de=sap_crear_goods_receipt(ent_data,items)
        query("UPDATE entradas_mercancia SET sap_doc_entry=%s,sap_sync_status=%s,sap_sync_msg=%s WHERE id=%s",
              ("ok" if sap_ok else "error",sap_msg,sap_de or None,ent_id) if False else
              (sap_de,"ok" if sap_ok else "error",sap_msg,ent_id),commit=True)

        if sap_ok: flash(f"Entrada {folio} registrada ✅ SAP:{sap_de}","success")
        else: flash(f"Entrada {folio} guardada ⚠ SAP:{sap_msg}","warning")
    except Exception as e:
        flash(f"Error: {e}","danger")
    return redirect(url_for("detalle_compra",oc_id=oc_id))


# ══════════════════════════════════════════════════════════
# ── ÓRDENES DE VENTA ──────────────────────────────────────
# ══════════════════════════════════════════════════════════
EST_OV=["borrador","confirmada","en proceso","surtida","cancelada"]

def gen_folio_ov():
    c=query("SELECT COUNT(*) AS c FROM ordenes_venta",fetchone=True)["c"]
    return f"OV-{(c+1):04d}"

def sap_crear_orden_venta(ov,items):
    s=sap_login()
    if not s: return False,"No se pudo conectar a SAP",None
    try:
        lines=[]
        for it in items:
            item_code = it.get("item_code") or it.get("codigo","")
            if not item_code: continue
            line={"ItemCode":item_code,"Quantity":float(it.get("cantidad",1)),
                  "UnitPrice":float(it.get("precio_unitario",0)),
                  "DiscountPercent":float(it.get("descuento",0))}
            if ov.get("almacen_codigo"): line["WarehouseCode"]=ov["almacen_codigo"]
            lines.append(line)
        payload={"CardCode":ov.get("cliente_cardcode",""),
                 "DocDueDate":ov.get("fecha_entrega",""),
                 "DocumentLines":lines}
        if ov.get("notas"): payload["Comments"]=ov["notas"]
        r=s.post(f"{SAP_BASE_URL}/Orders",json=payload,timeout=20)
        if r.status_code in [200,201]:
            de=r.json().get("DocEntry") or r.json().get("DocNum")
            return True,f"OV creada en SAP (DocEntry:{de})",de
        msg=r.json().get("error",{}).get("message","Error")
        return False,f"SAP:{msg}",None
    except Exception as e: return False,str(e),None
    finally: sap_logout(s)

@app.route("/ventas")
def ventas():
    if not logged_in(): return redirect(url_for("login"))
    uid=session["user_id"]; rol=session["rol"]
    fil_est=request.args.get("estatus",""); q=request.args.get("q","").strip()
    base="""SELECT ov.*,u.nombre AS creador_nombre,alm.nombre AS almacen_nombre
            FROM ordenes_venta ov
            LEFT JOIN usuarios u ON u.id=ov.creado_por
            LEFT JOIN almacenes alm ON alm.id=ov.almacen_id WHERE 1=1"""
    params=[]
    if not can_see_all() and rol!="supervisor":
        base+=" AND ov.creado_por=%s"; params.append(uid)
    if fil_est: base+=" AND ov.estatus=%s"; params.append(fil_est)
    if q: base+=" AND (ov.folio ILIKE %s OR ov.cliente_nombre ILIKE %s)"; params+=[f"%{q}%",f"%{q}%"]
    base+=" ORDER BY ov.fecha_creacion DESC"
    lista=query(base,tuple(params),fetchall=True) or []
    almacenes_list=query("SELECT id,codigo,nombre FROM almacenes WHERE activo=true ORDER BY nombre",fetchall=True) or []
    cots_pendientes=query("""SELECT c.id,c.folio,c.cliente_nombre,c.total
                              FROM cotizaciones c WHERE c.estatus='aceptada'
                              AND c.id NOT IN (SELECT cotizacion_id FROM ordenes_venta WHERE cotizacion_id IS NOT NULL)
                              ORDER BY c.fecha_creacion DESC LIMIT 20""",fetchall=True) or []
    return render_template("ventas.html", empresa=EMPRESA, logo=LOGO,
                           ordenes=lista, estatus_ov=EST_OV,
                           almacenes=almacenes_list, cots_pendientes=cots_pendientes,
                           fil_est=fil_est, q=q)

@app.route("/ventas/crear", methods=["POST"])
def crear_orden_venta():
    if not logged_in(): return redirect(url_for("login"))
    if not tiene_permiso("crear","ventas"): abort(403)
    uid=session["user_id"]; now=datetime.now().strftime("%Y-%m-%d %H:%M")
    import json as _json
    items_raw=request.form.get("items_json","[]")
    try: items=_json.loads(items_raw)
    except: items=[]
    if not items:
        flash("Agrega al menos un artículo.","danger"); return redirect(url_for("ventas"))

    subtotal=sum(float(i["cantidad"])*float(i["precio_unitario"])*(1-float(i.get("descuento",0))/100) for i in items)
    impuesto=round(subtotal*0.16,2); total=round(subtotal+impuesto,2)
    folio=gen_folio_ov()
    cliente_id=request.form.get("cliente_id") or None
    cliente_nombre=request.form.get("cliente_nombre","").strip()
    almacen_id=request.form.get("almacen_id") or None
    cotizacion_id=request.form.get("cotizacion_id") or None
    fecha_entrega=request.form.get("fecha_entrega","").strip()
    notas=request.form.get("notas","").strip()

    try:
        conn=get_db(); cur=conn.cursor()
        cur.execute("""INSERT INTO ordenes_venta
            (folio,cotizacion_id,cliente_id,cliente_nombre,almacen_id,estatus,moneda,
             subtotal,impuesto,total,notas,fecha_entrega,sap_sync_status,creado_por,fecha_creacion,fecha_actualizacion)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (folio,cotizacion_id,cliente_id,cliente_nombre,almacen_id,"borrador","MXN",
             subtotal,impuesto,total,notas,fecha_entrega,"pendiente",uid,now,now))
        ov_id=cur.fetchone()["id"]
        for it in items:
            sub=round(float(it["cantidad"])*float(it["precio_unitario"])*(1-float(it.get("descuento",0))/100),2)
            cur.execute("""INSERT INTO ordenes_venta_items
                (orden_id,item_code,item_nombre,uom,cantidad,precio_unitario,descuento,subtotal)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (ov_id,it["codigo"],it["nombre"],it.get("uom",""),
                 float(it["cantidad"]),float(it["precio_unitario"]),float(it.get("descuento",0)),sub))
        conn.commit(); cur.close(); conn.close()

        # SAP
        almacen=query("SELECT codigo FROM almacenes WHERE id=%s",(almacen_id,),fetchone=True) if almacen_id else None
        import re
        cli=query("SELECT notas FROM clientes WHERE id=%s",(cliente_id,),fetchone=True) if cliente_id else None
        card_code=""
        if cli and cli.get("notas"):
            m=re.search(r"SAP CardCode:\s*(\S+)",cli["notas"] or "")
            if m: card_code=m.group(1)
        ov_data={"cliente_cardcode":card_code,"fecha_entrega":fecha_entrega,
                 "notas":notas,"almacen_codigo":almacen["codigo"] if almacen else ""}
        sap_ok,sap_msg,sap_de=sap_crear_orden_venta(ov_data,items)
        query("UPDATE ordenes_venta SET sap_doc_entry=%s,sap_sync_status=%s,sap_sync_msg=%s WHERE id=%s",
              (sap_de,"ok" if sap_ok else "error",sap_msg,ov_id),commit=True)

        if sap_ok: flash(f"OV {folio} creada ✅ SAP:{sap_de}","success")
        else: flash(f"OV {folio} guardada ⚠ SAP:{sap_msg}","warning")
        return redirect(url_for("detalle_venta",ov_id=ov_id))
    except Exception as e:
        flash(f"Error: {e}","danger"); return redirect(url_for("ventas"))

@app.route("/ventas/<int:ov_id>")
def detalle_venta(ov_id):
    if not logged_in(): return redirect(url_for("login"))
    ov=query("""SELECT ov.*,u.nombre AS creador_nombre,alm.nombre AS almacen_nombre,alm.codigo AS almacen_codigo
                FROM ordenes_venta ov
                LEFT JOIN usuarios u ON u.id=ov.creado_por
                LEFT JOIN almacenes alm ON alm.id=ov.almacen_id WHERE ov.id=%s""",(ov_id,),fetchone=True)
    if not ov: abort(404)
    items=query("SELECT * FROM ordenes_venta_items WHERE orden_id=%s ORDER BY id",(ov_id,),fetchall=True) or []
    remisiones=query("""SELECT r.*,u.nombre AS creador FROM remisiones r
                        LEFT JOIN usuarios u ON u.id=r.creado_por
                        WHERE r.orden_venta_id=%s ORDER BY r.fecha_creacion DESC""",(ov_id,),fetchall=True) or []
    almacenes_list=query("SELECT id,codigo,nombre FROM almacenes WHERE activo=true ORDER BY nombre",fetchall=True) or []
    return render_template("venta_detalle.html", empresa=EMPRESA, logo=LOGO,
                           ov=ov, items=items, remisiones=remisiones,
                           almacenes=almacenes_list, estatus_ov=EST_OV)

@app.route("/ventas/<int:ov_id>/estatus", methods=["POST"])
def actualizar_estatus_venta(ov_id):
    if not logged_in(): return redirect(url_for("login"))
    nuevo=request.form.get("estatus","borrador")
    now=datetime.now().strftime("%Y-%m-%d %H:%M")
    query("UPDATE ordenes_venta SET estatus=%s,fecha_actualizacion=%s WHERE id=%s",(nuevo,now,ov_id),commit=True)
    flash("Estatus actualizado","success")
    return redirect(url_for("detalle_venta",ov_id=ov_id))


# ══════════════════════════════════════════════════════════
# ── REMISIONES ────────────────────────────────────────────
# ══════════════════════════════════════════════════════════
def gen_folio_rem():
    c=query("SELECT COUNT(*) AS c FROM remisiones",fetchone=True)["c"]
    return f"REM-{(c+1):04d}"

def sap_crear_delivery(rem,items):
    s=sap_login()
    if not s: return False,"No se pudo conectar a SAP",None
    try:
        lines=[]
        for it in items:
            item_code = it.get("item_code") or it.get("codigo","")
            if not item_code: continue
            line={"ItemCode":item_code,"Quantity":float(it.get("cantidad",1)),
                  "UnitPrice":float(it.get("precio_unitario") or it.get("precio",0))}
            if rem.get("almacen_codigo"): line["WarehouseCode"]=rem["almacen_codigo"]
            if it.get("serie"): line["SerialNumbers"]=[{"ManufacturerSerialNumber":it["serie"]}]
            lines.append(line)
        payload={"CardCode":rem.get("cliente_cardcode",""),
                 "DocDate":datetime.now().strftime("%Y-%m-%d"),
                 "DocumentLines":lines}
        if rem.get("sap_ov_entry"): payload["BaseType"]=17; payload["BaseEntry"]=rem["sap_ov_entry"]
        r=s.post(f"{SAP_BASE_URL}/DeliveryNotes",json=payload,timeout=20)
        if r.status_code in [200,201]:
            de=r.json().get("DocEntry") or r.json().get("DocNum")
            return True,f"Remisión creada en SAP (DocEntry:{de})",de
        msg=r.json().get("error",{}).get("message","Error")
        return False,f"SAP:{msg}",None
    except Exception as e: return False,str(e),None
    finally: sap_logout(s)

@app.route("/ventas/<int:ov_id>/remision/crear", methods=["POST"])
def crear_remision(ov_id):
    if not logged_in(): return redirect(url_for("login"))
    if not tiene_permiso("crear","ventas"): abort(403)
    uid=session["user_id"]; now=datetime.now().strftime("%Y-%m-%d %H:%M")
    import json as _json
    items_raw=request.form.get("items_json","[]")
    try: items=_json.loads(items_raw)
    except: items=[]

    ov=query("SELECT * FROM ordenes_venta WHERE id=%s",(ov_id,),fetchone=True)
    if not ov: abort(404)
    almacen_id=request.form.get("almacen_id") or ov.get("almacen_id")
    folio=gen_folio_rem()

    try:
        conn=get_db(); cur=conn.cursor()
        cur.execute("""INSERT INTO remisiones
            (folio,orden_venta_id,cliente_id,cliente_nombre,almacen_id,estatus,
             notas,sap_sync_status,creado_por,fecha_creacion,fecha_entrega)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (folio,ov_id,ov["cliente_id"],ov["cliente_nombre"],almacen_id,"entregada",
             request.form.get("notas","").strip(),"pendiente",uid,now,now))
        rem_id=cur.fetchone()["id"]
        for it in items:
            sub=round(float(it["cantidad"])*float(it["precio"]),2)
            cur.execute("""INSERT INTO remisiones_items
                (remision_id,item_code,item_nombre,uom,cantidad,precio_unitario,subtotal,numero_serie,numero_lote)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (rem_id,it["codigo"],it["nombre"],it.get("uom",""),
                 float(it["cantidad"]),float(it["precio"]),sub,
                 it.get("serie",""),it.get("lote","")))
            # Reducir stock
            if almacen_id:
                art=query("SELECT id FROM articulos WHERE codigo=%s",(it["codigo"],),fetchone=True)
                if art:
                    cur.execute("""UPDATE inventario SET stock_actual=stock_actual-%s,ultima_actualizacion=%s
                                   WHERE articulo_id=%s AND almacen_id=%s""",
                                (float(it["cantidad"]),now,art["id"],almacen_id))
        # Actualizar OV
        cur.execute("UPDATE ordenes_venta SET estatus='surtida',fecha_actualizacion=%s WHERE id=%s",(now,ov_id))
        conn.commit(); cur.close(); conn.close()

        # SAP
        almacen=query("SELECT codigo FROM almacenes WHERE id=%s",(almacen_id,),fetchone=True) if almacen_id else None
        import re
        cli=query("SELECT notas FROM clientes WHERE id=%s",(ov["cliente_id"],),fetchone=True) if ov.get("cliente_id") else None
        card_code=""
        if cli and cli.get("notas"):
            m=re.search(r"SAP CardCode:\s*(\S+)",cli["notas"] or "")
            if m: card_code=m.group(1)
        rem_data={"cliente_cardcode":card_code,"almacen_codigo":almacen["codigo"] if almacen else "",
                  "sap_ov_entry":ov.get("sap_doc_entry")}
        sap_ok,sap_msg,sap_de=sap_crear_delivery(rem_data,items)
        query("UPDATE remisiones SET sap_doc_entry=%s,sap_sync_status=%s,sap_sync_msg=%s WHERE id=%s",
              (sap_de,"ok" if sap_ok else "error",sap_msg,rem_id),commit=True)

        if sap_ok: flash(f"Remisión {folio} creada ✅ SAP:{sap_de}","success")
        else: flash(f"Remisión {folio} guardada ⚠ SAP:{sap_msg}","warning")
    except Exception as e:
        flash(f"Error: {e}","danger")
    return redirect(url_for("detalle_venta",ov_id=ov_id))

@app.route("/remisiones/<int:rem_id>/pdf")
def remision_pdf(rem_id):
    if not logged_in(): return redirect(url_for("login"))
    rem=query("""SELECT r.*,u.nombre AS creador,alm.nombre AS almacen_nombre
                 FROM remisiones r LEFT JOIN usuarios u ON u.id=r.creado_por
                 LEFT JOIN almacenes alm ON alm.id=r.almacen_id WHERE r.id=%s""",(rem_id,),fetchone=True)
    if not rem: abort(404)
    items=query("SELECT * FROM remisiones_items WHERE remision_id=%s ORDER BY id",(rem_id,),fetchall=True) or []
    config=query("SELECT * FROM config WHERE id=1",fetchone=True) or {}
    return render_template("remision_pdf.html", rem=rem, items=items, empresa=EMPRESA, config=config)

