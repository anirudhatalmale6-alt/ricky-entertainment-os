"""Convocatoria en % del aforo: el salón chico lleno no puede salir 'abajo'."""
import json
import urllib.error
import urllib.request

API = "http://localhost:8432/api/v1"
fallos = []


def ok(cond, msg, extra=""):
    print(("  OK   " if cond else "  FALLA") + " " + msg + (f"  [{extra}]" if extra else ""))
    if not cond:
        fallos.append(msg)


def login(email, pw="x1234567"):
    r = urllib.request.urlopen(urllib.request.Request(
        API + "/auth/login", data=json.dumps({"email": email, "password": pw}).encode(),
        headers={"Content-Type": "application/json"}))
    return json.load(r)["access_token"]


def get(token, path):
    req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + token})
    try:
        return json.load(urllib.request.urlopen(req)), 200
    except urllib.error.HTTPError as e:
        return e.read().decode()[:160], e.code


t = login("gerente@chico.mx")
d, _ = get(t, "/audiencia/desempeno")
fila = {f["nombre"]: f for f in d["filas"]}
c = fila["Cuarteto Íntimo"]

print("1. Lo que ve el hotel chico")
llen_aqui = round((95 + 96 + 94) / 300 * 100, 1)
ok(abs(c["convocatoria_pct"] - llen_aqui) < 0.15, "llenado aquí", f'{c["convocatoria_pct"]} vs {llen_aqui}')
ok(abs(c["convocatoria"] - 95.0) < 0.05, "la gente por noche sigue estando", str(c["convocatoria"]))
ok(c["noches_con_aforo"] == 3, "las 3 noches tienen aforo conocido", str(c["noches_con_aforo"]))

print("\n2. Su promedio afuera (salones de 600 a media entrada)")
fu = c["fuera"]
ok(fu["publicable"] is True, "hay referencia publicable", str(fu["publicable"]))
llen_fuera = round((300 + 310 + 290) / 1800 * 100, 1)
ok(abs(fu["convocatoria_pct"] - llen_fuera) < 0.15, "llenado afuera", f'{fu["convocatoria_pct"]} vs {llen_fuera}')
ok(abs(fu["convocatoria"] - 300.0) < 0.05, "y su gente por noche afuera es MAYOR", str(fu["convocatoria"]))
# Buscar la palabra "aforo" en el JSON no sirve: `noches_con_aforo` la contiene
# y no filtra nada. Lo que hay que fijar es QUÉ campos salen, ni uno más.
permitidos = {"propiedades", "noches", "convocatoria", "convocatoria_pct",
              "noches_con_aforo", "retencion", "publicable"}
ok(set(fu) == permitidos, "de afuera sólo salen esos campos: ni aforo, ni precios, ni nombres",
   str(sorted(set(fu) - permitidos) or "sin extras"))
ok(not any(k in fu for k in ("capacidad", "aforo", "gasto", "costo_persona", "precio", "propiedad_nombre")),
   "ningún campo de aforo, dinero ni identidad de la otra propiedad")

print("\n3. El caso de David: lleno chico vs medio grande")
viejo = round((95.0 - 300.0) / 300.0 * 100, 1)   # lo que decía la versión anterior
ok(viejo < 0, "con gente por noche salía NEGATIVO aunque estuviera lleno", f"{viejo}%")
ok(c["vs_fuera_convocatoria"] > 0, "en puntos de llenado sale POSITIVO",
   str(c["vs_fuera_convocatoria"]))
ok(abs(c["vs_fuera_convocatoria"] - round(llen_aqui - llen_fuera, 1)) < 0.15,
   "y la diferencia son puntos, no un % de %",
   f'{c["vs_fuera_convocatoria"]} vs {round(llen_aqui - llen_fuera, 1)}')
ok(c["marca_fuera"] == "arriba", "el veredicto ya no lo castiga", str(c["marca_fuera"]))

print("\n4. Contra su mismo género en la casa")
otro = fila["Otro del Género"]
ok(abs(otro["convocatoria_pct"] - 50.0) < 0.15, "el otro deja la sala a la mitad",
   str(otro["convocatoria_pct"]))
ok(c["vs_categoria_convocatoria"] > 0, "el que llena queda por encima de su género",
   str(c["vs_categoria_convocatoria"]))
ok(otro["vs_categoria_convocatoria"] < 0, "y el que no llena, por debajo",
   str(otro["vs_categoria_convocatoria"]))
ok(otro["marca_fuera"] is None, "el que no tiene historia afuera no recibe veredicto",
   str(otro["marca_fuera"]))

print("\n5. El detalle noche por noche cuadra")
noches = c["noches_detalle"]
ok(len(noches) == 3, "tres noches", str(len(noches)))
ok(all(n["capacidad"] == 100 for n in noches), "todas en la sala de 100")
ok(abs(noches[0]["atraccion"] - round(noches[0]["gente"] / 100 * 100, 1)) < 0.05,
   "el llenado de la noche cuadra con su aforo",
   f'{noches[0]["atraccion"]} con {noches[0]["gente"]}')

print()
print("TODO BIEN" if not fallos else f"{len(fallos)} FALLAS: {fallos}")
