"""Prueba del motor de afinidad: matrices, scores, suelo y multiselección.

No necesita servidor ni base de datos: `afinidad.py` es cálculo puro. Se corre
con `python3 backend/scripts/pruebas/test_afinidad.py` desde la raíz del repo.

Lo que de verdad vigila esto no es la fórmula, que es corta, sino LAS MATRICES.
Son 640 números copiados a mano de las capturas que mandó David, y un dedazo en
uno de ellos no rompe nada: sigue calculando, sigue dando una nota con buena
pinta y recomienda mal para siempre. Por eso las comprobaciones estructurales
—simetría, diagonal, monotonía— valen más que cualquier caso de ejemplo: un
número mal tecleado casi siempre rompe alguna de las tres.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.afinidad import (  # noqa: E402
    MOODS, MULTIPLES, PREGUNTAS, PREGUNTAS_PROPIEDAD, PREGUNTAS_SALON,
    RespuestaInvalida, SCORES, SUELO, cruzar, motivos, perfil_hotel,
    perfil_salon, puntuar, puntuar_score,
)

FALLOS: list[str] = []
N = 0


def ok(condicion, mensaje):
    global N
    N += 1
    if not condicion:
        FALLOS.append(mensaje)


def igual(a, b, mensaje):
    ok(a == b, f"{mensaje}: esperaba {b!r}, salió {a!r}")


# --- 1. Estructura de las diez matrices ------------------------------------
NOMINALES = ["P1", "P2", "P5", "P6", "P7", "P10"]
ORDINALES = ["P3", "P4", "P8", "P9"]

igual(sorted(PREGUNTAS), sorted(NOMINALES + ORDINALES), "las diez preguntas")

for clave, (nombre, opciones, matriz) in PREGUNTAS.items():
    n = len(opciones)
    ok(len(set(opciones)) == n, f"{clave}: opciones repetidas")
    ok(len(matriz) == n and all(len(f) == n for f in matriz),
       f"{clave}: la matriz no es {n}x{n}")
    for i in range(n):
        igual(matriz[i][i], 100, f"{clave}: la diagonal de {opciones[i]}")
    for i in range(n):
        for j in range(n):
            ok(0 <= matriz[i][j] <= 100,
               f"{clave}: {opciones[i]}/{opciones[j]} = {matriz[i][j]} fuera de 0-100")

# Las nominales son simétricas: la afinidad entre dos conceptos no depende de
# quién la mire. Aquí es donde cae un dedazo al copiar.
for clave in NOMINALES:
    _, opciones, matriz = PREGUNTAS[clave]
    for i in range(len(opciones)):
        for j in range(i + 1, len(opciones)):
            igual(matriz[i][j], matriz[j][i],
                  f"{clave}: {opciones[i]}/{opciones[j]} no es simétrica")

# Las ordinales NO son simétricas a propósito, pero sí monótonas: alejarse de la
# diagonal nunca puede subir la nota. Si sube, hay un número mal puesto.
for clave in ORDINALES:
    _, opciones, matriz = PREGUNTAS[clave]
    n = len(opciones)
    for i in range(n):
        for j in range(i + 1, n - 1):
            ok(matriz[i][j + 1] <= matriz[i][j],
               f"{clave}: fila {opciones[i]} sube de {opciones[j]} a {opciones[j+1]}")
        for j in range(i - 1, 0, -1):
            ok(matriz[i][j - 1] <= matriz[i][j],
               f"{clave}: fila {opciones[i]} sube de {opciones[j]} a {opciones[j-1]}")

# Y al menos una de las cuatro tiene que ser asimétrica de verdad, o alguien
# "arregló" las direccionales y se perdió la regla de excederse.
ok(any(PREGUNTAS[c][2][i][j] != PREGUNTAS[c][2][j][i]
       for c in ORDINALES
       for i in range(len(PREGUNTAS[c][1]))
       for j in range(len(PREGUNTAS[c][1]))),
   "ninguna ordinal es direccional: se perdió la asimetría")

# --- 2. Los scores ---------------------------------------------------------
for nombre, pesos in SCORES.items():
    igual(sum(pesos.values()), 100, f"score {nombre}: los pesos no suman 100")
    for pregunta in pesos:
        ok(pregunta in PREGUNTAS, f"score {nombre}: {pregunta} no existe")

usadas = {p for pesos in SCORES.values() for p in pesos}
# El TALENT sale de historial, así que las diez del cuestionario tienen que
# repartirse entre los otros tres. Una pregunta que no entra en ninguno es una
# pregunta que se le hace al hotel para nada.
igual(sorted(usadas), sorted(PREGUNTAS), "hay preguntas que no entran en ningún score")

igual(sorted(set(PREGUNTAS_PROPIEDAD + PREGUNTAS_SALON)), sorted(PREGUNTAS),
      "el reparto propiedad/salón no cubre las diez")
igual(sorted(set(PREGUNTAS_PROPIEDAD) & set(PREGUNTAS_SALON)), ["P2"],
      "sólo la P2 debería preguntarse en los dos niveles")

# --- 3. Valores concretos (regresión de la transcripción) ------------------
# Los que le enseñé a David por escrito el 07/09. Si alguno cambia, cambió una
# matriz.
igual(cruzar("P1", "Familiar", "Adults Only"), 35, "P1 Familiar/Adults")
igual(cruzar("P10", "Ambiente", "Sorprender"), 20, "P10 Ambiente/Sorprender")
igual(cruzar("P3", "Ambiental", "Show"), 0, "P3 Ambiental/Show")
igual(cruzar("P8", "Muy baja", "Muy alta"), 0, "P8 Muy baja/Muy alta")
igual(cruzar("P4", "Muy baja", "Inmersiva"), 0, "P4 Muy baja/Inmersiva")
# La P9 premia pasarse de innovador y castiga quedarse corto: es al revés que
# las otras direccionales y es a propósito (David, 07/09).
ok(cruzar("P9", "Tradicional", "Actualizado") > cruzar("P9", "Actualizado", "Tradicional"),
   "P9: debería premiar al que se pasa de innovador")
ok(cruzar("P3", "Ambiental", "Show") < cruzar("P3", "Show", "Ambiental"),
   "P3: excederse debería puntuar peor que quedarse corto")

# --- 4. Multiselección: promedio, no mejor cruce ---------------------------
igual(MULTIPLES, {"P6"}, "hoy sólo la P6 admite varias respuestas")

# Hotel de Familias+Parejas frente a show de Corporativo+Grupos. Los cuatro
# cruces son 45, 80, 65 y 70 -> promedio 65. Con "mejor cruce" saldría 80 y el
# 45 de Familias/Corporativo, que es un desencuentro real, desaparecería.
valor = cruzar("P6", ["Familias", "Parejas"], ["Corporativo", "Grupos"])
igual(valor, 65.0, "P6 multiselección por promedio")
_, ops6, m6 = PREGUNTAS["P6"]
peor = max(m6[ops6.index(h)][ops6.index(a)]
           for h in ("Familias", "Parejas") for a in ("Corporativo", "Grupos"))
igual(peor, 80, "CONTROL: el mejor cruce daría 80")
ok(valor < peor, "CONTROL: el promedio tiene que ser MENOR que el mejor cruce")

# Y una sola respuesta por lado tiene que seguir dando la casilla exacta.
igual(cruzar("P6", "Familias", "Corporativo"), 45, "P6 con una sola respuesta")

# Pedir varias donde no se puede tiene que reventar, no promediar en silencio.
try:
    cruzar("P1", ["Lujo", "Familiar"], "Lujo")
    ok(False, "P1 con dos respuestas debería lanzar RespuestaInvalida")
except RespuestaInvalida:
    ok(True, "")
try:
    cruzar("P1", "Palacete", "Lujo")
    ok(False, "una respuesta inventada debería lanzar RespuestaInvalida")
except RespuestaInvalida:
    ok(True, "")
try:
    cruzar("P6", ["Parejas", "Familias", "25-40", "40-60"], "Parejas")
    ok(False, "cuatro selecciones deberían lanzar RespuestaInvalida")
except RespuestaInvalida:
    ok(True, "")

# --- 5. Sin contestar es None, no cero -------------------------------------
igual(cruzar("P1", None, "Lujo"), None, "sin respuesta del hotel")
igual(cruzar("P1", "Lujo", None), None, "sin respuesta del show")
igual(cruzar("P6", [], "Parejas"), None, "lista vacía")

vacio = puntuar_score("brand", {}, {})
igual(vacio["score"], None, "score sin nada contestado")
igual(vacio["cobertura"], 0.0, "cobertura sin nada contestado")

# Media ficha: la nota sale, pero la cobertura tiene que delatarlo.
medio = puntuar_score("brand", {"P1": "Lujo"}, {"P1": "Lujo"})
igual(medio["score"], 100.0, "un solo cruce perfecto")
igual(medio["cobertura"], 0.3, "cobertura con sólo la P1 contestada")
ok(medio["cobertura"] < 1.0, "una ficha a medias no puede parecer completa")

# --- 6. La regla de suelo --------------------------------------------------
# El caso que le enseñé a David: mago infantil en un resort de fiesta. El 35 de
# protagonismo se diluye hasta dejar el EXPERIENCE en 70, así que el aviso es lo
# único que lo saca a la luz.
salon_fiesta = {"P3": "Show", "P4": "Alta", "P8": "Muy alta", "P10": "Atractivo",
                "P2": "Diversion"}
mago = {"P3": "Moderado", "P4": "Inmersiva", "P8": "Media", "P10": "Entretener",
        "P2": "Sorpresa"}
exp = puntuar_score("experience", salon_fiesta, mago)
ok(exp["score"] > 60, f"el EXPERIENCE del mago no debería hundirse solo: {exp['score']}")
ok("P3" in exp["avisos"],
   f"el 35 de protagonismo tiene que avisar; avisos={exp['avisos']}")
ok(exp["detalle"]["P3"] < SUELO, "el protagonismo del mago está bajo el suelo")

# Un par sin desencuentros no puede llevar avisos.
limpio = puntuar_score("experience", salon_fiesta, salon_fiesta)
igual(limpio["score"], 100.0, "un show idéntico a lo que pide la sala")
igual(limpio["avisos"], [], "un encaje perfecto no lleva avisos")

# --- 7. El motivo se enseña por los dos lados ------------------------------
m = motivos(puntuar(salon_fiesta, mago))
ok(m["favor"], "tiene que decir en qué coincide")
ok(m["contra"], "y tiene que decir en qué NO, o el motivo engaña")
ok(any("protagonismo" in t for t in m["contra"]),
   f"el protagonismo tiene que salir en contra: {m['contra']}")

# --- 8. Moods y reparto propiedad/salón ------------------------------------
for mood, respuestas in MOODS.items():
    igual(sorted(respuestas), sorted(PREGUNTAS_SALON),
          f"el mood {mood} no cubre exactamente las preguntas del salón")
    for pregunta, valor in respuestas.items():
        ok(valor in PREGUNTAS[pregunta][1],
           f"mood {mood}: {valor!r} no es una opción de {pregunta}")

# El mismo show tiene que puntuar MUY distinto según el mood de la sala, que es
# justo lo que pidió David: en el lobby el piano, en el teatro el circo.
piano = {"P3": "Ambiental", "P4": "Muy baja", "P8": "Muy baja", "P10": "Ambiente",
         "P2": "Elegancia"}
en_ambiente = puntuar_score("experience", perfil_salon("AMBIENTE"), piano)["score"]
en_estelar = puntuar_score("experience", perfil_salon("ESTELAR"), piano)["score"]
ok(en_ambiente > en_estelar + 25,
   f"el piano debería separar mucho entre salas: {en_ambiente} vs {en_estelar}")

# Lo propio del salón manda sobre lo que trae el mood.
retocado = perfil_salon("AMBIENTE", {"P8": "Alta"})
igual(retocado["P8"], "Alta", "la respuesta propia del salón debe pisar al mood")
igual(retocado["P3"], "Ambiental", "lo que no se retoca se queda del mood")
igual(perfil_salon(None), {}, "sin mood y sin respuestas propias, nada")

# Y la sala manda sobre la propiedad donde las dos contestan (la P2).
mezcla = perfil_hotel({"P1": "Lujo", "P2": "Elegancia"}, {"P2": "Sorpresa", "P3": "Show"})
igual(mezcla["P1"], "Lujo", "lo de la propiedad se conserva")
igual(mezcla["P2"], "Sorpresa", "la P2 del salón manda sobre la de la propiedad")
igual(mezcla["P3"], "Show", "lo del salón entra")

# --- 9. Los tres scores salen juntos ---------------------------------------
completo = puntuar({"P1": "Lujo", "P2": "Elegancia", "P5": "Clasico",
                    "P6": "High-end", "P7": "Exclusivo", "P9": "Tradicional",
                    "P3": "Ambiental", "P4": "Muy baja", "P8": "Baja",
                    "P10": "Ambiente"},
                   {"P1": "Lujo", "P2": "Elegancia", "P5": "Clasico",
                    "P6": "High-end", "P7": "Exclusivo", "P9": "Tradicional",
                    "P3": "Ambiental", "P4": "Muy baja", "P8": "Baja",
                    "P10": "Ambiente"})
igual(sorted(completo), ["brand", "experience", "guest"], "los tres scores")
for nombre, datos in completo.items():
    igual(datos["score"], 100.0, f"{nombre} con dos fichas idénticas")
    igual(datos["cobertura"], 1.0, f"{nombre} con la ficha completa")

if FALLOS:
    print(f"FALLOS ({len(FALLOS)} de {N} comprobaciones):")
    for f in FALLOS:
        print("  -", f)
    sys.exit(1)
print(f"TODO BIEN, {N} comprobaciones")
