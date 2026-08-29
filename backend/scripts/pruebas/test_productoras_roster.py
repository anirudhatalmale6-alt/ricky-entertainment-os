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

Corre contra un SERVIDOR DE VERDAD con una COPIA de la base de producción.

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


print("\n5. El músico tampoco puede ESCRIBIR datos fiscales")
_, code = patch("/me/artist", {"rfc": "AAAA010101AAA", "bank_clabe": "999"}, MUSICO)
tras = sql("SELECT rfc, bank_clabe FROM artists WHERE id=?", (MUS_ID,))[0]
ok(tras[0] == "XAXX010101000" and tras[1] == "032180000118359719",
   "el PATCH a mano no le cambió el RFC ni la CLABE", f"{code} {tras}")
_, code = patch("/me/artist", {"bio": "toco el saxo"}, MUSICO)
ok(code == 200 and sql("SELECT bio FROM artists WHERE id=?", (MUS_ID,))[0][0] == "toco el saxo",
   "CONTROL: lo que NO es fiscal sí lo puede editar", str(code))


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


print("\n10. Sacarlo del equipo no lo borra")
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
ids = [PROD_ID, INDIE_ID, MUS_ID]
marcas = ",".join("?" * len(ids))
usuarios = [r[0] for r in sql(f"SELECT user_id FROM artists WHERE id IN ({marcas})", ids) if r[0]]
sql(f"DELETE FROM artist_blocked_dates WHERE artist_id IN ({marcas})", ids)
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
