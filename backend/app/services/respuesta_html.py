"""La página donde el proveedor acepta o rechaza, sin entrar a su cuenta.

Se genera entera en el servidor, como la del pase: se abre desde el correo, a
menudo en un móvil, y una pantalla en blanco mientras carga es una decisión que
no se toma.

Lo importante del diseño: los datos ANTES que los botones. Quien llega aquí
viene de un correo y está decidiendo si se compromete con una fecha y un
importe. Si lo primero que ve es un botón verde, acepta sin leer.
"""
from __future__ import annotations

from datetime import datetime
from html import escape as _e

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _fecha(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return "—"
    return f"{_DIAS[d.weekday()]}, {d.day} de {_MESES[d.month - 1]} de {d.year}"


def _hora(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M")
    except ValueError:
        return ""


def _dinero(v, moneda="MXN") -> str:
    return f"${v:,.2f} {moneda}" if v is not None else ""


def _js(v: str) -> str:
    import json
    return json.dumps(v).replace("</", "<\\/")


def pagina(d: dict, *, api_base: str, token: str) -> str:
    horario = _hora(d.get("cuando")) + (f" a {_hora(d.get('termina'))}"
                                        if d.get("termina") else "")
    filas = [
        ("Orden", d.get("folio")),
        ("Show", d.get("show")),
        ("Hotel", d.get("hotel")),
        ("Salón", d.get("salon")),
        ("Fecha", _fecha(d.get("cuando"))),
        ("Horario", horario),
        ("Integrantes", str(d["integrantes"]) if d.get("integrantes") else ""),
        ("Importe acordado", _dinero(d.get("importe"), d.get("moneda", "MXN"))),
    ]
    cuerpo = "".join(
        f'<div class="f"><span>{_e(k)}</span><b>{_e(str(v))}</b></div>'
        for k, v in filas if v
    )

    if d.get("puede_contestar"):
        acciones = (
            '<div class="acc">'
            '<button class="si" id="bsi" onclick="responder(true)">Aceptar la actuación</button>'
            '<button class="no" id="bno" onclick="pedirMotivo()">No puedo</button>'
            '<div id="motivo" class="motivo">'
            '<label for="txt">¿Por qué no puedes? (opcional, lo verá el hotel)</label>'
            '<textarea id="txt" rows="2" maxlength="300" '
            'placeholder="Tengo otra fecha ese día…"></textarea>'
            '<button class="no" onclick="responder(false)">Confirmar que no puedo</button>'
            "</div>"
            '<div id="msg" class="msg"></div></div>'
        )
        pie = ("Al aceptar te mandamos por correo tu pase de acceso con el código QR "
               "para entrar a la propiedad.")
    else:
        acciones = f'<div class="ya">{_e(d.get("motivo") or "Esta actuación ya no admite respuesta.")}</div>'
        pie = "Puedes ver el detalle en tu perfil de SHOWMA."

    return f"""<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Solicitud de actuación · {_e(d.get('folio') or 'SHOWMA')}</title>
<style>
  :root{{--tinta:#1b1f2e;--mut:#697089;--linea:#e6e8f0}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:#f4f5f9;color:var(--tinta);
    font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
  .hoja{{max-width:440px;margin:0 auto;padding:14px 14px 40px}}
  .tarjeta{{background:#fff;border-radius:16px;overflow:hidden;
    box-shadow:0 2px 14px rgba(27,31,46,.09)}}
  .cab{{background:#111827;color:#fff;padding:18px 20px}}
  .cab .m{{font-size:19px;font-weight:800;letter-spacing:1px;line-height:1}}
  .cab .s{{font-size:9.5px;letter-spacing:3px;opacity:.65;margin-top:3px}}
  .ttl{{padding:18px 20px 2px;font-size:18px;font-weight:800;line-height:1.3}}
  .sub{{padding:0 20px;color:var(--mut);font-size:13.5px;line-height:1.5}}
  .datos{{padding:14px 20px 4px}}
  .f{{display:flex;justify-content:space-between;gap:14px;padding:9px 0;
    border-bottom:1px solid var(--linea);font-size:14px}}
  .f:last-child{{border-bottom:0}}
  .f span{{color:var(--mut);flex:none}}
  .f b{{text-align:right;font-weight:650}}
  .acc{{padding:6px 20px 20px}}
  .acc button{{width:100%;padding:15px;border:0;border-radius:11px;font-size:16px;
    font-weight:700;cursor:pointer;margin-top:10px}}
  .acc .si{{background:#15803d;color:#fff}}
  .acc .no{{background:#fff;color:#b91c1c;border:1.5px solid #f0c9c9}}
  .acc button:disabled{{opacity:.5}}
  .motivo{{display:none;margin-top:12px}}
  .motivo label{{display:block;font-size:12.5px;color:var(--mut);margin-bottom:5px}}
  .motivo textarea{{width:100%;padding:11px;border:1px solid var(--linea);
    border-radius:10px;font-size:16px;font-family:inherit}}
  .msg{{font-size:14px;margin-top:14px;text-align:center;line-height:1.5}}
  .ya{{margin:6px 20px 20px;padding:16px;border-radius:11px;background:#eef0f6;
    color:var(--mut);font-size:14px;text-align:center;line-height:1.5}}
  .ok{{margin:6px 20px 20px;padding:18px;border-radius:11px;background:#dcfce7;
    color:#166534;font-weight:700;font-size:15px;text-align:center;line-height:1.5}}
  .pie{{text-align:center;font-size:11.5px;color:var(--mut);padding:16px 10px;line-height:1.6}}
</style>
<div class="hoja">
  <div class="tarjeta">
    <div class="cab"><div class="m">SHOWMA</div><div class="s">ENTERTAINMENT OS</div></div>
    <div class="ttl">¡Tienes una nueva solicitud!</div>
    <div class="sub">Hola{(", " + _e(d["artista"])) if d.get("artista") else ""}:<br>
      <b>{_e(d.get("hotel") or "Un hotel")}</b> quiere contar contigo para esta actuación.</div>
    <div class="datos">{cuerpo}</div>
    {acciones}
  </div>
  <div class="pie">{pie}</div>
</div>
<script>
function pedirMotivo(){{
  var m=document.getElementById('motivo');
  m.style.display='block';
  document.getElementById('bno').style.display='none';
  document.getElementById('txt').focus();
}}
async function responder(acepta){{
  var si=document.getElementById('bsi'), msg=document.getElementById('msg');
  document.querySelectorAll('.acc button').forEach(function(b){{b.disabled=true;}});
  if(acepta) si.textContent='Confirmando…';
  var cuerpo = acepta ? null : JSON.stringify({{
    motivo:(document.getElementById('txt').value||'').trim()||null}});
  try{{
    var r=await fetch({_js(api_base)}+'/public/responder/'+{_js(token)}+
                      (acepta?'/aceptar':'/rechazar'),
      {{method:'POST', headers:{{'Content-Type':'application/json'}},
        body: cuerpo || '{{}}'}});
    var j=await r.json();
    if(!r.ok) throw new Error(j.detail||'No se pudo registrar');
    document.querySelector('.acc').outerHTML='<div class="ok">'+j.mensaje+'</div>';
  }}catch(e){{
    document.querySelectorAll('.acc button').forEach(function(b){{b.disabled=false;}});
    if(acepta) si.textContent='Aceptar la actuación';
    msg.style.color='#b91c1c';
    msg.textContent=e.message||'No se pudo registrar. Revisa la señal e intenta otra vez.';
  }}
}}
</script>"""
