"""Afinidad hotel–show: las diez preguntas de David y los cuatro scores.

David, 2026-09-07: dos cuestionarios de diez preguntas, uno para el hotel y otro
para el artista. Preguntas distintas, MISMO juego de respuestas, para poder
cruzarlas. "Como Match.com". Lo que aquí se calcula no sale de la historia sino
de lo que las dos partes CONTESTARON, y ésa es la gracia: funciona el primer día
con un hotel que no ha contratado nunca. La analítica por historial (aforo,
reseñas, recontratación) sigue viviendo en trayectoria.py y distinciones.py.

Dos tipos de pregunta, y se puntúan distinto:

- NOMINALES (P1, P2, P5, P6, P7, P10). No tienen un "más" ni un "menos":
  "Cultural" no está por encima de "Familiar", es otra cosa. Hace falta decir a
  mano cuánto se complementa cada respuesta con cada otra. Esas seis matrices
  son SIMÉTRICAS: la afinidad entre dos conceptos no depende de quién la mire.

- ORDINALES (P3, P4, P8, P9). Son escalas, y sus matrices son DIRECCIONALES a
  propósito: "excederse es generalmente más problemático que quedarse
  ligeramente corto" (David). Un show más intenso de lo que la sala aguanta
  estropea la noche; uno más suave sólo decepciona. La P9 va al revés adrede:
  sorprender a un hotel tradicional es un regalo, aburrir a uno que quiere ser
  referente es un fallo.

En las matrices, la FILA es la respuesta del HOTEL y la COLUMNA la del SHOW.
No se pueden trasponer sin cambiar el significado en las cuatro direccionales.

Tres decisiones que costaron medirlas y conviene no deshacer sin volver a
medir:

1. MULTISELECCIÓN POR PROMEDIO, NO POR EL MEJOR CRUCE. Hotel y show marcan
   hasta tres respuestas en la P6. Puntuar con el mejor cruce de los que haya
   sube la media de esa pregunta a 96 sobre 100 y deja al 95% de los
   emparejamientos por encima de 85: todos encajan con todos y el score deja de
   servir. Con el promedio de todos los cruces la media queda en 77 y sigue
   separando. Y el caso concreto: un hotel de Familias+Parejas frente a un show
   de Corporativo+Grupos da 80 por el mejor cruce y 65 por el promedio, o sea
   que el 45 que David puso en Familias/Corporativo desaparece entero con la
   primera regla.

2. REGLA DE SUELO POR SCORE. Un promedio ponderado se traga los noes: un show
   con 0 en protagonismo y 85 en todo lo demás termina con 76.5 y parece un
   candidato normal. Partir en cuatro scores mejora mucho eso —el desencuentro
   sale en la columna que le toca en vez de diluirse en una nota única— pero no
   lo cura: dentro del EXPERIENCE, un 35 en protagonismo todavía deja el score
   en 70. Por eso cada score devuelve además sus avisos, y la pantalla tiene que
   decirlos en voz alta.

3. EL MOTIVO SE ENSEÑA POR LOS DOS LADOS. Si sólo se enseña en qué coincide, un
   candidato malo luce "protagonismo 100" mientras el concepto va en 35. Ver
   `motivos()`.

El TALENT SCORE no está aquí: sale de reseñas, recontratación, puntualidad,
aforo y retención, o sea de historial, y hoy sólo 3 de 22 artistas tienen alguna
reseña. Vive con lo demás que se calcula por historia.
"""
from __future__ import annotations

# --- Las seis matrices NOMINALES (simétricas) ------------------------------
# Valores de David, 2026-09-07. Fila = HOTEL, columna = SHOW.

P1_OPCIONES = ["Lujo", "Lifestyle", "Familiar", "Adults Only", "Cultural",
               "Entretenimiento", "Wellness", "Business"]
P1_MATRIZ = [
    [100, 85, 65, 90, 75, 70, 85, 70],
    [85, 100, 65, 90, 80, 90, 75, 65],
    [65, 65, 100, 35, 80, 90, 60, 55],
    [90, 90, 35, 100, 70, 80, 80, 60],
    [75, 80, 80, 70, 100, 85, 70, 65],
    [70, 90, 90, 80, 85, 100, 50, 60],
    [85, 75, 60, 80, 70, 50, 100, 60],
    [70, 65, 55, 60, 65, 60, 60, 100],
]

P2_OPCIONES = ["Elegancia", "Diversion", "Relajacion", "Sorpresa",
               "Autenticidad", "Romance", "Modernidad", "Familiaridad"]
P2_MATRIZ = [
    [100, 45, 75, 65, 70, 90, 85, 55],
    [45, 100, 45, 90, 70, 60, 85, 90],
    [75, 45, 100, 30, 75, 85, 65, 75],
    [65, 90, 30, 100, 75, 60, 90, 70],
    [70, 70, 75, 75, 100, 70, 65, 80],
    [90, 60, 85, 60, 70, 100, 75, 60],
    [85, 85, 65, 90, 65, 75, 100, 65],
    [55, 90, 75, 70, 80, 60, 65, 100],
]

P5_OPCIONES = ["Clasico", "Minimalista", "Moderno", "Tropical", "Bohemio",
               "Cultural", "Espectacular", "Divertido"]
P5_MATRIZ = [
    [100, 85, 70, 55, 65, 80, 70, 45],
    [85, 100, 95, 60, 75, 65, 70, 45],
    [70, 95, 100, 70, 80, 70, 90, 75],
    [55, 60, 70, 100, 90, 85, 75, 90],
    [65, 75, 80, 90, 100, 90, 65, 80],
    [80, 65, 70, 85, 90, 100, 80, 75],
    [70, 70, 90, 75, 65, 80, 100, 90],
    [45, 45, 75, 90, 80, 75, 90, 100],
]

P6_OPCIONES = ["Parejas", "Familias", "25-40", "40-60", "Senior", "Grupos",
               "Corporativo", "High-end"]
P6_MATRIZ = [
    [100, 65, 90, 90, 75, 70, 65, 90],
    [65, 100, 65, 75, 70, 80, 45, 65],
    [90, 65, 100, 65, 35, 90, 75, 80],
    [90, 75, 65, 100, 80, 75, 85, 95],
    [75, 70, 35, 80, 100, 60, 65, 80],
    [70, 80, 90, 75, 60, 100, 90, 70],
    [65, 45, 75, 85, 65, 90, 100, 85],
    [90, 65, 80, 95, 80, 70, 85, 100],
]

P7_OPCIONES = ["Exclusivo", "Elegante", "Casual", "Social", "Energetico",
               "Sorprendente", "Espectacular", "Divertido"]
P7_MATRIZ = [
    [100, 95, 50, 60, 65, 80, 85, 50],
    [95, 100, 60, 65, 60, 75, 80, 50],
    [50, 60, 100, 90, 80, 70, 60, 90],
    [60, 65, 90, 100, 90, 80, 75, 95],
    [65, 60, 80, 90, 100, 90, 90, 95],
    [80, 75, 70, 80, 90, 100, 95, 90],
    [85, 80, 60, 75, 90, 95, 100, 85],
    [50, 50, 90, 95, 95, 90, 85, 100],
]

P10_OPCIONES = ["Ambiente", "Conexion", "Entretener", "Sorprender", "Recuerdos",
                "Activar", "Atractivo", "Marca"]
P10_MATRIZ = [
    [100, 60, 45, 20, 40, 70, 20, 75],
    [60, 100, 80, 60, 80, 90, 50, 55],
    [45, 80, 100, 85, 85, 75, 85, 50],
    [20, 60, 85, 100, 95, 65, 90, 70],
    [40, 80, 85, 95, 100, 70, 90, 75],
    [70, 90, 75, 65, 70, 100, 65, 50],
    [20, 50, 85, 90, 90, 65, 100, 80],
    [75, 55, 50, 70, 75, 50, 80, 100],
]

# --- Las cuatro matrices ORDINALES (direccionales) --------------------------
# Fila = HOTEL, columna = SHOW. NO son simétricas y no deben "arreglarse".

P3_OPCIONES = ["Ambiental", "Moderado", "Protagonista", "Show"]
P3_MATRIZ = [
    [100, 80, 30, 0],
    [75, 100, 80, 35],
    [35, 80, 100, 85],
    [10, 35, 80, 100],
]

P4_OPCIONES = ["Muy baja", "Baja", "Media", "Alta", "Inmersiva"]
P4_MATRIZ = [
    [100, 90, 60, 25, 0],
    [90, 100, 90, 55, 20],
    [65, 90, 100, 90, 60],
    [35, 65, 90, 100, 90],
    [10, 35, 65, 90, 100],
]

P8_OPCIONES = ["Muy baja", "Baja", "Media", "Alta", "Muy alta"]
P8_MATRIZ = [
    [100, 90, 55, 20, 0],
    [85, 100, 90, 55, 15],
    [55, 90, 100, 90, 55],
    [25, 60, 90, 100, 90],
    [5, 30, 65, 90, 100],
]

P9_OPCIONES = ["Tradicional", "Actualizado", "Equilibrado", "Diferente",
               "Referente"]
P9_MATRIZ = [
    [100, 95, 75, 45, 20],
    [90, 100, 95, 75, 45],
    [70, 95, 100, 95, 75],
    [45, 70, 95, 100, 95],
    [20, 45, 75, 95, 100],
]


# El texto COMPLETO de cada pregunta, tal como lo escribió David (07/09), en sus
# dos versiones. "Concepto" a secas no es una pregunta: es una etiqueta que sólo
# entiende quien ya sabe de qué va. Delante de un desplegable con ocho opciones,
# el proveedor necesita leer qué se le está preguntando.
#
# Y las dos versiones importan: al hotel se le pregunta qué BUSCA y al artista
# qué OFRECE. La misma etiqueta, dos preguntas distintas — que es justamente lo
# que hace que las respuestas se puedan cruzar.
PREGUNTAS_TEXTO: dict[str, dict[str, str]] = {
    "P1": {"hotel": "¿Cómo definirías el concepto de tu propiedad?",
           "show": "¿Cómo definirías tu show?"},
    "P2": {"hotel": "¿Qué sensación debería transmitir el entretenimiento?",
           "show": "¿Qué sensación transmite tu propuesta?"},
    "P3": {"hotel": "¿Qué nivel de protagonismo debe tener el entretenimiento?",
           "show": "¿Cómo es tu show?"},
    "P4": {"hotel": "¿Qué interacción con los huéspedes buscas en tu propiedad?",
           "show": "¿Qué nivel de interacción demanda tu show?"},
    "P5": {"hotel": "¿Qué estilo describe mejor tu marca?",
           "show": "¿Qué estilo visual describe tu show?"},
    "P6": {"hotel": "¿Cuál es el perfil predominante de huésped?",
           "show": "¿Qué perfil coincide más con tu estilo?"},
    "P7": {"hotel": "¿Qué personalidad debe tener el entretenimiento?",
           "show": "¿Cómo calificarías tu show?"},
    "P8": {"hotel": "¿Qué nivel de energía tiene tu propiedad?",
           "show": "¿Qué nivel de energía tiene tu propuesta?"},
    "P9": {"hotel": "¿Qué grado de innovación artística acepta la propiedad?",
           "show": "¿Qué tan innovadora es tu propuesta?"},
    "P10": {"hotel": "¿Qué debe conseguir el entretenimiento?",
            "show": "¿Qué crees que logra tu show?"},
}

PREGUNTAS: dict[str, tuple[str, list[str], list[list[int]]]] = {
    "P1": ("Concepto", P1_OPCIONES, P1_MATRIZ),
    "P2": ("Sensacion", P2_OPCIONES, P2_MATRIZ),
    "P3": ("Protagonismo", P3_OPCIONES, P3_MATRIZ),
    "P4": ("Interaccion", P4_OPCIONES, P4_MATRIZ),
    "P5": ("Estilo", P5_OPCIONES, P5_MATRIZ),
    "P6": ("Publico", P6_OPCIONES, P6_MATRIZ),
    "P7": ("Personalidad", P7_OPCIONES, P7_MATRIZ),
    "P8": ("Energia", P8_OPCIONES, P8_MATRIZ),
    "P9": ("Innovacion", P9_OPCIONES, P9_MATRIZ),
    "P10": ("Objetivo", P10_OPCIONES, P10_MATRIZ),
}

# Preguntas donde se puede marcar más de una respuesta (David: "para no ser
# blanco/negro, un hotel puede ser de lujo y familiar"). Hoy sólo la P6 está
# confirmada; el resto del bloque nominal queda pendiente de que lo cierre.
MULTIPLES = {"P6"}
MAX_SELECCIONES = 3

# --- Los cuatro scores ------------------------------------------------------
# David, 2026-09-07. Los tres de aquí salen del cuestionario; el TALENT sale de
# historial y no se calcula en este módulo.

SCORES: dict[str, dict[str, int]] = {
    "brand": {"P1": 30, "P2": 25, "P5": 20, "P7": 15, "P9": 10},
    "guest": {"P6": 70, "P2": 15, "P7": 15},
    "experience": {"P10": 25, "P3": 25, "P8": 20, "P4": 15, "P2": 15},
}

NOMBRES_SCORE = {
    "brand": "Afinidad de marca",
    "guest": "Afinidad de público",
    "experience": "Afinidad de experiencia",
}

# Qué preguntas contesta la PROPIEDAD y cuáles el SALÓN. Sale del propio ejemplo
# de David: en el mismo hotel de lujo, el lobby quiere un pianista de ambiente y
# el salón de shows quiere energía. Lo que cambia entre las dos salas es el
# protagonismo, la interacción, la energía y lo que se busca conseguir; lo que
# NO cambia es que el hotel sigue siendo de lujo y sus huéspedes son los mismos.
# La P2 se pregunta en los dos sitios y la del salón manda cuando está puesta.
PREGUNTAS_PROPIEDAD = ["P1", "P5", "P6", "P7", "P9", "P2"]
PREGUNTAS_SALON = ["P3", "P4", "P8", "P10", "P2"]

# Debajo de esto, una pregunta se avisa en vez de diluirse en el promedio.
SUELO = 40

# Moods de salón: rellenan de golpe las respuestas del bloque de experiencia,
# para no pedirle cuatro preguntas por sala a quien tiene quince salas. Se
# pueden retocar después. PROPUESTA, pendiente de que David los cierre.
MOODS: dict[str, dict[str, str]] = {
    "AMBIENTE": {"P3": "Ambiental", "P4": "Muy baja", "P8": "Baja",
                 "P10": "Ambiente", "P2": "Relajacion"},
    "SOCIAL": {"P3": "Moderado", "P4": "Alta", "P8": "Alta",
               "P10": "Conexion", "P2": "Diversion"},
    "ESTELAR": {"P3": "Show", "P4": "Baja", "P8": "Muy alta",
                "P10": "Recuerdos", "P2": "Sorpresa"},
}


class RespuestaInvalida(ValueError):
    """Una respuesta que no está en el juego de opciones de su pregunta."""


def _indices(pregunta: str, respuesta) -> list[int]:
    """Las respuestas de un lado, ya convertidas a posiciones de la matriz.

    Acepta una sola o una lista: la P6 admite hasta tres. Se valida aquí y no
    al guardar porque un texto que no está en la lista no puede puntuar contra
    nada, y es mejor que reviente al calcular que devolver un cero que parece
    un desencuentro real.
    """
    _, opciones, _ = PREGUNTAS[pregunta]
    valores = respuesta if isinstance(respuesta, (list, tuple, set)) else [respuesta]
    valores = [v for v in valores if v is not None]
    if not valores:
        return []
    if len(valores) > 1 and pregunta not in MULTIPLES:
        raise RespuestaInvalida(
            f"{pregunta} admite una sola respuesta, llegaron {len(valores)}")
    if len(valores) > MAX_SELECCIONES:
        raise RespuestaInvalida(
            f"{pregunta} admite hasta {MAX_SELECCIONES} respuestas")
    fuera = [v for v in valores if v not in opciones]
    if fuera:
        raise RespuestaInvalida(f"{pregunta}: {fuera!r} no está en {opciones}")
    return [opciones.index(v) for v in valores]


def cruzar(pregunta: str, hotel, show) -> float | None:
    """La nota de UNA pregunta. None si a alguno de los dos le falta contestar.

    Con varias respuestas por lado se promedian TODOS los cruces, no se coge el
    mejor: ver la nota 1 de la cabecera. Devolver None y no un cero es
    importante — "no contestó" y "no encaja" son cosas distintas, y un cero
    aquí hundiría a quien todavía no ha rellenado su ficha.
    """
    filas = _indices(pregunta, hotel)
    columnas = _indices(pregunta, show)
    if not filas or not columnas:
        return None
    _, _, matriz = PREGUNTAS[pregunta]
    cruces = [matriz[f][c] for f in filas for c in columnas]
    return sum(cruces) / len(cruces)


def puntuar_score(nombre: str, hotel: dict, show: dict) -> dict:
    """Un score, con su detalle y sus avisos.

    `cobertura` es cuánto peso llegó contestado. Va en la respuesta a propósito:
    un 88 calculado con la mitad de las preguntas no vale lo mismo que un 88
    completo, y quien pinte la pantalla tiene que poder decirlo.
    """
    pesos = SCORES[nombre]
    detalle: dict[str, float] = {}
    peso_ok = 0
    acumulado = 0.0
    for pregunta, peso in pesos.items():
        valor = cruzar(pregunta, hotel.get(pregunta), show.get(pregunta))
        if valor is None:
            continue
        detalle[pregunta] = valor
        acumulado += valor * peso
        peso_ok += peso
    if not peso_ok:
        return {"score": None, "detalle": {}, "avisos": [], "cobertura": 0.0}
    total = sum(pesos.values())
    return {
        # Se reparte sobre lo contestado para que una pregunta en blanco no
        # cuente como un cero, pero la cobertura viaja al lado para que no se
        # pueda enseñar como si estuviera completo.
        "score": round(acumulado / peso_ok, 1),
        "detalle": detalle,
        "avisos": sorted((p for p, v in detalle.items() if v < SUELO),
                         key=lambda p: detalle[p]),
        "cobertura": round(peso_ok / total, 3),
    }


def puntuar(hotel: dict, show: dict) -> dict:
    """Los tres scores de cuestionario para un par salón–show."""
    return {nombre: puntuar_score(nombre, hotel, show) for nombre in SCORES}


def motivos(resultado: dict, cuantos: int = 3) -> dict[str, list[str]]:
    """Por qué encaja y por qué no, en palabras y con las dos caras.

    Nunca se enseña sólo lo que coincide: el mago infantil en un resort de
    fiesta luce "protagonismo 100" mientras el concepto va en 35.
    """
    detalle: dict[str, float] = {}
    for datos in resultado.values():
        detalle.update(datos["detalle"])
    if not detalle:
        return {"favor": [], "contra": []}
    orden = sorted(detalle.items(), key=lambda kv: kv[1], reverse=True)
    etiqueta = lambda p, v: f"{PREGUNTAS[p][0].lower()} {v:.0f}"  # noqa: E731
    contra = [etiqueta(p, v) for p, v in reversed(orden) if v < 70][:cuantos]
    return {
        "favor": [etiqueta(p, v) for p, v in orden if v >= 70][:cuantos],
        "contra": contra,
    }


def perfil_salon(mood: str | None, propias: dict | None = None) -> dict:
    """Las respuestas de un salón: las del mood, pisadas por las suyas propias.

    Así el caso normal es un desplegable y el salón raro se sigue pudiendo
    describir a mano.
    """
    base = dict(MOODS.get((mood or "").upper(), {}))
    if propias:
        base.update({k: v for k, v in propias.items() if v is not None})
    return base


def perfil_hotel(propiedad: dict, salon: dict) -> dict:
    """Junta lo que contesta la casa con lo que contesta la sala.

    La sala manda donde las dos contestan (hoy sólo la P2): el lobby y el teatro
    del mismo hotel transmiten cosas distintas aunque la marca sea la misma.
    """
    perfil = {p: propiedad.get(p) for p in PREGUNTAS_PROPIEDAD if propiedad.get(p)}
    perfil.update({p: v for p, v in salon.items() if v is not None})
    return perfil
