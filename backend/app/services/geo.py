"""Distancia aproximada entre el hotel y el proveedor.

No guardamos coordenadas del artista (sólo su ciudad base), así que resolvemos
la ciudad contra una tabla de destinos y capitales de México y calculamos la
distancia en línea recta. Es una aproximación suficiente para filtrar "¿está
cerca?": lo que interesa es distinguir 40 km de 2 000 km, no 40 de 45.

Si no reconocemos alguna de las dos ciudades devolvemos ``None`` y el filtro
deja pasar al proveedor: preferimos mostrar de más que esconder a alguien por
un dato incompleto.
"""
from __future__ import annotations

import unicodedata
from math import asin, cos, radians, sin, sqrt

# --- Ciudades (lat, lon) --------------------------------------------------
# Destinos turísticos, capitales y plazas donde opera el catálogo.
CITIES: dict[str, tuple[float, float]] = {
    # Quintana Roo / Yucatán / Caribe
    "cancun": (21.1619, -86.8515),
    "playa del carmen": (20.6296, -87.0739),
    "tulum": (20.2114, -87.4654),
    "cozumel": (20.4230, -86.9223),
    "isla mujeres": (21.2311, -86.7310),
    "puerto morelos": (20.8480, -86.8750),
    "bacalar": (18.6769, -88.3886),
    "chetumal": (18.5002, -88.2961),
    "akumal": (20.3936, -87.3150),
    "puerto aventuras": (20.4970, -87.2270),
    "merida": (20.9674, -89.5926),
    "progreso": (21.2820, -89.6640),
    "valladolid": (20.6896, -88.2011),
    "campeche": (19.8301, -90.5349),
    # Pacífico
    "puerto vallarta": (20.6534, -105.2253),
    "nuevo vallarta": (20.6940, -105.2950),
    "sayulita": (20.8690, -105.4410),
    "punta mita": (20.7700, -105.5150),
    "manzanillo": (19.1138, -104.3388),
    "colima": (19.2433, -103.7240),
    "barra de navidad": (19.2010, -104.6840),
    "mazatlan": (23.2494, -106.4111),
    "los cabos": (22.9083, -109.9167),
    "cabo san lucas": (22.8905, -109.9167),
    "san jose del cabo": (23.0631, -109.7020),
    "san jose": (23.0631, -109.7020),          # como lo escriben en el registro
    "la paz": (24.1426, -110.3128),
    "loreto": (26.0115, -111.3486),
    "todos santos": (23.4467, -110.2270),
    "acapulco": (16.8531, -99.8237),
    "ixtapa": (17.6640, -101.6070),
    "zihuatanejo": (17.6416, -101.5515),
    "puerto escondido": (15.8720, -97.0767),
    "huatulco": (15.7690, -96.1330),
    "mazunte": (15.6660, -96.5530),
    # Centro
    "ciudad de mexico": (19.4326, -99.1332),
    "cdmx": (19.4326, -99.1332),
    "mexico": (19.4326, -99.1332),
    "toluca": (19.2826, -99.6557),
    "cuernavaca": (18.9242, -99.2216),
    "cuautla": (18.8130, -98.9540),
    "taxco": (18.5575, -99.6050),
    "puebla": (19.0414, -98.2063),
    "cholula": (19.0630, -98.3030),
    "tlaxcala": (19.3139, -98.2404),
    "pachuca": (20.1011, -98.7591),
    "queretaro": (20.5888, -100.3899),
    "san miguel de allende": (20.9144, -100.7436),
    "guanajuato": (21.0190, -101.2574),
    "leon": (21.1219, -101.6833),
    "morelia": (19.7060, -101.1950),
    "zamora": (19.9853, -102.2836),
    "uruapan": (19.4110, -102.0560),
    "patzcuaro": (19.5130, -101.6090),
    "aguascalientes": (21.8853, -102.2916),
    "san luis potosi": (22.1565, -100.9855),
    "zacatecas": (22.7709, -102.5833),
    # Occidente / Norte
    "guadalajara": (20.6597, -103.3496),
    "zapopan": (20.7214, -103.3918),
    "tlaquepaque": (20.6410, -103.3120),
    "chapala": (20.2950, -103.1910),
    "tepic": (21.5042, -104.8946),
    "monterrey": (25.6866, -100.3161),
    "san pedro garza garcia": (25.6570, -100.4020),
    "saltillo": (25.4232, -101.0053),
    "torreon": (25.5428, -103.4068),
    "durango": (24.0277, -104.6532),
    "chihuahua": (28.6330, -106.0691),
    "ciudad juarez": (31.6904, -106.4245),
    "hermosillo": (29.0729, -110.9559),
    "ciudad obregon": (27.4864, -109.9400),
    "los mochis": (25.7933, -108.9973),
    "culiacan": (24.8091, -107.3940),
    "tijuana": (32.5149, -117.0382),
    "rosarito": (32.3610, -117.0580),
    "ensenada": (31.8667, -116.5964),
    "mexicali": (32.6245, -115.4523),
    # Golfo / Sureste
    "veracruz": (19.1738, -96.1342),
    "boca del rio": (19.1050, -96.1060),
    "xalapa": (19.5438, -96.9102),
    "coatzacoalcos": (18.1345, -94.4590),
    "cordoba": (18.8833, -96.9333),
    "orizaba": (18.8514, -97.0990),
    "tampico": (22.2331, -97.8611),
    "ciudad victoria": (23.7369, -99.1411),
    "reynosa": (26.0806, -98.2880),
    "matamoros": (25.8690, -97.5025),
    "nuevo laredo": (27.4763, -99.5164),
    "villahermosa": (17.9892, -92.9475),
    "tuxtla gutierrez": (16.7531, -93.1156),
    "san cristobal de las casas": (16.7370, -92.6376),
    "palenque": (17.5090, -91.9840),
    "tapachula": (14.9110, -92.2617),
    "oaxaca": (17.0732, -96.7266),
}

# Estado -> ciudad de referencia, para cuando sólo tenemos el estado.
REGIONS: dict[str, str] = {
    "quintana roo": "cancun",
    "yucatan": "merida",
    "campeche": "campeche",
    "baja california sur": "la paz",
    "baja california": "tijuana",
    "jalisco": "guadalajara",
    "nayarit": "tepic",
    "colima": "colima",
    "sinaloa": "culiacan",
    "sonora": "hermosillo",
    "chihuahua": "chihuahua",
    "coahuila": "saltillo",
    "nuevo leon": "monterrey",
    "tamaulipas": "ciudad victoria",
    "durango": "durango",
    "zacatecas": "zacatecas",
    "aguascalientes": "aguascalientes",
    "san luis potosi": "san luis potosi",
    "guanajuato": "guanajuato",
    "queretaro": "queretaro",
    "hidalgo": "pachuca",
    "michoacan": "morelia",
    "estado de mexico": "toluca",
    "mexico": "toluca",
    "ciudad de mexico": "ciudad de mexico",
    "cdmx": "ciudad de mexico",
    "morelos": "cuernavaca",
    "puebla": "puebla",
    "tlaxcala": "tlaxcala",
    "veracruz": "veracruz",
    "guerrero": "acapulco",
    "oaxaca": "oaxaca",
    "chiapas": "tuxtla gutierrez",
    "tabasco": "villahermosa",
}


def _norm(s: str | None) -> str:
    """minúsculas, sin acentos y sin ruido ('Cancún, Q. Roo' -> 'cancun')."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    for sep in (",", "/", "|", " - "):
        if sep in s:
            s = s.split(sep)[0].strip()
    return " ".join(s.split())


def coords_for(city: str | None, region: str | None = None) -> tuple[float, float] | None:
    """Coordenadas de una ciudad; si no la conocemos, las de su estado."""
    c = _norm(city)
    if c in CITIES:
        return CITIES[c]
    # "playa del carmen, quintana roo" ya viene recortado; probamos por prefijo
    for name, pt in CITIES.items():
        if c and (c.startswith(name) or name.startswith(c)) and abs(len(c) - len(name)) <= 4:
            return pt
    r = _norm(region)
    ref = REGIONS.get(r)
    if ref:
        return CITIES.get(ref)
    return None


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return round(2 * 6371.0 * asin(sqrt(h)), 1)


def distance_km(city_a: str | None, region_a: str | None,
                city_b: str | None, region_b: str | None) -> float | None:
    """Distancia aproximada entre dos plazas, o None si no se puede calcular."""
    pa, pb = coords_for(city_a, region_a), coords_for(city_b, region_b)
    if pa is None or pb is None:
        return None
    return haversine_km(pa, pb)
