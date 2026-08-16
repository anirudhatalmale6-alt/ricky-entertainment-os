"""GET /shows no puede reventar cuando no hay hotel de origen.

David, 16/08: "me esta dando error 500 en /Presupuesto/". La pantalla de
Presupuesto pide el catálogo de shows, y el catálogo calculaba la distancia al
hotel que consulta SÓLO si había un hotel de origen. Un director de cadena y el
administrador no cuelgan de una propiedad, así que la distancia nunca se
asignaba... y dos líneas más abajo el código la leía: AttributeError y 500 en
toda la pantalla. Un dato que no se puede calcular vale None, no es un atributo
que no existe.

Correr con la base de `seed_audiencia.py` levantada:
    DATABASE_URL="sqlite+aiosqlite:///<ruta>/aud_test.db" \
        .venv/bin/python -m uvicorn app.main:app --port 8442
    python scripts/pruebas/test_shows_sin_origen.py
"""
import json
import urllib.error
import urllib.request

API = "http://localhost:8442/api/v1"
fallos = []


def ok(cond, msg, extra=""):
    print(("  OK   " if cond else "  FALLA") + " " + msg + (f"  [{extra}]" if extra else ""))
    if not cond:
        fallos.append(msg)


def login(email, pw):
    r = urllib.request.urlopen(urllib.request.Request(
        API + "/auth/login", data=json.dumps({"email": email, "password": pw}).encode(),
        headers={"Content-Type": "application/json"}))
    return json.load(r)["access_token"]


def get(token, path):
    req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + token})
    try:
        return json.load(urllib.request.urlopen(req)), 200
    except urllib.error.HTTPError as e:
        return e.read().decode()[:200], e.code


def patch(token, path, cuerpo):
    req = urllib.request.Request(
        API + path, data=json.dumps(cuerpo).encode(), method="PATCH",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req)), 200
    except urllib.error.HTTPError as e:
        return e.read().decode()[:200], e.code


CUENTAS = [
    ("admin@showma.mx", "admin1234", "el administrador (no cuelga de ninguna propiedad)"),
    ("director@paraiso.mx", "x1234567", "el director de cadena (tampoco)"),
    ("gerente@cancun.mx", "x1234567", "el gerente de hotel (este sí tiene origen)"),
]

print("1. El catálogo responde para todos los perfiles")
for email, pw, quien in CUENTAS:
    t = login(email, pw)
    d, code = get(t, "/shows")
    ok(code == 200, f"{quien}: /shows responde 200", f"{code} {d if code != 200 else ''}")
    if code == 200 and isinstance(d, list):
        ok(True, f"{quien}: llega la lista", f"{len(d)} shows")
        faltan = [s for s in d if "distance_km" not in s]
        ok(not faltan, f"{quien}: todos los shows traen distance_km (aunque sea None)",
           f"{len(faltan)} sin el campo")

print("2. Sin origen la distancia es None, no un error")
t = login("admin@showma.mx", "admin1234")
d, code = get(t, "/shows")
# Si el punto 1 falló, aquí llega el texto del error y no una lista: se reporta
# la falla en vez de reventar la prueba entera.
ok(isinstance(d, list) and all(s["distance_km"] is None for s in d),
   "para el administrador todas las distancias vienen vacías",
   str([s["distance_km"] for s in d][:5]) if isinstance(d, list) else f"{code} {d}")

print("3. El filtro por radio tampoco revienta sin origen")
d, code = get(t, "/shows?max_km=200")
ok(code == 200, "/shows?max_km=200 responde 200", str(code))
ok(d == [], "sin ciudad de origen no se puede demostrar el radio: lista vacía, no error",
   str(len(d) if isinstance(d, list) else d))

print("4. Con origen la distancia sí se calcula")
# La base de pruebas no trae geografía, así que se la ponemos: sin ciudades no
# hay nada que medir y el punto 4 pasaría en falso.
ta = login("admin@showma.mx", "admin1234")
patch(ta, "/companies/1", {"city": "Cancún", "region": "Quintana Roo"})
patch(ta, "/artists/1", {"city": "Mérida", "region": "Yucatán"})
t = login("gerente@cancun.mx", "x1234567")
d, _ = get(t, "/shows")
con = [s for s in d if s["distance_km"] is not None]
ok(bool(con), "al menos un show tiene distancia medida desde el hotel",
   f"{len(con)} de {len(d)}")
ok(all(s["distance_km"] > 0 for s in con), "y es un número positivo de km",
   str([s["distance_km"] for s in con][:3]))

print()
print("TODO BIEN" if not fallos else f"{len(fallos)} FALLAS: " + "; ".join(fallos))
