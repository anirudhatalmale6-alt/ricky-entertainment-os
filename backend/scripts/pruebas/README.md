# Pruebas manuales del análisis de desempeño

No usan pytest a propósito: levantan la API real contra una base sembrada y le
pegan por HTTP, que es como se rompen estas cosas (alcance del usuario, filtros,
lo que sale y lo que no sale en el JSON).

## Convocatoria en % del aforo

Reproduce el caso que planteó David el 16/08/2026: un teatro chico lleno contra
teatros grandes a media entrada. En gente por noche salía −68% (castigado por
llenar una sala pequeña); en puntos de llenado sale +45.

    cd backend
    .venv/bin/python scripts/pruebas/seed_llenado.py
    DATABASE_URL="sqlite+aiosqlite:///<ruta>/llenado.db" \
        .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8432 &
    python3 scripts/pruebas/test_llenado.py

Comprueba además que del bloque de otras propiedades salgan EXACTAMENTE los
campos permitidos: ni aforos, ni precios, ni nombres. La comprobación es sobre
el conjunto de llaves, no buscando palabras en el JSON — `noches_con_aforo`
contiene "aforo" y una búsqueda de texto no filtraría nada.
