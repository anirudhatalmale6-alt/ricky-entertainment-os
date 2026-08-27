"""Las fotos subidas se sirven igual con y sin ROOT_PATH, y solo las de dentro.

El defecto que provoco esta prueba: con `app.mount("/uploads", StaticFiles(...))`
debajo de una app con root_path, Starlette no le recortaba el prefijo al hijo y
StaticFiles acababa buscando static/uploads/uploads/x.jpg. En produccion
(ROOT_PATH="") todo funcionaba; en la demo (ROOT_PATH=/demo) NINGUNA foto se
servia. Un defecto que solo aparece en la instancia donde nadie mira.

Se levanta la app DOS veces, una por configuracion, y se pide la misma foto.
Sin las dos mitades la prueba no prueba nada: con una sola habria pasado
tambien antes del arreglo.
"""
import os, socket, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

BACK = Path(__file__).resolve().parents[2]   # .../backend
fallos = []


def ok(c, m, x=""):
    print(("  OK   " if c else "  FALLA") + " " + m + (f"  [{x}]" if x else ""))
    if not c:
        fallos.append(m)


def libre():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def codigo(url):
    """GET, no HEAD: una ruta declarada con @app.get responde 405 a un HEAD, y
    ese 405 se leeria como 'no arranco' o como 'la foto no esta'. Del cuerpo no
    se lee nada: aqui solo importa el codigo."""
    try:
        return urllib.request.urlopen(url).status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def levanta(root_path, db, cwd):
    puerto = libre()
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db}", "ROOT_PATH": root_path}
    p = subprocess.Popen(
        [str(cwd / ".venv/bin/python"), "-m", "uvicorn", "app.main:app", "--port", str(puerto)],
        cwd=str(cwd), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(0.5)
        if codigo(f"http://127.0.0.1:{puerto}/health") == 200:
            return p, puerto
    p.kill()
    raise SystemExit("no arranco")


db = sys.argv[1]
subidas = BACK / "static" / "uploads"
foto = sorted(x.name for x in subidas.iterdir() if x.is_file())[0]
print(f"foto de prueba: {foto}")

for root in ("", "/demo"):
    proc, puerto = levanta(root, db, BACK)
    base = f"http://127.0.0.1:{puerto}"
    etq = f"ROOT_PATH={root or '(vacio)'}"
    try:
        ok(codigo(f"{base}/uploads/{foto}") == 200, f"{etq}: la foto se sirve",
           str(codigo(f"{base}/uploads/{foto}")))
        # Controles: lo que NO debe salir.
        ok(codigo(f"{base}/uploads/no-existe.jpg") == 404, f"{etq}: una inventada da 404")
        ok(codigo(f"{base}/uploads/..%2F..%2F.env") in (404, 400),
           f"{etq}: no se puede salir de la carpeta con ..",
           str(codigo(f"{base}/uploads/..%2F..%2F.env")))
        ok(codigo(f"{base}/uploads/") == 404, f"{etq}: no se listan las subidas")
    finally:
        proc.kill(); proc.wait()

print()
print("TODO BIEN" if not fallos else f"{len(fallos)} FALLAS: " + "; ".join(fallos))
