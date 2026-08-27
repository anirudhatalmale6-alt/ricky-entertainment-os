"""La tarjeta pública enseña el show y NADA MÁS.

David, 27/08: "convertir/usar el perfil de los músicos/shows como una especie
de tarjeta de presentación que se vea externa a la plataforma".

Una pantalla pública es una superficie de seguridad: se abre sin cuenta, la
puede leer cualquiera y la indexa Google. El perfil del artista lleva dentro
RFC, CLABE, cuenta bancaria, razón social, fecha de nacimiento, teléfono y
correo — y las siete tarifas del show. Nada de eso puede salir, y no basta con
"no lo pinté en el HTML": lo que importa es lo que manda el SERVIDOR, porque el
JSON se lee entero desde el navegador aunque la página no lo enseñe.

Esta prueba corre contra un SERVIDOR DE VERDAD con una COPIA de la base de
producción, no con datos inventados: los perfiles reales traen campos llenos
que un fixture limpio no tendría, y son justo los que se pueden escapar.

Correr:
    DATABASE_URL="sqlite+aiosqlite:///<copia>.db" \
        .venv/bin/python -m uvicorn app.main:app --port 8451
    python scripts/pruebas/test_tarjeta_publica.py
"""
import json
import urllib.error
import urllib.request

BASE = "http://localhost:8451"
API = BASE + "/api/v1"
ADMIN = ("admin@ricky.os", "Prueba2026!")   # copia local, nunca la de producción
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
    return _pide(urllib.request.Request(BASE + path, headers=h))


def post(path, cuerpo, token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    return _pide(urllib.request.Request(
        API + path, data=json.dumps(cuerpo).encode(), headers=h, method="POST"))


tok = json.loads(post("/auth/login", {"email": ADMIN[0], "password": ADMIN[1]})[0])["access_token"]

print("1. Apagada por omisión: publicar la función no publica a nadie")
cuerpo, code = get("/api/v1/public/artist/dj-nova")
ok(code == 404, "un proveedor que nadie publicó da 404", str(code))
cuerpo, code = get("/p/dj-nova")
ok(code == 404, "y su página también", str(code))
cuerpo, code = get("/p/este-slug-no-existe")
ok(code == 404, "un slug inventado da 404 (control)", str(code))

print("2. Se publica a propósito y queda una liga estable")
r1 = json.loads(post("/artists/13/tarjeta", {"publicar": True}, tok)[0])
ok(r1["is_public"] is True, "queda publicada")
ok(r1["public_slug"] == "los-marismenos",
   "el slug sale del nombre, sin acentos ni mayúsculas", r1["public_slug"])
ok(r1["url"].endswith("/p/los-marismenos"), "y el servidor arma la liga completa", r1["url"])
r2 = json.loads(post("/artists/13/tarjeta", {"publicar": False}, tok)[0])
ok(r2["public_slug"] == r1["public_slug"],
   "al apagarla el slug NO se borra: la liga que ya circula no se rompe")
cuerpo, code = get("/api/v1/public/artist/los-marismenos")
ok(code == 404, "pero apagada deja de verse", str(code))
json.loads(post("/artists/13/tarjeta", {"publicar": True}, tok)[0])

print("3. Nadie más puede publicar perfiles")
cuerpo, code = post("/artists/4/tarjeta", {"publicar": True})
ok(code in (401, 403), "sin sesión no se puede publicar a nadie", str(code))

print("4. LO QUE NO PUEDE SALIR (lo que manda el servidor, no lo que pinta la página)")
crudo, code = get("/api/v1/public/artist/los-marismenos")
ok(code == 200, "la tarjeta publicada responde 200", str(code))
d = json.loads(crudo)
bajo = crudo.lower()
# Nombres de campo que no pueden aparecer NUNCA en esta salida.
PROHIBIDOS = [
    "rfc", "clabe", "bank", "cuenta", "legal_name", "razon", "regimen", "tax",
    "csd", "cfdi", "birth", "nacimiento", "phone", "telefono", "email", "correo",
    "postal", "payout", "commission", "comision", "user_id", "price", "precio",
    "tarifa", "base_price", "surcharge", "travel_fee", "rating", "is_active",
]
encontrados = [p for p in PROHIBIDOS if p in bajo]
ok(not encontrados, "ningún campo prohibido viaja en el JSON público", str(encontrados))
# Y ahora al revés: el perfil COMPLETO sí los trae. Sin este control la prueba
# de arriba pasaría igual si el proveedor tuviera todos esos campos vacíos.
completo, _ = get("/api/v1/artists/13", tok)
tiene = [p for p in ("rfc", "bank", "price", "email") if p in completo.lower()]
ok(len(tiene) >= 3,
   "control: el perfil de dentro SÍ trae esos campos, o sea que hay algo que filtrar",
   str(tiene))

print("5. Sí sale lo que tiene que salir")
ok(d["nombre"] and d["shows"], "nombre y espectáculos")
ok(all("fotos" in s for s in d["shows"]), "cada show con sus fotos")
ok(d.get("portada"), "y una portada", str(d.get("portada")))

print("6. La liga se ve bien pegada en WhatsApp (Open Graph desde el SERVIDOR)")
html, code = get("/p/los-marismenos")
ok(code == 200, "la página responde 200", str(code))
# El robot de WhatsApp no ejecuta JavaScript: estas etiquetas TIENEN que venir
# ya escritas en el HTML, no puestas por el script al cargar.
for etiqueta in ('property="og:title"', 'property="og:image"', 'property="og:description"',
                 'property="og:url"', 'name="twitter:card"'):
    ok(etiqueta in html, f"trae {etiqueta}")
ok("og:image\" content=\"http" in html.replace("'", '"'),
   "la foto va con dirección completa, no /uploads/… suelto")
ok("window.TARJETA=" in html, "y los datos vienen embebidos: se ve sin esperar a ninguna petición")
# Un precio no puede haberse colado en el HTML por otra vía.
ok("base_price" not in html and "price_hotel" not in html,
   "ni un precio dentro del HTML de la página")

print()
print("TODO BIEN" if not fallos else f"{len(fallos)} FALLAS: " + "; ".join(fallos))
