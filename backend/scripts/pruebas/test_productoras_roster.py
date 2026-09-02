"""El músico dentro de una productora: ficha propia, sin facturación.

David, 28/08: va a cerrar con una empresa de más de 100 músicos. Para que la
plataforma le QUITE trabajo a la empresa, cada músico necesita su propia cuenta
y su propio calendario. Y decidió el dinero: SHOWMA le factura y le paga a la
PRODUCTORA, y la productora liquida a los suyos fuera de SHOWMA. Así que la
ficha del músico no lleva RFC, ni CLABE, ni banco, ni CFDI, ni tarifas.

Esto es una frontera de dinero, no una pantalla. Esconder la sección en el
navegador no sirve de nada: lo que cuenta es que el SERVIDOR cierre la puerta,
porque cualquiera con la sesión abierta puede llamar al endpoint a mano.

Dos controles invertidos, sin los cuales esta prueba pasaría por el motivo
equivocado:

  - Sección 4 comprueba que el dato fiscal se ESCONDE pero NO SE BORRA: se
    siembra un RFC en la base, se comprueba que la API devuelve nulo, y después
    se vuelve a mirar la base para verificar que el dato sigue ahí. Sin esa
    tercera parte, un `UPDATE ... SET rfc=NULL` accidental también pasaría.
  - Sección 6 comprueba que las 10 puertas del dinero dan 403 al músico Y que
    NO dan 403 al artista independiente. Sin la segunda mitad, romper el login
    entero haría pasar la prueba.

Corre contra un SERVIDOR DE VERDAD, sobre una COPIA de una base con datos
(la del repositorio sirve; una copia de producción es mejor porque trae fichas
viejas y ahí se nota si la columna nueva movió a alguien de sitio). Nunca sobre
producción: la prueba escribe.

Correr:
    cp /ruta/ricky.db /tmp/copia.db
    DATABASE_URL="sqlite+aiosqlite:////tmp/copia.db" \
        .venv/bin/python -m uvicorn app.main:app --port 8461 &
    RICKY_DB=/tmp/copia.db python scripts/pruebas/test_productoras_roster.py
"""
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = os.environ.get("RICKY_BASE", "http://localhost:8461")
API = BASE + "/api/v1"
DB = os.environ.get("RICKY_DB", "/tmp/copia_roster.db")

BACK = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACK))
from app.core.security import hash_password  # noqa: E402

fallos = []


def ok(cond, msg, extra=""):
    print(("  OK   " if cond else "  FALLA") + " " + msg + (f"  [{extra}]" if extra else ""))
    if not cond:
        fallos.append(msg)


def _pide(req):
    try:
        r = urllib.request.urlopen(req)
        return r.read().decode(), r.status
    except urllib.error.HTTPError as e:
        return e.read().decode(), e.code


def get(path, token=None):
    h = {"Authorization": "Bearer " + token} if token else {}
    return _pide(urllib.request.Request(API + path, headers=h))


def _cuerpo(path, cuerpo, token, metodo):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    return _pide(urllib.request.Request(
        API + path, data=json.dumps(cuerpo).encode(), headers=h, method=metodo))


def post(path, cuerpo, token=None):
    return _cuerpo(path, cuerpo, token, "POST")


def patch(path, cuerpo, token=None):
    return _cuerpo(path, cuerpo, token, "PATCH")


def delete(path, token=None):
    h = {"Authorization": "Bearer " + token} if token else {}
    return _pide(urllib.request.Request(API + path, headers=h, method="DELETE"))


def multipart(path, token, campos, ficheros):
    """POST multipart a mano. Hace falta para /me/fiscal/csd: la guarda vive
    DENTRO de la función, así que FastAPI parsea el cuerpo primero y mandar la
    petición vacía daría 422 en vez del 403 que queremos comprobar."""
    lim = "----ricky" + uuid.uuid4().hex
    tr = []
    for k, v in campos.items():
        tr.append(f"--{lim}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n")
    for k, (nombre, datos) in ficheros.items():
        tr.append(f"--{lim}\r\nContent-Disposition: form-data; name=\"{k}\"; "
                  f"filename=\"{nombre}\"\r\nContent-Type: application/octet-stream\r\n\r\n{datos}\r\n")
    tr.append(f"--{lim}--\r\n")
    return _pide(urllib.request.Request(
        API + path, data="".join(tr).encode(),
        headers={"Content-Type": f"multipart/form-data; boundary={lim}",
                 "Authorization": "Bearer " + token},
        method="POST"))


def sql(q, args=()):
    con = sqlite3.connect(DB)
    try:
        cur = con.execute(q, args)
        filas = cur.fetchall()
        con.commit()
        return filas
    finally:
        con.close()


def login(correo, clave):
    cuerpo, code = post("/auth/login", {"email": correo, "password": clave})
    if code != 200:
        raise SystemExit(f"No pude entrar como {correo}: {code} {cuerpo[:200]}")
    return json.loads(cuerpo)["access_token"]


def alta_artista(nombre, clave="Prueba2026!"):
    """Un artista independiente recién registrado, con su propia cuenta."""
    correo = f"t{uuid.uuid4().hex[:10]}@prueba.mx"
    cuerpo, code = post("/auth/register/artist", {
        "email": correo, "password": clave, "full_name": nombre,
        "stage_name": nombre, "artist_type": "Solista", "phone": "9990000000",
        "base_city": "Cancún",
    })
    if code != 201:
        raise SystemExit(f"No pude registrar a {nombre}: {code} {cuerpo[:300]}")
    tok = json.loads(cuerpo)["access_token"]
    aid = json.loads(get("/me/artist", tok)[0])["id"]
    return correo, clave, tok, aid


CLAVE = "Prueba2026!"
sello = uuid.uuid4().hex[:8]

print("Preparando: una productora y un artista independiente")
prod_mail, _, PROD, PROD_ID = alta_artista(f"Productora {sello}")
indie_mail, _, INDIE, INDIE_ID = alta_artista(f"Indie {sello}")
print(f"  productora artist_id={PROD_ID}   independiente artist_id={INDIE_ID}")


print("\n1. La columna nueva no metió a nadie dentro de una empresa")
sueltos = sql("SELECT COUNT(*) FROM artists WHERE parent_id IS NOT NULL "
              "AND id NOT IN (SELECT id FROM artists WHERE stage_name LIKE ?)",
              (f"%{sello}%",))[0][0]
ok(sueltos == 0,
   "ningún perfil que ya existía quedó colgado de una productora",
   f"{sueltos} con parent_id")


print("\n1b. Dar de alta músicos NO está abierto a cualquier proveedor")
# Dar de alta CREA una cuenta y MANDA un correo a la dirección que escriban. Si
# eso quedara abierto a cualquiera con sesión, SHOWMA sería una forma de mandar
# correo desde su propio dominio a quien fuera. El permiso lo prende el
# administrador en la ficha, uno por uno.
cuerpo, code = post("/me/musicos", {
    "stage_name": "No deberia existir", "email": f"x{uuid.uuid4().hex[:8]}@prueba.mx",
}, PROD)
ok(code == 403, "sin el permiso de productora, el alta responde 403", f"{code} {cuerpo[:120]}")
colados = sql("SELECT COUNT(*) FROM artists WHERE stage_name='No deberia existir'")[0][0]
# Lo que importa no es el número de la respuesta, es que no se haya creado nada:
# un 403 devuelto DESPUÉS de haber dado de alta la ficha sería igual de inútil.
ok(colados == 0, "y no se creó ninguna ficha ni cuenta", f"{colados} coladas")

cuerpo, code = post("/me/musicos/lote", {"musicos": [
    {"stage_name": "Lote sin permiso", "email": f"y{uuid.uuid4().hex[:8]}@prueba.mx"}]}, PROD)
ok(code == 403, "el alta por lista también está cerrada", f"{code} {cuerpo[:120]}")

sql("UPDATE artists SET is_productora=1 WHERE id=?", (PROD_ID,))
print("  (el administrador le prende el permiso a la productora)")


print("\n2. La productora da de alta a un músico")
mus_mail = f"m{uuid.uuid4().hex[:10]}@prueba.mx"
cuerpo, code = post("/me/musicos", {
    "stage_name": f"Saxofón {sello}", "email": mus_mail,
    "phone": "9981112233", "artist_type": "Solista",
}, PROD)
ok(code == 201, "el alta responde 201", f"{code} {cuerpo[:160]}")
MUS = json.loads(cuerpo) if code == 201 else {}
MUS_ID = MUS.get("id")
ok(bool(MUS_ID), "devuelve la ficha del músico", str(MUS_ID))

fila = sql("SELECT parent_id, user_id FROM artists WHERE id=?", (MUS_ID,))
ok(bool(fila) and fila[0][0] == PROD_ID,
   "el músico cuelga de la productora", str(fila))
ok(bool(fila) and fila[0][1] is not None,
   "el músico tiene su propia cuenta de acceso")

# La productora NO elige la contraseña: se le manda al músico un enlace para
# que ponga la suya. Que exista el token es la prueba de que ese camino corrió.
tokens = sql("SELECT COUNT(*) FROM password_reset_tokens WHERE user_id=?",
             (fila[0][1],))[0][0] if fila else 0
if MUS.get("invitacion_enviada"):
    ok(tokens >= 1, "se le emitió el enlace para que ponga su contraseña",
       f"{tokens} token(s)")
else:
    # Sin SMTP local el correo no sale y el token no se emite. Se dice en voz
    # alta en vez de dar un OK: un "pasa" aquí sería un pase falso, y este es
    # justo el camino por el que la empresa NO se entera de la contraseña.
    print("  NO CUBIERTO  el envío de la invitación: no hay SMTP en local. "
          "Comprobar a mano en la demo.")
# Lo que sí se comprueba sin SMTP: que la clave inicial es de verdad aleatoria.
# Si el alta la dejara predecible -en blanco, el correo, el nombre artístico-,
# la productora podría entrar como él y aceptar contrataciones en su nombre.
predecibles = ["", mus_mail, MUS.get("stage_name", ""), CLAVE, "123456", "showma"]
adivinada = [c for c in predecibles
             if post("/auth/login", {"email": mus_mail, "password": c})[1] == 200]
ok(not adivinada,
   "la clave inicial no es adivinable: nadie entra como el músico sin su enlace",
   ", ".join(repr(c) for c in adivinada))

# Para poder entrar como él en el resto de la prueba le ponemos una clave
# directo en la base. En la vida real esto lo hace ÉL desde el enlace.
sql("UPDATE users SET hashed_password=? WHERE id=?", (hash_password(CLAVE), fila[0][1]))
MUSICO = login(mus_mail, CLAVE)


print("\n3. Cada quien ve lo suyo")
mios, _ = get("/me/musicos", PROD)
ok(any(m["id"] == MUS_ID for m in json.loads(mios)),
   "la productora ve a su músico en Mis músicos")
ajenos, _ = get("/me/musicos", INDIE)
ok(json.loads(ajenos) == [],
   "el artista independiente no ve a nadie", ajenos[:80])
propios, _ = get("/me/musicos", MUSICO)
ok(json.loads(propios) == [],
   "el músico tampoco ve equipo propio", propios[:80])


print("\n4. La facturación se ESCONDE, no se borra")
sql("UPDATE artists SET rfc=?, bank_clabe=?, bank_account=? WHERE id=?",
    ("XAXX010101000", "032180000118359719", "1234567890", MUS_ID))
perfil = json.loads(get("/me/artist", MUSICO)[0])
for campo in ("rfc", "bank_clabe", "bank_account", "bank_name", "legal_name"):
    ok(perfil.get(campo) is None,
       f"el músico no recibe {campo}", repr(perfil.get(campo)))
ok(perfil.get("parent_id") == PROD_ID,
   "la ficha dice de qué productora cuelga, para que la pantalla lo sepa")

# CONTROL INVERTIDO. Sin esto, un borrado accidental de la columna también
# haría pasar lo de arriba.
guardado = sql("SELECT rfc, bank_clabe FROM artists WHERE id=?", (MUS_ID,))[0]
ok(guardado[0] == "XAXX010101000" and guardado[1] == "032180000118359719",
   "el dato SIGUE en la base: se escondió, no se destruyó", str(guardado))

# Y el independiente sí ve lo suyo.
sql("UPDATE artists SET rfc=? WHERE id=?", ("XEXX010101000", INDIE_ID))
ok(json.loads(get("/me/artist", INDIE)[0]).get("rfc") == "XEXX010101000",
   "CONTROL: el artista independiente sí recibe su propio RFC")


print("\n5. Nadie le escribe datos fiscales a esa ficha, ni él ni la empresa")
# Quien cobra es la productora, con SU RFC. Un RFC en la ficha del músico sería
# un dato que nadie sabría de dónde salió y que no le toca cobrar.
_, code = patch("/me/artist", {"rfc": "AAAA010101AAA", "bank_clabe": "999"}, MUSICO)
tras = sql("SELECT rfc, bank_clabe FROM artists WHERE id=?", (MUS_ID,))[0]
ok(tras[0] == "XAXX010101000" and tras[1] == "032180000118359719",
   "el PATCH a mano no le cambió el RFC ni la CLABE", f"{code} {tras}")
# CONTROL invertido: el filtro tiene que quitar SÓLO lo fiscal. Va por la vía de
# la productora porque desde el 02/09 el músico ya no edita su propia ficha (ver
# sección 12), así que si se probara con su token no se distinguiría "filtró el
# RFC" de "rechazó la petición entera".
_, code = patch(f"/me/musicos/{MUS_ID}",
                {"rfc": "AAAA010101AAA", "bio": "toco el saxo"}, PROD)
tras2 = sql("SELECT rfc, bio FROM artists WHERE id=?", (MUS_ID,))[0]
ok(code == 200 and tras2[1] == "toco el saxo" and tras2[0] == "XAXX010101000",
   "CONTROL: en la misma petición se guarda la bio y se descarta el RFC",
   f"{code} {tras2}")


print("\n6. Las puertas del dinero, cerradas para él y abiertas para el indie")
PUERTAS = [
    ("GET", "/me/payouts", None),
    # El cuerpo tiene que ser VÁLIDO. La guarda vive dentro de la función, así
    # que un cuerpo mal formado se queda en el 422 de validación y nunca llega
    # a la puerta: daría por buena una prueba que no probó nada.
    ("POST", "/me/payouts/mark", {"company_id": 1, "period": "2026-08-Q1", "paid": True}),
    ("GET", "/me/fiscal", None),
    ("POST", "/me/fiscal", {"rfc": "XAXX010101000"}),
    ("GET", "/me/cfdis", None),
    ("GET", "/me/cfdis/1/file/pdf", None),
    ("GET", "/me/artist/client-rates", None),
    ("POST", "/me/artist/client-rates", {"company_id": 1, "special_price": 100}),
    ("DELETE", "/me/artist/client-rates/1", None),
]


def toca(metodo, ruta, cuerpo, token):
    if metodo == "GET":
        return get(ruta, token)[1]
    if metodo == "DELETE":
        return delete(ruta, token)[1]
    return _cuerpo(ruta, cuerpo or {}, token, metodo)[1]


for metodo, ruta, cuerpo in PUERTAS:
    ok(toca(metodo, ruta, cuerpo, MUSICO) == 403,
       f"{metodo} {ruta} le da 403 al músico de la productora",
       str(toca(metodo, ruta, cuerpo, MUSICO)))

csd = multipart("/me/fiscal/csd", MUSICO,
                {"password": "x", "rfc": "XAXX010101000"},
                {"cer": ("a.cer", "x"), "key": ("a.key", "x")})[1]
ok(csd == 403, "POST /fiscal/csd le da 403 al músico", str(csd))

# CONTROL INVERTIDO: si todo diera 403 (login roto, permiso mal puesto) lo de
# arriba pasaría igual y no probaría nada.
abiertas = [f"{m} {r}" for m, r, c in PUERTAS if toca(m, r, c, INDIE) == 403]
ok(not abiertas,
   "CONTROL: al artista independiente NINGUNA de esas puertas le da 403",
   ", ".join(abiertas))


print("\n7. Un solo nivel: el músico no puede tener equipo propio")
_, code = post("/me/musicos", {"stage_name": "Sub", "email": f"s{sello}@prueba.mx"}, MUSICO)
ok(code == 403, "un músico dentro de una empresa no puede dar de alta a otros", str(code))


print("\n8. No se secuestran cuentas ajenas")
_, code = post("/me/musicos", {"stage_name": "Robo", "email": indie_mail}, PROD)
ok(code == 409,
   "un correo que ya tiene cuenta en SHOWMA no se engancha sin permiso", str(code))


print("\n9. Bloquear fechas es de cada músico, no de la empresa")
DIA = "2027-03-15"
_, code = post("/me/blocked-dates", {"date": DIA, "reason": "boda"}, MUSICO)
ok(code == 201, "el músico bloquea su propio día", str(code))
suyos = [d["date"] for d in json.loads(get("/me/blocked-dates", MUSICO)[0])]
ok(DIA in suyos, "le aparece bloqueado a él")
dela = [d["date"] for d in json.loads(get("/me/blocked-dates", PROD)[0])]
ok(DIA not in dela,
   "a la productora NO se le bloqueó ese día por rebote", str(dela[:5]))
delindie = [d["date"] for d in json.loads(get("/me/blocked-dates", INDIE)[0])]
ok(DIA not in delindie, "y a un tercero tampoco")


print("\n10. El alta por lista: 200 músicos no se capturan de uno en uno")
repetido = f"r{uuid.uuid4().hex[:10]}@prueba.mx"
lote = [
    {"stage_name": f"Lote A {sello}", "email": f"a{uuid.uuid4().hex[:10]}@prueba.mx"},
    {"stage_name": f"Lote B {sello}", "email": repetido},
    {"stage_name": f"Lote C {sello}", "email": repetido},          # repetido en la lista
    {"stage_name": f"Lote D {sello}", "email": indie_mail},        # ya tiene cuenta
    {"stage_name": f"Lote E {sello}", "email": "  "},              # sin correo
]
cuerpo, code = post("/me/musicos/lote", {"musicos": lote}, PROD)
ok(code == 200, "el alta por lista responde 200", f"{code} {cuerpo[:160]}")
res = json.loads(cuerpo) if code == 200 else {"creados": [], "rechazados": []}
EXTRA = [m["id"] for m in res.get("creados", [])]
ok(len(EXTRA) == 2, "entran los buenos", f"{len(EXTRA)} creados")
ok(len(res.get("rechazados", [])) == 3, "y salen los tres malos con su motivo",
   json.dumps(res.get("rechazados", []), ensure_ascii=False)[:200])
# Lo que de verdad se está probando: que un renglón malo NO tumbe a los buenos.
# Un rollback general obligaría a la empresa a depurar 200 renglones a ciegas.
vivos = sql("SELECT COUNT(*) FROM artists WHERE parent_id=? AND stage_name LIKE ?",
            (PROD_ID, f"Lote%{sello}"))[0][0]
ok(vivos == 2, "los buenos quedaron guardados de verdad, no sólo en la respuesta",
   f"{vivos} en la base")
motivos = " ".join(r["motivo"] for r in res.get("rechazados", []))
ok("repetido en tu lista" in motivos,
   "al correo escrito dos veces se le dice que está repetido, no que sea de otro")
# Sin correo: la ficha NO se crea. Si se creara, la empresa tendría un músico
# que jamás podría entrar y nadie sabría por qué.
sin_correo = sql("SELECT COUNT(*) FROM artists WHERE stage_name=?",
                 (f"Lote E {sello}",))[0][0]
ok(sin_correo == 0, "el renglón sin correo no dejó ficha muerta", str(sin_correo))
# El tope existe para que una lista pegada por error no dé de alta 50 mil.
_, code = post("/me/musicos/lote", {"musicos": [
    {"stage_name": "X", "email": f"z{i}@prueba.mx"} for i in range(501)]}, PROD)
ok(code == 422, "una lista de más de 500 se rechaza entera", str(code))


print("\n11. Nadie se regala a sí mismo un permiso que otorga SHOWMA")
# Estos tres los da SHOWMA, no el que llena su ficha. is_partner además es el
# add-on de PAGO (Market Intelligence, Tendencias, Noticias): si un proveedor se
# lo pone solo con un PATCH, deja de pagarlo y la pantalla no se entera.
antes = sql("SELECT is_verified, is_partner, is_productora FROM artists WHERE id=?",
            (INDIE_ID,))[0]
cuerpo, code = patch("/me/artist", {
    "is_verified": True, "is_partner": True, "is_productora": True,
    "partner_monthly_fee": 0, "bio": "toco de todo",
}, INDIE)
ok(code == 200, "el PATCH pasa (no se le grita por intentarlo)", str(code))
despues = sql("SELECT is_verified, is_partner, is_productora FROM artists WHERE id=?",
              (INDIE_ID,))[0]
ok(tuple(despues) == tuple(antes),
   "ni verificado, ni productora, ni partner: los tres siguen igual",
   f"{antes} -> {despues}")
# Control: el mismo PATCH SÍ tenía que guardar lo que sí es suyo. Sin esto, un
# endpoint roto que ignorara el cuerpo entero también pasaría esta prueba.
ok(json.loads(get("/me/artist", INDIE)[0]).get("bio") == "toco de todo",
   "y lo que sí es suyo sí se guardó (la biografía)")
ok(json.loads(get("/auth/me", INDIE)[0]).get("is_partner") is False,
   "el menú de las pantallas de pago no se le abre")


print("\n12. La ficha del músico la manda la EMPRESA, no él")
# David, 02/09: "El perfil sería gestionado, visto y cobrado por la productora".
# Su cuenta es para bloquear fechas y consultar actuaciones, nada más. Se cierra
# en el servidor: esconder el formulario no sirve, la API se llama a mano.
antes_ficha = sql("SELECT stage_name, bio FROM artists WHERE id=?", (MUS_ID,))[0]
cuerpo, code = patch("/me/artist", {"stage_name": "Me cambio el nombre",
                                    "bio": "y me escribo la bio"}, MUSICO)
ok(code == 403, "el músico no puede editar su propia ficha", f"{code} {cuerpo[:120]}")
despues_ficha = sql("SELECT stage_name, bio FROM artists WHERE id=?", (MUS_ID,))[0]
ok(tuple(antes_ficha) == tuple(despues_ficha),
   "y nada cambió en la base", f"{antes_ficha} -> {despues_ficha}")
_, c_show = post("/me/artist/shows", {"show_name": "Mi show", "category": "Musica",
                                      "subcategory": "Solista"}, MUSICO)
ok(c_show == 403, "tampoco publica shows por su cuenta", str(c_show))
_, c_doc = multipart("/me/artist/documents", MUSICO,
                     {"doc_type": "identificacion"}, {"file": ("id.pdf", "%PDF-1.4")})
ok(c_doc == 403, "ni sube documentos legales", str(c_doc))
# CONTROL invertido: el independiente SÍ tiene que poder hacer las tres. Sin
# esto, romper el login o el router entero también daría 403 y pasaría.
_, ci1 = patch("/me/artist", {"bio": "sigo mandando en lo mío"}, INDIE)
_, ci2 = post("/me/artist/shows", {"show_name": f"Show indie {sello}",
                                   "category": "Musica", "subcategory": "Solista"}, INDIE)
ok(ci1 == 200 and ci2 in (200, 201),
   "CONTROL: el artista independiente sí edita su ficha y sí publica",
   f"perfil={ci1} show={ci2}")


print("\n13. La productora sí edita la ficha de los suyos")
cuerpo, code = get(f"/me/musicos/{MUS_ID}", PROD)
ok(code == 200, "puede abrir la ficha completa de su músico", str(code))
ficha = json.loads(cuerpo) if code == 200 else {}
# La ficha COMPLETA y no la fila de la tabla: si el formulario se abriera sin
# bio ni ciudad, al guardar guardaría esos blancos y borraría datos buenos.
ok("bio" in ficha and "base_city" in ficha,
   "y viene completa (bio y ciudad incluidas), no sólo lo de la tabla")
ok(ficha.get("parent_name") == f"Productora {sello}",
   "trae el nombre de la productora, para poder decirle a quién pedirle un cambio",
   str(ficha.get("parent_name")))
_, code = patch(f"/me/musicos/{MUS_ID}", {
    "stage_name": f"Saxofonista {sello}", "bio": "20 años tocando en la Riviera",
    "base_city": "Playa del Carmen", "auto_confirm_bookings": True,
}, PROD)
ok(code == 200, "y guarda los cambios", str(code))
fila = sql("SELECT stage_name, bio, base_city, auto_confirm_bookings "
           "FROM artists WHERE id=?", (MUS_ID,))[0]
ok(fila[0] == f"Saxofonista {sello}" and fila[2] == "Playa del Carmen" and fila[3] == 1,
   "los cambios están en la base", str(fila))
# Que escriba la EMPRESA no agranda lo que se puede escribir.
antes_p = sql("SELECT is_partner, is_verified, is_productora, rfc FROM artists WHERE id=?",
              (MUS_ID,))[0]
patch(f"/me/musicos/{MUS_ID}", {"is_partner": True, "is_verified": True,
                                "is_productora": True, "rfc": "XAXX010101000"}, PROD)
despues_p = sql("SELECT is_partner, is_verified, is_productora, rfc FROM artists WHERE id=?",
                (MUS_ID,))[0]
ok(tuple(antes_p) == tuple(despues_p),
   "ni la empresa le regala el sello, el plan de pago ni un RFC",
   f"{antes_p} -> {despues_p}")
# Y sólo los suyos: el independiente no cuelga de ella.
_, code = patch(f"/me/musicos/{INDIE_ID}", {"bio": "no deberia entrar"}, PROD)
ok(code == 404, "la ficha de un artista ajeno no se toca (404, no 403)", str(code))
ok(json.loads(get("/me/artist", INDIE)[0]).get("bio") != "no deberia entrar",
   "y la bio del independiente sigue intacta")


print("\n14. Los shows del músico los publica la empresa")
# El hotel lo busca por su show: sin al menos uno no aparece como contratable, y
# la empresa NO conoce la contraseña de sus músicos -es a propósito-, así que si
# no pudiera publicar desde aquí, un catálogo de 200 no habría forma de armarlo.
cuerpo, code = post(f"/me/musicos/{MUS_ID}/shows", {
    "show_name": f"Sax lounge {sello}", "category": "Musica",
    "subcategory": "Solista", "price_hotel": 8000,
}, PROD)
ok(code == 201, "publica un show en la ficha de su músico", f"{code} {cuerpo[:150]}")
SHOW_ID = json.loads(cuerpo)["id"] if code == 201 else None
duenyo = sql("SELECT artist_id FROM shows WHERE id=?", (SHOW_ID,))[0][0] if SHOW_ID else None
ok(duenyo == MUS_ID, "y queda colgado del MÚSICO, no de la empresa", str(duenyo))
lista, code = get(f"/me/musicos/{MUS_ID}/shows", PROD)
ok(code == 200 and any(s["id"] == SHOW_ID for s in json.loads(lista)),
   "sale en la lista de sus shows")
# La subcategoría tiene que existir DENTRO de su categoría o el servidor la
# rechaza: por eso los desplegables se arman con la taxonomía y no a mano.
_, code = post(f"/me/musicos/{MUS_ID}/shows", {
    "show_name": "Categoria mal", "category": "Musica", "subcategory": "Danza"}, PROD)
ok(code == 422, "una subcategoría que no es de esa categoría se rechaza", str(code))
# El show tiene que ser de ESE músico: si sólo se comprobara el músico, mandando
# otro show_id se editaría el de un tercero.
ajeno = sql("SELECT id FROM shows WHERE artist_id=?", (INDIE_ID,))
if ajeno:
    _, code = patch(f"/me/musicos/{MUS_ID}/shows/{ajeno[0][0]}", {"show_name": "robado"}, PROD)
    ok(code == 404, "no se edita el show de otro pasándolo por la ruta del suyo", str(code))
    ok(sql("SELECT show_name FROM shows WHERE id=?", (ajeno[0][0],))[0][0] != "robado",
       "y el show ajeno sigue con su nombre")
if SHOW_ID:
    _, code = delete(f"/me/musicos/{MUS_ID}/shows/{SHOW_ID}", PROD)
    ok(code == 204, "y puede quitarlo del catálogo", str(code))
    ok(not sql("SELECT id FROM shows WHERE id=?", (SHOW_ID,)), "el show ya no está")


print("\n15. El músico ve la actuación completa, pero SIN importes")
# "Gestionado, visto y cobrado por la productora" (David, 02/09). El precio del
# hotel es el margen de su propia empresa: no es dato nuestro que dar.
comp = sql("SELECT id FROM companies LIMIT 1")[0][0]
ven = sql("SELECT id FROM venues WHERE company_id=? LIMIT 1", (comp,))
ven = ven[0][0] if ven else sql("SELECT id FROM venues LIMIT 1")[0][0]
sql("INSERT INTO bookings (artist_id, company_id, venue_id, starts_at, status, "
    "agreed_price, currency, commission_pct, notified_at, created_at, "
    "invoice_paid, payout_paid) VALUES (?,?,?,?,?,?,?,?,?,?,0,0)",
    (MUS_ID, comp, ven, "2026-12-20 21:00:00", "confirmed", 8000, "MXN", 15,
     "2026-09-02 10:00:00", "2026-09-02 10:00:00"))
BK_ID = sql("SELECT id FROM bookings WHERE artist_id=? ORDER BY id DESC LIMIT 1",
            (MUS_ID,))[0][0]
cuerpo, code = get("/bookings/mine", MUSICO)
mias = [b for b in json.loads(cuerpo)] if code == 200 else []
suya = next((b for b in mias if b["id"] == BK_ID), None)
ok(suya is not None, "el músico ve su actuación", str(code))
if suya:
    ok(suya.get("agreed_price") is None and suya.get("commission_pct") is None,
       "sin precio y sin comisión", f"{suya.get('agreed_price')} / {suya.get('commission_pct')}")
    # Control: tiene que seguir viendo LO QUE SÍ necesita, o "sin importes" se
    # habría conseguido rompiendo el endpoint entero.
    ok(suya.get("starts_at") and suya.get("company_name"),
       "pero sí el día y el hotel, que es para lo que entra",
       f"{suya.get('starts_at')} · {suya.get('company_name')}")
ok(sql("SELECT agreed_price FROM bookings WHERE id=?", (BK_ID,))[0][0] == 8000,
   "y el precio sigue guardado en la base: se esconde, no se borra")
# La empresa SÍ lo ve, porque es la que cobra.
cuerpo, code = get(f"/me/musicos/{MUS_ID}/agenda", PROD)
ag = json.loads(cuerpo) if code == 200 else []
fila_ag = next((a for a in ag if a["id"] == BK_ID), None)
ok(fila_ag is not None and fila_ag.get("agreed_price") == 8000,
   "CONTROL: la productora sí ve el importe de esa misma actuación",
   str(fila_ag.get("agreed_price") if fila_ag else None))
# Y el catálogo con precios de la competencia no es para un proveedor.
_, code = get(f"/bookings/{BK_ID}/replacements", MUSICO)
ok(code == 403, "un proveedor no puede pedir la lista de reemplazos con precios",
   str(code))
sql("DELETE FROM bookings WHERE id=?", (BK_ID,))


print("\n15b. La productora responde por los suyos, y sólo por los suyos")
# David, 03/09: "Eventualmente la productora, pero seria configurable como los
# musicos independientes". Pueden los dos: la empresa lleva lo comercial y el
# músico conserva el botón, porque poder decir "ese día no puedo" ES su
# disponibilidad, que es para lo que se le dio cuenta.
sql("INSERT INTO bookings (artist_id, company_id, venue_id, starts_at, status, "
    "agreed_price, currency, commission_pct, notified_at, created_at, "
    "invoice_paid, payout_paid) VALUES (?,?,?,?,?,?,?,?,?,?,0,0)",
    (MUS_ID, comp, ven, "2026-12-22 21:00:00", "pending", 9000, "MXN", 15,
     "2026-09-03 10:00:00", "2026-09-03 10:00:00"))
PEND = sql("SELECT id FROM bookings WHERE artist_id=? AND status='pending' "
           "ORDER BY id DESC LIMIT 1", (MUS_ID,))[0][0]
# El artista INDEPENDIENTE no es de esta empresa: no debe poder tocarla.
_, code = post(f"/bookings/{PEND}/artist-respond?action=accept", {}, INDIE)
ok(code == 404, "otro proveedor no responde por un músico ajeno (404)", str(code))
ok(sql("SELECT status FROM bookings WHERE id=?", (PEND,))[0][0] == "pending",
   "y la actuación sigue pendiente")
cuerpo, code = post(f"/bookings/{PEND}/artist-respond?action=accept", {}, PROD)
ok(code == 200, "su productora sí la acepta", f"{code} {cuerpo[:120]}")
ok(sql("SELECT status FROM bookings WHERE id=?", (PEND,))[0][0] == "confirmed",
   "y queda confirmada en la base")
# El motivo tiene que decir QUIÉN, pero cancelled_by sigue siendo "artist":
# de ese campo cuelgan el aviso del hotel y el historial de cumplimiento.
sql("INSERT INTO bookings (artist_id, company_id, venue_id, starts_at, status, "
    "agreed_price, currency, commission_pct, notified_at, created_at, "
    "invoice_paid, payout_paid) VALUES (?,?,?,?,?,?,?,?,?,?,0,0)",
    (MUS_ID, comp, ven, "2026-12-29 21:00:00", "pending", 9500, "MXN", 15,
     "2026-09-03 10:00:00", "2026-09-03 10:00:00"))
PEND2 = sql("SELECT id FROM bookings WHERE artist_id=? AND status='pending' "
            "ORDER BY id DESC LIMIT 1", (MUS_ID,))[0][0]
post(f"/bookings/{PEND2}/artist-respond?action=reject", {}, PROD)
fila = sql("SELECT status, cancelled_by, cancellation_reason FROM bookings WHERE id=?",
           (PEND2,))[0]
ok(fila[0] == "cancelled" and fila[1] == "artist"
   and fila[2] == "Rechazada por la productora",
   "al rechazar, el motivo dice que fue la empresa y cancelled_by sigue en artist",
   str(fila))
sql("DELETE FROM bookings WHERE id IN (?,?)", (PEND, PEND2))


print("\n16. Sacarlo del equipo no lo borra")
_, code = delete(f"/me/musicos/{MUS_ID}", PROD)
ok(code == 204, "la productora lo desvincula", str(code))
fila = sql("SELECT parent_id, user_id, is_active FROM artists WHERE id=?", (MUS_ID,))
ok(bool(fila), "la ficha sigue existiendo")
ok(fila[0][0] is None, "ya no cuelga de la productora")
ok(fila[0][1] is not None and fila[0][2] == 1,
   "conserva su cuenta y sigue activo: se le prometió que el perfil es suyo",
   str(fila))
ok(login(mus_mail, CLAVE) is not None, "y puede seguir entrando")
# Ya suelto, el dinero es suyo otra vez.
ok(get("/me/payouts", login(mus_mail, CLAVE))[1] != 403,
   "y recupera su propia facturación al quedar independiente")


print("\nLimpiando lo que sembró la prueba")
ids = [PROD_ID, INDIE_ID, MUS_ID, *EXTRA]
marcas = ",".join("?" * len(ids))
usuarios = [r[0] for r in sql(f"SELECT user_id FROM artists WHERE id IN ({marcas})", ids) if r[0]]
sql(f"DELETE FROM artist_blocked_dates WHERE artist_id IN ({marcas})", ids)
# Los shows también. SQLite reutiliza los id de las fichas borradas, así que un
# show huérfano reaparece colgado de OTRO artista en la siguiente corrida y hace
# perder el rato buscando un fallo que no existe.
sql(f"DELETE FROM shows WHERE artist_id IN ({marcas})", ids)
sql(f"DELETE FROM bookings WHERE artist_id IN ({marcas})", ids)
sql(f"DELETE FROM artists WHERE id IN ({marcas})", ids)
if usuarios:
    m2 = ",".join("?" * len(usuarios))
    sql(f"DELETE FROM password_reset_tokens WHERE user_id IN ({m2})", usuarios)
    sql(f"DELETE FROM users WHERE id IN ({m2})", usuarios)
print(f"  borradas {len(ids)} fichas y {len(usuarios)} cuentas de prueba")


print("\n" + ("TODO BIEN" if not fallos else f"{len(fallos)} FALLO(S):"))
for f in fallos:
    print("  - " + f)
sys.exit(1 if fallos else 0)
