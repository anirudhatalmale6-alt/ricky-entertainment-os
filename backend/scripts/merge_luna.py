"""Junta los dos registros de 'Luna Cirque' en uno solo.

En produccion el mismo proveedor quedo dado de alta dos veces: el artista 3 (sin
cuenta, creado a mano) y el artista 12 (su cuenta real, con foto). La historia
quedo partida y por eso ninguno de los dos llegaba al piso de comparacion.

Se conserva el 12 (tiene usuario y foto) y se le pasa TODO lo del 3. Los dos
shows repetidos se mapean al del que se queda, para no dejarle el catalogo
duplicado. Nada se borra hasta comprobar que ya no queda una sola referencia.

Uso:  python merge_luna.py /ruta/ricky.db [--aplicar]
"""
import sqlite3
import sys

DB = sys.argv[1]
APLICAR = "--aplicar" in sys.argv

VIEJO, NUEVO = 3, 12
SHOWS = {4: 14, 5: 15}          # mismo nombre y mismo precio en los dos lados

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
tablas = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]


def cols(t):
    return [r[1] for r in con.execute(f"pragma table_info({t})")]


con_artist = [t for t in tablas if "artist_id" in cols(t)]
con_show = [t for t in tablas if "show_id" in cols(t)]

antes_b = con.execute("select count(*) from bookings where artist_id=?", (NUEVO,)).fetchone()[0]
antes_v = con.execute("select count(*) from bookings where artist_id=?", (VIEJO,)).fetchone()[0]

con.execute("begin")
# 1. Los shows repetidos: todo lo que colgaba del viejo pasa al gemelo que se queda.
for viejo, nuevo in SHOWS.items():
    for t in con_show:
        con.execute(f"update {t} set show_id=? where show_id=?", (nuevo, viejo))

# 2. Los avisos del perfil viejo nunca los vio nadie (no tenia cuenta): entran
#    ya leidos, si no le aparecen 9 campanitas de actuaciones del ano pasado.
if "is_read" in cols("artist_notifications"):
    con.execute("update artist_notifications set is_read=1 where artist_id=?", (VIEJO,))

# 3. El resto de las referencias al perfil viejo.
for t in con_artist:
    con.execute(f"update {t} set artist_id=? where artist_id=?", (NUEVO, VIEJO))

# 4. Datos del perfil que el que se queda no tenia.
v = con.execute("select * from artists where id=?", (VIEJO,)).fetchone()
n = con.execute("select * from artists where id=?", (NUEVO,)).fetchone()
rellenos = []
for campo in ("city", "region", "bio", "phone", "email", "base_city", "website"):
    if campo in v.keys() and (n[campo] in (None, "")) and v[campo] not in (None, ""):
        con.execute(f"update artists set {campo}=? where id=?", (v[campo], NUEVO))
        rellenos.append(f"{campo}={v[campo]}")

# 5. Comprobar que no queda una sola referencia antes de borrar nada.
sobras = []
for t in con_artist:
    n_ = con.execute(f"select count(*) from {t} where artist_id=?", (VIEJO,)).fetchone()[0]
    if n_:
        sobras.append(f"{t}:{n_}")
for t in con_show:
    n_ = con.execute(
        f"select count(*) from {t} where show_id in ({','.join('?' * len(SHOWS))})",
        tuple(SHOWS),
    ).fetchone()[0]
    if n_:
        sobras.append(f"{t}(show):{n_}")
if sobras:
    con.rollback()
    print("NO SE TOCA NADA, quedan referencias:", sobras)
    sys.exit(1)

con.execute(f"delete from shows where id in ({','.join('?' * len(SHOWS))})", tuple(SHOWS))
con.execute("delete from artists where id=?", (VIEJO,))

despues = con.execute("select count(*) from bookings where artist_id=?", (NUEVO,)).fetchone()[0]
res = con.execute("select count(*), round(avg(rating),2) from reviews where artist_id=?", (NUEVO,)).fetchone()
props = con.execute(
    "select count(distinct company_id) from bookings where artist_id=? and status='completed'", (NUEVO,)
).fetchone()[0]
noches = con.execute(
    "select count(*) from bookings where artist_id=? and status='completed'", (NUEVO,)
).fetchone()[0]
shows_q = [dict(r) for r in con.execute(
    "select id,show_name from shows where artist_id=? order by id", (NUEVO,))]

print(f"actuaciones: {antes_v} (viejo) + {antes_b} (nuevo) = {despues}")
print(f"resenas: {res[0]} calificaciones, promedio {res[1]}")
print(f"completadas: {noches} noches en {props} propiedades")
print("shows:", shows_q)
print("rellenado:", rellenos or "nada")
print("artistas Luna que quedan:",
      [dict(r) for r in con.execute("select id,stage_name from artists where stage_name like '%Luna%'")])

if APLICAR:
    con.commit()
    print("\nAPLICADO")
else:
    con.rollback()
    print("\nSIMULACION (sin --aplicar no se guardo nada)")
