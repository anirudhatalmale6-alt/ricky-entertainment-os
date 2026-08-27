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

BASE = "http://localhost:8455"
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


def existe(path) -> int:
    """Solo el codigo. `get` decodifica el cuerpo como texto y un JPEG lo
    revienta: aqui no nos importa el contenido, solo si esta."""
    try:
        return urllib.request.urlopen(
            urllib.request.Request(BASE + path, method="HEAD")).status
    except urllib.error.HTTPError as e:
        return e.code


def post(path, cuerpo, token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    return _pide(urllib.request.Request(
        API + path, data=json.dumps(cuerpo).encode(), headers=h, method="POST"))


tok = json.loads(post("/auth/login", {"email": ADMIN[0], "password": ADMIN[1]})[0])["access_token"]

# La prueba deja la base como se la encontró en lo que a tarjetas se refiere:
# apaga las que va a usar ANTES de empezar. Sin esto la segunda corrida falla
# sola —el punto 1 esperaba un 404 y encontraba la tarjeta que publicó la
# corrida anterior— y una prueba que sólo pasa la primera vez no sirve de nada.
for _aid in (4, 5, 7, 13):
    post(f"/artists/{_aid}/tarjeta", {"publicar": False}, tok)

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

print("7. Las cifras que Instagram no puede dar")
# David, 27/08: "instagram es lo que mas estan usando para presentarse, pero no
# da datos... casi como una tarjeta de pokemon". Estas cifras son el motivo de
# que la tarjeta exista, y NINGUNA la escribe el proveedor.
json.loads(post("/artists/7/tarjeta", {"publicar": True}, tok)[0])   # DJ Nova
crudo, code = get("/api/v1/public/artist/dj-nova")
dn = json.loads(crudo)
t = dn.get("trayectoria") or {}
ok(code == 200 and t, "la tarjeta trae su trayectoria", str(code))
ok(t.get("actuaciones", 0) > 0 and t.get("hoteles", 0) > 0,
   "actuaciones y hoteles", f"{t.get('actuaciones')} en {t.get('hoteles')}")
# Que salgan del MISMO servicio que el perfil de dentro, no de una copia: si
# alguna vez divergen, el musico ensena un numero y el hotel ve otro.
dentro = json.loads(get("/api/v1/artists/7/trayectoria", tok)[0])
ok(t.get("actuaciones") == dentro.get("actuaciones")
   and t.get("hoteles") == dentro.get("hoteles"),
   "y coinciden EXACTAMENTE con las del perfil de dentro",
   f"fuera {t.get('actuaciones')}/{t.get('hoteles')} · dentro {dentro.get('actuaciones')}/{dentro.get('hoteles')}")

print("8. Cada porcentaje viaja con su muestra")
for clave, campo in (("cumplimiento", "muestra"), ("publico", "muestra")):
    b = t.get(clave)
    if b:
        ok(b.get(campo) is not None,
           f"{clave} dice sobre cuantas actuaciones esta medido", str(b.get(campo)))
r = t.get("recontratacion")
if r:
    ok(r.get("hoteles_totales") is not None,
       "recontratacion dice de cuantos hoteles", str(r))

print("9. Los comentarios no publican a la persona que los firmo")
res = dn.get("resenas") or []
ok(res, "llegan las resenas", str(len(res)))
if res:
    ok(res[0].get("hotel"), "con el nombre del hotel", str(res[0].get("hotel")))
    ok("cargo" in res[0], "y el cargo de quien firma", str(res[0].get("cargo")))
# El nombre propio de quien escribio NO puede salir. Control: se lee del
# perfil de dentro, donde si esta, y se busca en la salida publica.
adentro = json.loads(get("/api/v1/reviews/artists/7", tok)[0])
firmantes = [i.get("author_name") for i in adentro.get("items", []) if i.get("author_name")]
ok(bool(firmantes), "control: adentro SI se guarda quien firmo", str(firmantes[:2]))
fugados = [f for f in firmantes if f and f.lower() in crudo.lower()]
ok(not fugados, "y ninguno de esos nombres sale en la tarjeta publica", str(fugados))

print("10. La vista previa arranca con las cifras")
html7, _ = get("/p/dj-nova")
import re as _re
m = _re.search(r'property="og:description" content="([^"]*)"', html7)
ok(bool(m), "hay og:description")
if m:
    ok(_re.match(r"^\d+ actuaciones", m.group(1)),
       "y empieza por los numeros, no por la biografia", m.group(1)[:70])
    ok("(1 reseñas)" not in m.group(1),
       "y con el plural bien puesto: '1 reseña', no '1 reseñas'", m.group(1)[:70])

print("11. Ninguna imagen rota")
# En la tarjeta publica una foto rota es la primera impresion de un hotel, y
# la que se pega en WhatsApp. La base puede guardar rutas huerfanas: ya paso
# en este proyecto con un prefijo /ricky/ de un despliegue viejo. El servidor
# comprueba que el archivo exista antes de publicarlo.
urls = set()
for dd in (d, dn):
    if dd.get("portada"):
        urls.add(dd["portada"])
    urls.update(dd.get("galeria") or [])
    for sh in dd.get("shows") or []:
        urls.update(sh.get("fotos") or [])
    for h in (dd.get("trayectoria") or {}).get("hoteles_detalle") or []:
        if h.get("logo_url"):
            urls.add(h["logo_url"])
    for rr in dd.get("resenas") or []:
        if rr.get("logo"):
            urls.add(rr["logo"])
rotas = [u for u in urls if u.startswith("/uploads/") and existe(u) != 200]
ok(not rotas, f"las {len(urls)} imagenes publicadas existen todas", str(rotas[:3]))
# Control: si el filtro no hiciera nada, esta ruta inventada se colaria.
ok(existe("/uploads/no-existe-esta-foto.jpg") == 404,
   "control: una ruta inventada sí da 404, o sea que la comprobacion vale")

print()
print("TODO BIEN" if not fallos else f"{len(fallos)} FALLAS: " + "; ".join(fallos))
