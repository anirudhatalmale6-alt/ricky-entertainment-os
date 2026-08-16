# Entorno de demostración (showma.mx/demo)

Otra instancia de la MISMA aplicación, con su propia base de datos, para
presentar la plataforma sin tocar la operación real. Se montó el 16/08/2026
porque las comparativas de "Análisis de desempeño" no se pueden enseñar con la
base real todavía (casi ningún proveedor ha trabajado en dos propiedades) y esos
datos no se inventan en producción.

Servidor: 165.227.90.244

    /opt/ricky_demo/            copia de app/ + static/ + .env propio
    /opt/ricky_demo/ricky_demo.db
    systemd: showma-demo.service  -> uvicorn 127.0.0.1:8001
    nginx:  location /demo/       -> proxy_pass http://127.0.0.1:8001/

`ROOT_PATH=/demo` en su `.env`: `main.py` lo inyecta como `window.RICKY_API`, así
que el mismo dashboard.html sirve para las dos instancias sin tocar una línea.

El `.env` de la demo va SIN SMTP y con Facturama apagado a propósito: desde ahí
no sale un correo ni se timbra una factura.

## Volver a sembrarla

    cd /opt/ricky_demo && rm -f ricky_demo.db
    PYTHONPATH=/opt/ricky_demo /opt/ricky_app/.venv/bin/python \
        scripts/seed_demo.py /opt/ricky_demo/ricky_demo.db
    chown -R showma:showma /opt/ricky_demo && systemctl restart showma-demo

La semilla es fija: dos corridas dan exactamente los mismos números, así que una
captura de pantalla vieja sigue coincidiendo con lo que se ve en vivo.

## Al actualizar el frontend o el backend

La demo NO se actualiza sola. Después de desplegar a producción:

    rsync -a --delete --exclude __pycache__ backend/app/ root@IP:/opt/ricky_demo/app/
    scp frontend/dashboard.html root@IP:/opt/ricky_demo/static/dashboard.html
    ssh root@IP 'chown -R showma:showma /opt/ricky_demo && systemctl restart showma-demo'

## Para apagarla

    systemctl disable --now showma-demo
    (y quitar el bloque `location /demo/` de /etc/nginx/sites-available/showma)
