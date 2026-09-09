"""El cuestionario de afinidad de punta a punta: guardar, recomendar y aislar.

David, 07/09: "cada actuación se contrata para un venue distinto. Un hotel de
lujo para el lobby busca un pianista de ambiente, pero para el show necesitan
más energía". Esta prueba comprueba exactamente eso contra un servidor de
verdad: el mismo catálogo, el mismo hotel, dos salas, y dos recomendaciones
distintas.

Lo que vigila, además del camino feliz:

  - AISLAMIENTO. Las respuestas del cuestionario son estrategia comercial: qué
    busca un hotel y cuánto encaja cada proveedor. Un hotel no puede leer las de
    otro, ni sus recomendaciones. Se comprueba con la sesión de un contratante
    de OTRA propiedad, no quitando el token.
  - CONTROL INVERTIDO del aislamiento: el mismo contratante SÍ puede con lo
    suyo. Sin esa mitad, romper el login entero haría pasar la prueba.
  - "SIN CONTESTAR" NO ES "NO ENCAJA". Los shows sin cuestionario salen en una
    lista aparte, no ordenados al final con un cero. Un cero los dejaría
    invisibles para siempre y parecería que el sistema los descartó.
  - Una respuesta inventada se rechaza al GUARDAR. Si entra a la base, ese show
    deja de aparecer recomendado y nadie sabe por qué.

Corre contra una COPIA de la base del repositorio, nunca contra producción:
escribe.

    cp backend/ricky.db /tmp/copia_afinidad.db
    DATABASE_URL="sqlite+aiosqlite:////tmp/copia_afinidad.db" ROOT_PATH="" \
        .venv/bin/python -m uvicorn app.main:app --port 8471 &
    RICKY_DB=/tmp/copia_afinidad.db RICKY_BASE=http://127.0.0.1:8471 \
        .venv/bin/python scripts/pruebas/test_afinidad_api.py
"""
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = os.environ.get("RICKY_BASE", "http://127.0.0.1:8471")
API = BASE + "/api/v1"
DB = os.environ.get("RICKY_DB", "/tmp/copia_afinidad.db")

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


def put(path, cuerpo, token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    return _pide(urllib.request.Request(
        API + path, data=json.dumps(cuerpo).encode(), headers=h, method="PUT"))


def post(path, cuerpo, token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    return _pide(urllib.request.Request(
        API + path, data=json.dumps(cuerpo).encode(), headers=h, method="POST"))


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
        raise SystemExit(f"No pude entrar como {correo}: {code} {cuerpo[:300]}")
    return json.loads(cuerpo)["access_token"]


CLAVE = "Prueba2026!"
sello = uuid.uuid4().hex[:8]
CREADOS = {"users": [], "bookers": []}


def alta_contratante(company_id):
    """Un contratante de una propiedad, creado a mano: no hay endpoint público."""
    correo = f"h{uuid.uuid4().hex[:10]}@prueba.mx"
    rol = sql("SELECT id FROM roles WHERE name='booker'")[0][0]
    sql("INSERT INTO users (email, full_name, hashed_password, is_active, "
        "is_superuser, totp_enabled, role_id, created_at) "
        "VALUES (?,?,?,1,0,0,?,datetime('now'))",
        (correo, f"Contratante {sello}", hash_password(CLAVE), rol))
    uid = sql("SELECT id FROM users WHERE email=?", (correo,))[0][0]
    sql("INSERT INTO bookers (user_id, company_id, position, created_at) "
        "VALUES (?,?,?,datetime('now'))", (uid, company_id, "Gerente"))
    CREADOS["users"].append(uid)
    return login(correo, CLAVE)


# --- Preparación -----------------------------------------------------------
# Se usa la semilla del repositorio: Paraíso Cancún tiene Teatro, Lobby Bar y
# Beach Club, que son justo las tres salas del ejemplo de David.
HOTEL = sql("SELECT id FROM companies WHERE name='Paraíso Cancún'")[0][0]
OTRO = sql("SELECT id FROM companies WHERE id<>? ORDER BY id LIMIT 1", (HOTEL,))[0][0]
SALAS = {n: i for i, n in sql(
    "SELECT id, name FROM venues WHERE company_id=?", (HOTEL,))}
SHOWS = {n: i for i, n in sql("SELECT id, show_name FROM shows")}

print(f"Preparando: hotel {HOTEL}, otro hotel {OTRO}")
print(f"  salas: {SALAS}")
GERENTE = alta_contratante(HOTEL)
AJENO = alta_contratante(OTRO)


print("\n1. El cuestionario lo define el servidor")
cuerpo, code = get("/afinidad/cuestionario", GERENTE)
q = json.loads(cuerpo)
ok(code == 200, "el cuestionario responde 200", str(code))
ok(len(q["preguntas"]) == 10, "vienen las diez preguntas", str(len(q["preguntas"])))
ok(q["preguntas"]["P6"]["multiple"] is True, "la P6 admite varias respuestas")
ok(q["preguntas"]["P1"]["multiple"] is False, "la P1 admite una sola")
ok(sorted(q["moods"]) == ["AMBIENTE", "ESTELAR", "SOCIAL"], "los tres moods",
   str(sorted(q["moods"])))
ok(set(q["propiedad"]) & set(q["salon"]) == {"P2"},
   "sólo la P2 se pregunta en los dos niveles")
ok("Lujo" in q["preguntas"]["P1"]["opciones"], "las opciones vienen del servidor")


print("\n2. La propiedad contesta lo suyo")
PERFIL_HOTEL = {"P1": "Lujo", "P5": "Clasico", "P6": ["Parejas", "High-end"],
                "P7": "Exclusivo", "P9": "Tradicional", "P2": "Elegancia"}
cuerpo, code = put(f"/afinidad/propiedad/{HOTEL}", {"respuestas": PERFIL_HOTEL}, GERENTE)
ok(code == 200, "guarda las respuestas de la propiedad", f"{code} {cuerpo[:120]}")
cuerpo, code = get(f"/afinidad/propiedad/{HOTEL}", GERENTE)
guardado = json.loads(cuerpo)["respuestas"]
ok(guardado.get("P6") == ["Parejas", "High-end"],
   "la multiselección vuelve tal cual se guardó", str(guardado.get("P6")))
ok(guardado.get("P1") == "Lujo", "y la respuesta simple también")

# Lo que no es de este nivel se descarta, no se guarda a escondidas.
cuerpo, code = put(f"/afinidad/propiedad/{HOTEL}",
                   {"respuestas": dict(PERFIL_HOTEL, P3="Show")}, GERENTE)
ok(code == 200, "manda una pregunta de salón a la propiedad y no revienta", str(code))
ok("P3" not in json.loads(cuerpo)["respuestas"],
   "la pregunta que no es de la propiedad no se guarda")


print("\n3. Una respuesta inventada se rechaza AL GUARDAR")
cuerpo, code = put(f"/afinidad/propiedad/{HOTEL}",
                   {"respuestas": {"P1": "Palacete"}}, GERENTE)
ok(code == 422, "una opción que no existe da 422", f"{code} {cuerpo[:120]}")
sigue = json.loads(get(f"/afinidad/propiedad/{HOTEL}", GERENTE)[0])["respuestas"]
ok(sigue.get("P1") == "Lujo", "y no pisó lo que ya estaba guardado", str(sigue.get("P1")))
cuerpo, code = put(f"/afinidad/salon/{SALAS['Teatro']}", {"mood": "FIESTA"}, GERENTE)
ok(code == 422, "un mood inventado da 422", f"{code} {cuerpo[:120]}")


print("\n4. Cada sala elige su mood")
for sala, mood in (("Lobby Bar", "AMBIENTE"), ("Beach Club", "SOCIAL"),
                   ("Teatro", "ESTELAR")):
    cuerpo, code = put(f"/afinidad/salon/{SALAS[sala]}", {"mood": mood}, GERENTE)
    ok(code == 200, f"{sala} queda como {mood}", f"{code} {cuerpo[:100]}")
    efect = json.loads(cuerpo)["efectivas"]
    ok(len(efect) == 5, f"el mood de {sala} rellenó las cinco respuestas",
       str(sorted(efect)))

# El retoque a mano manda sobre el mood.
cuerpo, code = put(f"/afinidad/salon/{SALAS['Lobby Bar']}",
                   {"mood": "AMBIENTE", "respuestas": {"P8": "Media"}}, GERENTE)
efect = json.loads(cuerpo)["efectivas"]
ok(efect.get("P8") == "Media", "el retoque de la sala pisa al mood", str(efect.get("P8")))
ok(efect.get("P3") == "Ambiental", "y lo que no se retoca sigue viniendo del mood")
# Se deja como estaba para el resto de la prueba.
put(f"/afinidad/salon/{SALAS['Lobby Bar']}",
    {"mood": "AMBIENTE", "respuestas": {}}, GERENTE)


print("\n5. Los shows contestan las diez")
FICHAS = {
    "Piano Bar": {"P1": "Lujo", "P2": "Elegancia", "P3": "Ambiental",
                  "P4": "Muy baja", "P5": "Clasico", "P6": ["40-60", "High-end"],
                  "P7": "Elegante", "P8": "Muy baja", "P9": "Tradicional",
                  "P10": "Ambiente"},
    "Cirque Nocturne": {"P1": "Entretenimiento", "P2": "Sorpresa", "P3": "Show",
                        "P4": "Baja", "P5": "Espectacular", "P6": ["Familias"],
                        "P7": "Espectacular", "P8": "Muy alta", "P9": "Referente",
                        "P10": "Recuerdos"},
    "Sunset Sessions": {"P1": "Lifestyle", "P2": "Modernidad", "P3": "Moderado",
                        "P4": "Media", "P5": "Moderno", "P6": ["25-40"],
                        "P7": "Social", "P8": "Media", "P9": "Actualizado",
                        "P10": "Conexion"},
}
ADMIN_MAIL = f"a{uuid.uuid4().hex[:10]}@prueba.mx"
sql("INSERT INTO users (email, full_name, hashed_password, is_active, "
    "is_superuser, totp_enabled, role_id, created_at) "
    "VALUES (?,?,?,1,1,0,?,datetime('now'))",
    (ADMIN_MAIL, f"Admin {sello}", hash_password(CLAVE),
     sql("SELECT id FROM roles WHERE name='admin'")[0][0]))
CREADOS["users"].append(sql("SELECT id FROM users WHERE email=?", (ADMIN_MAIL,))[0][0])
ADMIN = login(ADMIN_MAIL, CLAVE)

for nombre, ficha in FICHAS.items():
    cuerpo, code = put(f"/afinidad/show/{SHOWS[nombre]}", {"respuestas": ficha}, ADMIN)
    ok(code == 200, f"guarda la ficha de {nombre}", f"{code} {cuerpo[:120]}")
    ok(len(json.loads(cuerpo)["respuestas"]) == 10, f"{nombre} con las diez")


print("\n6. LA PRUEBA DE FUEGO: dos salas del mismo hotel, dos recomendaciones")
def recomienda(sala, token=GERENTE):
    cuerpo, code = get(f"/afinidad/recomendaciones/{SALAS[sala]}", token)
    return json.loads(cuerpo) if code == 200 else {"_code": code, "_body": cuerpo}, code

lobby, code_l = recomienda("Lobby Bar")
teatro, code_t = recomienda("Teatro")
ok(code_l == 200 and code_t == 200, "las dos salas responden", f"{code_l}/{code_t}")

top_lobby = lobby["recomendaciones"][0]["show_name"]
top_teatro = teatro["recomendaciones"][0]["show_name"]
ok(top_lobby == "Piano Bar", "en el lobby gana el Piano Bar", top_lobby)
ok(top_teatro == "Cirque Nocturne", "en el teatro gana el Cirque Nocturne", top_teatro)
ok(top_lobby != top_teatro,
   "el mismo hotel recomienda cosas distintas según la sala")

# Y no es que estén empatados: el pianista tiene que HUNDIRSE en el teatro.
piano_lobby = next(r for r in lobby["recomendaciones"] if r["show_name"] == "Piano Bar")
piano_teatro = next(r for r in teatro["recomendaciones"] if r["show_name"] == "Piano Bar")
salto = piano_lobby["scores"]["experience"] - piano_teatro["scores"]["experience"]
ok(salto > 30, "el Piano Bar separa mucho entre las dos salas",
   f"{piano_lobby['scores']['experience']} vs {piano_teatro['scores']['experience']}")

# Los tres scores viajan por separado: es lo que evita que un promedio esconda
# un desencuentro.
ok(sorted(piano_teatro["scores"]) == ["brand", "experience", "guest"],
   "vienen los tres scores por separado", str(sorted(piano_teatro["scores"])))
ok(piano_teatro["scores"]["brand"] > piano_teatro["scores"]["experience"],
   "el pianista sigue encajando de marca aunque no de experiencia",
   f"marca {piano_teatro['scores']['brand']} vs experiencia {piano_teatro['scores']['experience']}")
ok(piano_teatro["motivos"]["contra"],
   "y el motivo dice en qué NO encaja", str(piano_teatro["motivos"]))


print("\n7. Sin contestar NO es lo mismo que no encajar")
nombres_ok = {r["show_name"] for r in lobby["recomendaciones"]}
sin = {r["show_name"] for r in lobby["sin_cuestionario"]}
ok(nombres_ok == set(FICHAS), "sólo se ordenan los que contestaron", str(nombres_ok))
ok("Noche Mexicana" in sin, "el que no contestó sale en la lista aparte")
ok(not (nombres_ok & sin), "ningún show está en las dos listas")
ok(all(r.get("scores") is None for r in lobby["sin_cuestionario"]),
   "los incompletos no traen nota")
todos = len(sql("SELECT s.id FROM shows s JOIN artists a ON a.id=s.artist_id "
                "WHERE s.is_active=1 AND a.is_active=1"))
ok(len(lobby["recomendaciones"]) + len(lobby["sin_cuestionario"]) == todos,
   "no se pierde ningún show por el camino",
   f"{len(lobby['recomendaciones'])}+{len(lobby['sin_cuestionario'])} de {todos}")


print("\n8. Cobertura y avisos")
ok(all(0 < r["cobertura"] <= 1 for r in lobby["recomendaciones"]),
   "toda recomendación dice cuánto de la ficha estaba contestado")
ok(any(r["avisos"] for r in teatro["recomendaciones"]),
   "alguna recomendación del teatro trae aviso de suelo",
   str([(r["show_name"], r["avisos"]) for r in teatro["recomendaciones"]]))


print("\n9. Aislamiento: un hotel no ve lo de otro")
for ruta, que in ((f"/afinidad/propiedad/{HOTEL}", "las respuestas de otra propiedad"),
                  (f"/afinidad/salon/{SALAS['Teatro']}", "el mood de otra sala"),
                  (f"/afinidad/recomendaciones/{SALAS['Teatro']}",
                   "las recomendaciones de otra sala")):
    cuerpo, code = get(ruta, AJENO)
    ok(code == 403, f"un contratante ajeno no puede leer {que}", f"{code}")
cuerpo, code = put(f"/afinidad/propiedad/{HOTEL}",
                   {"respuestas": {"P1": "Business"}}, AJENO)
ok(code == 403, "ni escribirlas", str(code))
sigue = json.loads(get(f"/afinidad/propiedad/{HOTEL}", GERENTE)[0])["respuestas"]
ok(sigue.get("P1") == "Lujo", "y no cambió nada", str(sigue.get("P1")))

# CONTROL INVERTIDO: sin esto, romper el login entero haría pasar la sección.
_, code = get(f"/afinidad/propiedad/{HOTEL}", GERENTE)
ok(code == 200, "CONTROL: el contratante de la casa SÍ puede leer lo suyo", str(code))
_, code = get(f"/afinidad/recomendaciones/{SALAS['Teatro']}", GERENTE)
ok(code == 200, "CONTROL: y sus propias recomendaciones", str(code))
_, code = get(f"/afinidad/recomendaciones/{SALAS['Teatro']}")
ok(code == 401, "CONTROL: sin sesión, 401", str(code))


print("\n10. Un salón sin cuestionario no inventa recomendaciones")
libre = sql("SELECT id FROM venues WHERE company_id=? AND mood IS NULL "
            "AND afinidad IS NULL LIMIT 1", (OTRO,))
if libre:
    cuerpo, code = get(f"/afinidad/recomendaciones/{libre[0][0]}", AJENO)
    ok(code == 409, "sin perfil de sala ni de propiedad responde 409, no una lista",
       f"{code} {cuerpo[:120]}")
else:
    ok(True, "(no había ninguna sala sin perfil que probar)")


print("\n11. El estilo se elige al CREAR la sala, y se valida ahí")
# David, 08/09: el mood va donde ya se crean los venues, sustituyendo al campo
# "Ambiente" de texto libre que hoy guarda PLAYA, playa, cool, Informal y Bar.
cuerpo, code = post(f"/companies/{HOTEL}/venues",
                    {"name": f"Sala estilo {sello}", "capacity": 90, "mood": "social"}, GERENTE)
ok(code == 201, "crea la sala con estilo en minúsculas", f"{code} {cuerpo[:120]}")
nueva_id = json.loads(cuerpo)["id"] if code == 201 else None
if nueva_id:
    CREADOS.setdefault("venues", []).append(nueva_id)
    guardado = sql("SELECT mood FROM venues WHERE id=?", (nueva_id,))[0][0]
    ok(guardado == "SOCIAL", "se guarda normalizado a mayúsculas", str(guardado))
    # Y el estilo tiene que llegar hasta el cálculo, no quedarse en la fila.
    cuerpo, code = get(f"/afinidad/salon/{nueva_id}", GERENTE)
    ok(code == 200 and len(json.loads(cuerpo)["efectivas"]) == 5,
       "el estilo elegido al crear ya rellena las respuestas de la sala",
       f"{code} {cuerpo[:120]}")

cuerpo, code = post(f"/companies/{HOTEL}/venues",
                    {"name": f"Sala mala {sello}", "mood": "FIESTA"}, GERENTE)
ok(code == 422, "un estilo inventado da 422", f"{code} {cuerpo[:120]}")
colada = sql("SELECT COUNT(*) FROM venues WHERE name=?", (f"Sala mala {sello}",))[0][0]
# Lo que importa no es el número, es que no se haya creado la sala a medias.
ok(colada == 0, "y la sala no se crea", f"{colada} filas")

# CONTROL: sin estilo tiene que seguir funcionando. Miles de salas ya existen
# sin él, y obligarlo ahora rompería el alta para todo el mundo.
cuerpo, code = post(f"/companies/{HOTEL}/venues",
                    {"name": f"Sala sin estilo {sello}", "capacity": 40}, GERENTE)
ok(code == 201, "CONTROL: crear una sala SIN estilo sigue funcionando", f"{code} {cuerpo[:120]}")
if code == 201:
    CREADOS.setdefault("venues", []).append(json.loads(cuerpo)["id"])


print("\n12. El match contra la PROPIEDAD no mira ninguna sala")
cuerpo, code = get(f"/afinidad/match/{HOTEL}", GERENTE)
ok(code == 200, "responde 200", str(code))
m = json.loads(cuerpo)
ok(m["listo"] is True, "la propiedad ya contestó, así que hay match")
ok(str(SHOWS["Piano Bar"]) in m["shows"], "el Piano Bar trae match")
uno = m["shows"][str(SHOWS["Piano Bar"])]
ok(sorted(uno) == ["artist_id", "avisos", "brand", "cobertura", "guest", "match"],
   "sólo marca y público, la experiencia es de la sala", str(sorted(uno)))
ok(str(SHOWS["Noche Mexicana"]) not in m["shows"],
   "quien no contestó el cuestionario NO sale con un cero")
# Y tiene que dar distinto que el match contra una sala concreta, o los dos
# números que pidió David serían el mismo número con dos nombres.
teatro_piano = next(r for r in teatro["recomendaciones"] if r["show_name"] == "Piano Bar")
ok(abs(uno["match"] - teatro_piano["media"]) > 5,
   "el match con la propiedad y con la sala son distintos",
   f"propiedad {uno['match']} vs teatro {teatro_piano['media']}")
cuerpo, code = get(f"/afinidad/match/{HOTEL}", AJENO)
ok(code == 403, "y un contratante ajeno no lo puede leer", str(code))


print("\n13. Las diez preguntas se pueden contestar EN EL ALTA del show")
# David, 08/09: mejor dentro del registro que en una pantalla aparte. Así que el
# alta tiene que aceptarlas y validarlas en el mismo golpe.
correo_art = f"a{uuid.uuid4().hex[:10]}@prueba.mx"
cuerpo, code = post("/auth/register/artist", {
    "email": correo_art, "password": CLAVE, "full_name": f"Alta {sello}",
    "stage_name": f"Alta {sello}", "artist_type": "Solista",
    "phone": "9990000000", "base_city": "Cancún"})
ok(code == 201, "se registra un proveedor de prueba", str(code))
ART = json.loads(cuerpo)["access_token"] if code == 201 else None
if ART:
    art_id = json.loads(get("/me/artist", ART)[0])["id"]
    CREADOS.setdefault("artists", []).append(art_id)

    ficha = {"P1": "Lujo", "P2": "Elegancia", "P6": ["Parejas", "High-end"],
             "P3": "Ambiental", "inventada": "x"}
    cuerpo, code = post("/me/artist/shows", {
        "show_name": f"Show alta {sello}", "category": "Musica",
        "subcategory": "Solista", "price_hotel": 5000, "afinidad": ficha}, ART)
    ok(code == 201, "crea el show con sus respuestas de afinidad", f"{code} {cuerpo[:120]}")
    if code == 201:
        sid = json.loads(cuerpo)["id"]
        guardado = sql("SELECT afinidad FROM shows WHERE id=?", (sid,))[0][0]
        guardado = json.loads(guardado) if guardado else {}
        ok(guardado.get("P1") == "Lujo", "la respuesta simple queda guardada")
        ok(guardado.get("P6") == ["Parejas", "High-end"], "y la múltiple también")
        # Una clave que no es pregunta se tira sin ruido: el alta puede mandar
        # de más y no es motivo para rechazar un registro entero.
        ok("inventada" not in guardado, "lo que no es pregunta no se guarda",
           str(sorted(guardado)))

    cuerpo, code = post("/me/artist/shows", {
        "show_name": f"Show malo {sello}", "category": "Musica",
        "subcategory": "Solista", "price_hotel": 5000,
        "afinidad": {"P1": "Palacete"}}, ART)
    ok(code == 422, "una opción inventada da 422 en el alta", f"{code} {cuerpo[:120]}")
    colado = sql("SELECT COUNT(*) FROM shows WHERE show_name=?", (f"Show malo {sello}",))[0][0]
    ok(colado == 0, "y el show no se crea a medias", f"{colado} filas")

    # CONTROL: sin afinidad tiene que seguir funcionando. Todos los shows que ya
    # existen se dieron de alta sin ella.
    cuerpo, code = post("/me/artist/shows", {
        "show_name": f"Show simple {sello}", "category": "Musica",
        "subcategory": "Solista", "price_hotel": 5000}, ART)
    ok(code == 201, "CONTROL: dar de alta un show SIN afinidad sigue funcionando",
       f"{code} {cuerpo[:120]}")


# --- Limpieza --------------------------------------------------------------
# Sólo lo que creó ESTA prueba, por id. Nunca "la fila más nueva que coincida":
# eso se come datos del cliente el día que la prueba falle a la mitad.
for aid in CREADOS.get("artists", []):
    sql("DELETE FROM shows WHERE artist_id=?", (aid,))
    sql("DELETE FROM artists WHERE id=?", (aid,))
for vid in CREADOS.get("venues", []):
    sql("DELETE FROM venues WHERE id=?", (vid,))
for uid in CREADOS["users"]:
    sql("DELETE FROM bookers WHERE user_id=?", (uid,))
    sql("DELETE FROM users WHERE id=?", (uid,))

print()
if fallos:
    print(f"FALLOS ({len(fallos)}):")
    for f in fallos:
        print("  -", f)
    sys.exit(1)
print("TODO BIEN")
