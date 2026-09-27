"""El expediente del proveedor: qué documentos le tocan y en qué estado están.

David, 26/09. Las cadenas grandes (HYATT y dos más, entre las tres más de 25
propiedades) piden un paquete de documentos que hoy los proveedores mandan por
correo. La idea es guardarlos aquí, avisar de los vencimientos y que el hotel
pueda consultarlos.

Tres decisiones que están metidas en la forma de este archivo:

1. UNA SOLA LISTA PARA TODOS. El checklist de la cadena es el mismo para
   cualquier proveedor; lo que cambia es que algunos renglones no le aplican.
   Por eso no hay listas por tipo de perfil, hay un catálogo único y un estado
   NO_APLICA, exactamente como la columna "No Aplica" del documento original.

2. LO QUE NO APLICA SE SABE SOLO CUANDO SE PUEDE. Acta constitutiva y poder del
   representante dicen, en el propio checklist, "aplica solo si el Proveedor es
   persona moral". Eso lo deduce el sistema del RFC (12 dígitos = moral,
   13 = física) y no se le pregunta a nadie. El resto de "si aplica" los marca
   el proveedor, porque dependen de su giro y nadie más lo sabe.

3. SHOWMA NO VALIDA AUTENTICIDAD, y el código no debe sugerir lo contrario. Las
   fechas las declara el proveedor. Por eso el estado se llama COMPLETO y no
   "verificado": dice que el archivo está y que la fecha declarada no ha pasado,
   que es todo lo que podemos sostener. El sello de verificado, si algún día se
   ofrece, es trabajo humano y va aparte.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# --- Estados de un renglón, los mismos tres del checklist de la cadena -------
COMPLETO = "completo"
PENDIENTE = "pendiente"
NO_APLICA = "no_aplica"
POR_VENCER = "por_vencer"   # subestado de completo: está, pero se acaba
VENCIDO = "vencido"         # subestado de pendiente: estuvo y ya no vale

# Con cuántos días de antelación se considera "por vencer". 30 días da tiempo a
# sacar una opinión de cumplimiento nueva sin correr.
DIAS_AVISO = 30


@dataclass(frozen=True)
class TipoDoc:
    codigo: str
    nombre: str
    grupo: str
    # None = no caduca. "fecha" = el documento trae su vencimiento impreso.
    # "antiguedad" = no vence, pero no vale si es más viejo que `meses_max`.
    caducidad: str | None = None
    meses_max: int | None = None
    # Sólo para personas morales (lo dice el checklist en el propio renglón).
    solo_moral: bool = False
    # El proveedor puede marcarlo "no aplica" (los "si aplica" del checklist).
    opcional: bool = False
    ayuda: str = ""


# Grupos, en el orden del checklist de la cadena.
GRUPOS = [
    ("corporativo", "Corporativo"),
    ("contacto", "Operativo y contacto"),
    ("servicio", "Del servicio"),
    ("laboral", "Regulatorio y laboral"),
    ("fiscal", "Fiscal y seguridad social"),
    ("permisos", "Permisos y autorizaciones"),
    ("seguros", "Seguros"),
]

# El catálogo. Añadir una cadena que pida un documento nuevo es añadir una línea
# aquí: ni migración, ni pantalla nueva, ni tocar el frontend.
CATALOGO: list[TipoDoc] = [
    # --- A. Corporativo ---
    TipoDoc("acta_constitutiva", "Acta constitutiva con boleta de registro público",
            "corporativo", solo_moral=True,
            ayuda="Sólo si el proveedor es persona moral."),
    TipoDoc("poder_representante", "Poder o facultades del representante legal",
            "corporativo", solo_moral=True,
            ayuda="Sólo si el proveedor es persona moral."),
    TipoDoc("identificacion", "Identificación oficial vigente",
            "corporativo", caducidad="fecha",
            ayuda="INE o pasaporte del representante legal, o del proveedor si es persona física."),
    TipoDoc("constancia_sat", "Constancia de Situación Fiscal (RFC)",
            "corporativo", caducidad="antiguedad", meses_max=3,
            ayuda="La del SAT, reciente."),
    TipoDoc("comprobante_domicilio", "Comprobante de domicilio",
            "corporativo", caducidad="antiguedad", meses_max=3,
            ayuda="Luz, agua o teléfono, con no más de 3 meses."),
    TipoDoc("registro_estatal", "Constancia de Inscripción al Registro Estatal de Contribuyentes",
            "corporativo"),

    # --- B. Operativo y contacto ---
    TipoDoc("comprobante_bancario", "Carátula de cuenta bancaria (CLABE)",
            "contacto",
            ayuda="La hoja del banco donde se ve la CLABE a la que te pagamos."),

    # --- C. Del servicio ---
    TipoDoc("propuesta_tecnica", "Carta propuesta técnica de servicios",
            "servicio",
            ayuda="Descripción del servicio, periodicidad, costo y forma de pago, "
                  "garantías y número de personas asignadas."),

    # --- D. Regulatorio y laboral ---
    TipoDoc("registro_patronal", "Registro Patronal vigente ante el IMSS", "laboral"),
    TipoDoc("lista_empleados", "Lista de empleados que prestarán los servicios",
            "laboral",
            ayuda="Un solo archivo (Excel) con nombre, categoría, CURP, RFC y número "
                  "de seguro social. Así lo actualizas una vez y sirve para todos tus shows."),
    TipoDoc("repse", "Registro ante la STPS (REPSE)", "laboral",
            caducidad="fecha", opcional=True,
            ayuda="Sólo si prestas servicios especializados."),
    TipoDoc("registro_estatal_servicios", "Registro estatal como prestadora de servicios especializados",
            "laboral", caducidad="fecha", opcional=True),

    # --- E. Fiscal y seguridad social ---
    TipoDoc("opinion_sat", "Opinión de Cumplimiento del SAT",
            "fiscal", caducidad="antiguedad", meses_max=1,
            ayuda="La 32-D. Caduca rápido: conviene renovarla cada mes."),
    TipoDoc("opinion_imss", "Opinión de Cumplimiento del IMSS",
            "fiscal", caducidad="antiguedad", meses_max=1),
    TipoDoc("obligaciones_estatales", "Constancia de Obligaciones Fiscales Estatales",
            "fiscal", caducidad="fecha"),

    # --- F. Permisos ---
    TipoDoc("licencias", "Licencias, permisos o autorizaciones",
            "permisos", caducidad="fecha", opcional=True,
            ayuda="Sólo si tu servicio los requiere (pirotecnia, animales, alturas…)."),

    # --- G. Seguros ---
    TipoDoc("poliza_seguro", "Póliza de seguro vigente",
            "seguros", caducidad="fecha",
            ayuda="Responsabilidad civil u otra. Anota la aseguradora y el número de póliza."),
]

POR_CODIGO = {t.codigo: t for t in CATALOGO}


def es_persona_moral(rfc: str | None) -> bool | None:
    """True moral, False física, None si no hay RFC para saberlo.

    El RFC de una empresa tiene 12 caracteres y el de una persona 13. Es la
    forma de no preguntarle al proveedor algo que ya nos dijo.
    """
    limpio = (rfc or "").replace(" ", "").replace("-", "").strip()
    if len(limpio) == 12:
        return True
    if len(limpio) == 13:
        return False
    return None


def aplica(tipo: TipoDoc, *, rfc: str | None) -> bool:
    """¿Este documento le toca a este proveedor?"""
    if tipo.solo_moral:
        # Si no sabemos si es moral, se pide: es peor dar por bueno un expediente
        # al que le falta el acta que molestar a alguien con un "no aplica".
        return es_persona_moral(rfc) is not False
    return True


def vencimiento(tipo: TipoDoc, *, vence_el: date | None, emitido_el: date | None) -> date | None:
    """La fecha en la que ese documento deja de valer, o None si no caduca.

    Para los de antigüedad el proveedor no sabe "cuándo vence" su recibo de luz:
    lo que se le pide es cuándo lo emitieron, y el vencimiento se calcula.
    """
    if tipo.caducidad == "fecha":
        return vence_el
    if tipo.caducidad == "antiguedad" and emitido_el and tipo.meses_max:
        return emitido_el + timedelta(days=int(tipo.meses_max * 30.4))
    return None


def estado(tipo: TipoDoc, *, tiene_archivo: bool, marcado_no_aplica: bool,
           vence_el: date | None, emitido_el: date | None, hoy: date) -> tuple[str, date | None]:
    """El estado de un renglón y hasta cuándo vale. Devuelve (estado, fecha)."""
    if marcado_no_aplica and tipo.opcional:
        return NO_APLICA, None
    if not tiene_archivo:
        return PENDIENTE, None
    limite = vencimiento(tipo, vence_el=vence_el, emitido_el=emitido_el)
    if limite is None:
        return COMPLETO, None
    if limite < hoy:
        return VENCIDO, limite
    if (limite - hoy).days <= DIAS_AVISO:
        return POR_VENCER, limite
    return COMPLETO, limite


def cuenta_como_completo(est: str) -> bool:
    """Por vencer TODAVÍA cuenta: el documento está y hoy sirve. Lo que no
    cuenta es vencido, que es exactamente igual de inútil que no tenerlo."""
    return est in (COMPLETO, POR_VENCER, NO_APLICA)
