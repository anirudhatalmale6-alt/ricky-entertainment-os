"""La página del pase, tal cual la ve el de la caseta de vigilancia.

Se genera entera en el servidor, con los datos ya dentro y sin ningún `fetch`
para pintarla. No es purismo: esto se abre en el celular de alguien que está en
una puerta de servicio con media barra de señal, y una pantalla en blanco
mientras carga es un pase que no sirve.

El diseño va al grano porque la pregunta es una sola y se contesta de lejos:
¿dejo pasar a esta gente o no? Por eso lo primero y más grande es la franja
VERDE o ROJA, antes que el nombre, antes que la hora. El resto son los datos
para comprobar que quien tiene enfrente es quien dice ser.
"""
from __future__ import annotations

from datetime import datetime
from html import escape as _e

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _fecha_larga(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return "—"
    return f"{_DIAS[d.weekday()]} {d.day} de {_MESES[d.month - 1]} de {d.year}"


def _hora(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return "—"
    return d.strftime("%H:%M")


def _dia_relativo(iso: str | None, hoy: datetime) -> str:
    """"Hoy", "mañana", "fue ayer"… El dato que de verdad evita el error en la
    puerta: un pase correcto pero de OTRO día es el caso que hay que cazar."""
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    dias = (d.date() - hoy.date()).days
    if dias == 0:
        return "HOY"
    if dias == 1:
        return "MAÑANA"
    if dias == -1:
        return "FUE AYER"
    if dias < 0:
        return f"FUE HACE {abs(dias)} DÍAS"
    return f"FALTAN {dias} DÍAS"


def pagina(d: dict, *, qr_uri: str, api_base: str, token: str, hoy: datetime | None = None) -> str:
    hoy = hoy or datetime.now()
    pasa = bool(d.get("puede_pasar"))
    rel = _dia_relativo(d.get("cuando"), hoy)
    # Un pase válido de otro día NO es un pase para hoy. Se avisa fuerte, porque
    # es justo el error que un vigilante cansado deja pasar.
    otro_dia = pasa and rel not in ("HOY", "")
    llegada = d.get("llegada_at")

    integrantes = d.get("integrantes")
    gente = (f"{integrantes} {'persona' if integrantes == 1 else 'personas'}"
             if integrantes else "no declarado por el proveedor")

    filas = [
        ("Show", d.get("show")),
        ("Personas que llegan", gente),
        ("Fecha", _fecha_larga(d.get("cuando"))),
        ("Hora", _hora(d.get("cuando")) + (f" a {_hora(d.get('termina'))}" if d.get("termina") else "")),
        ("Hotel", d.get("hotel")),
        ("Salón", d.get("salon")),
        ("Código de proveedor", d.get("codigo_proveedor")),
        ("Orden de actuación", d.get("folio")),
    ]
    cuerpo = "".join(
        f'<div class="f"><span>{_e(k)}</span><b>{_e(str(v))}</b></div>'
        for k, v in filas if v
    )

    if llegada:
        quien = d.get("llegada_por")
        bloque_llegada = (
            f'<div class="ok2">✓ Llegada confirmada a las {_e(_hora(llegada))}'
            + (f' por {_e(quien)}' if quien else "")
            + "</div>"
        )
    elif pasa:
        bloque_llegada = (
            '<div class="conf">'
            '<label for="quien">¿Quién confirma? (opcional)</label>'
            '<input id="quien" maxlength="120" placeholder="Tu nombre o el de la caseta" autocomplete="off">'
            '<button id="btn" onclick="confirmar()">Confirmar que llegaron</button>'
            '<div id="msg" class="msg"></div></div>'
        )
    else:
        bloque_llegada = (
            '<div class="aviso">No registres la llegada. '
            'Avisa a quien contrató la actuación antes de dar acceso.</div>'
        )

    return f"""<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Pase de acceso · {_e(d.get('folio') or 'SHOWMA')}</title>
<style>
  :root{{--tinta:#1b1f2e;--mut:#697089;--linea:#e6e8f0}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:#f4f5f9;color:var(--tinta);
    font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
  .hoja{{max-width:430px;margin:0 auto;padding:14px 14px 40px}}
  .marca{{text-align:center;font-weight:800;letter-spacing:3px;font-size:13px;
    color:var(--mut);padding:10px 0 12px}}
  .tarjeta{{background:#fff;border-radius:16px;overflow:hidden;
    box-shadow:0 2px 14px rgba(27,31,46,.09)}}
  .franja{{padding:18px 16px;text-align:center;color:#fff}}
  .franja.si{{background:#15803d}}
  .franja.no{{background:#b91c1c}}
  .franja .g{{font-size:25px;font-weight:800;letter-spacing:.5px;line-height:1.15}}
  .franja .p{{font-size:13px;opacity:.93;margin-top:5px}}
  .quien{{padding:18px 16px 4px;text-align:center}}
  .quien .n{{font-size:21px;font-weight:800;line-height:1.2}}
  .quien .rel{{display:inline-block;margin-top:8px;font-size:12px;font-weight:800;
    letter-spacing:.6px;padding:4px 11px;border-radius:20px;background:#eef0f6;color:var(--mut)}}
  .quien .rel.ojo{{background:#fef3c7;color:#92400e}}
  .datos{{padding:12px 16px 4px}}
  .f{{display:flex;justify-content:space-between;gap:14px;padding:9px 0;
    border-bottom:1px solid var(--linea);font-size:14px}}
  .f:last-child{{border-bottom:0}}
  .f span{{color:var(--mut);flex:none}}
  .f b{{text-align:right;font-weight:650}}
  .qr{{text-align:center;padding:6px 16px 18px}}
  .qr img{{width:150px;height:150px}}
  .qr div{{font-size:11px;color:var(--mut);margin-top:4px}}
  .conf{{padding:4px 16px 18px}}
  .conf label{{display:block;font-size:12.5px;color:var(--mut);margin-bottom:5px}}
  .conf input{{width:100%;padding:12px;border:1px solid var(--linea);border-radius:10px;
    font-size:16px;font-family:inherit}}
  .conf button{{width:100%;margin-top:10px;padding:15px;border:0;border-radius:11px;
    background:#382ca1;color:#fff;font-size:16px;font-weight:700;cursor:pointer}}
  .conf button:disabled{{opacity:.55}}
  .msg{{font-size:13px;margin-top:10px;text-align:center}}
  .ok2{{margin:4px 16px 18px;padding:14px;border-radius:11px;background:#dcfce7;
    color:#166534;font-weight:700;font-size:14px;text-align:center}}
  .aviso{{margin:4px 16px 18px;padding:14px;border-radius:11px;background:#fee2e2;
    color:#991b1b;font-weight:650;font-size:13.5px;text-align:center;line-height:1.45}}
  .pie{{text-align:center;font-size:11.5px;color:var(--mut);padding:16px 10px;line-height:1.6}}
</style>
<div class="hoja">
  <div class="marca">SHOWMA</div>
  <div class="tarjeta">
    <div class="franja {'si' if pasa else 'no'}">
      <div class="g">{'ACCESO AUTORIZADO' if pasa else 'NO AUTORIZADO'}</div>
      <div class="p">{_e(d.get('estado_texto') or '')}</div>
    </div>
    <div class="quien">
      <div class="n">{_e(d.get('quien') or '')}</div>
      {f'<div class="rel {"ojo" if otro_dia else ""}">{_e(rel)}</div>' if rel else ''}
    </div>
    <div class="datos">{cuerpo}</div>
    <div class="qr"><img src="{qr_uri}" alt="Código del pase">
      <div>Pase {_e(d.get('folio') or '')}</div></div>
    {bloque_llegada}
  </div>
  <div class="pie">Esta página la genera SHOWMA para control de acceso.<br>
    Si algo no coincide con quien tienes enfrente, no des acceso y avisa a quien contrató.</div>
</div>
<script>
async function confirmar(){{
  var b=document.getElementById('btn'), m=document.getElementById('msg');
  b.disabled=true; b.textContent='Confirmando…';
  try{{
    var r=await fetch({_js(api_base)}+'/public/pase/'+{_js(token)}+'/llegada',{{
      method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{quien:(document.getElementById('quien').value||'').trim()||null}})}});
    if(!r.ok) throw new Error('No se pudo registrar');
    var j=await r.json();
    document.querySelector('.conf').outerHTML =
      '<div class="ok2">✓ Llegada confirmada'+(j.llegada_por?' por '+j.llegada_por:'')+'</div>';
  }}catch(e){{
    b.disabled=false; b.textContent='Confirmar que llegaron';
    m.style.color='#b91c1c'; m.textContent='No se pudo registrar. Revisa la señal e intenta otra vez.';
  }}
}}
</script>"""


def _js(v: str) -> str:
    """Un literal de JavaScript seguro para meter dentro del <script>."""
    import json
    return json.dumps(v).replace("</", "<\\/")
