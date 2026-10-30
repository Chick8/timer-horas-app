"""Cálculo del pago mensual de cada persona.

  pago por horas  = horas APROBADAS (de categorías que se pagan por hora) × tarifa
  pago carreras   = lo que le toca en el reparto de cada carrera REALIZADA o PAGADA del mes
  total bruto     = pago por horas + pago carreras
  retención       = % de boleta de honorarios (configurable; 0 si se paga por contrato)

Las horas "por revisar" se muestran aparte como estimación: no entran al total hasta aprobarlas.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from .modelos import APROBADA, ESTADOS_QUE_PAGAN, PENDIENTE, FilaSueldo
from .reparto import calcular_reparto

MAX_HORAS_DIA = 16.0


def tarifa_aplicable(persona, categoria) -> float:
    if categoria is not None and categoria.tarifa_hora_especial not in (None, 0):
        return float(categoria.tarifa_hora_especial)
    return float(persona.tarifa_hora or 0) if persona is not None else 0.0


def validar_actividad(horas: float, descripcion: str, horas_ya_cargadas_dia: float) -> tuple[bool, str]:
    if horas is None or horas <= 0:
        return False, "Las horas deben ser mayores que 0."
    if horas > MAX_HORAS_DIA:
        return False, f"Una actividad no puede pasar de {MAX_HORAS_DIA:g} horas."
    if horas_ya_cargadas_dia + horas > MAX_HORAS_DIA:
        return False, (f"Con esta actividad el día sumaría {horas_ya_cargadas_dia + horas:g} h "
                       f"(máximo {MAX_HORAS_DIA:g} h por día).")
    if not (descripcion or "").strip():
        return False, "Escribe una descripción corta de lo que hiciste."
    return True, "OK"


def horas_entre(inicio: str, fin: str) -> float | None:
    """'09:00' y '11:30' -> 2.5. Si fin es menor que inicio, asume que cruzó la medianoche."""
    try:
        h1, m1 = (int(x) for x in inicio.split(":"))
        h2, m2 = (int(x) for x in fin.split(":"))
    except (ValueError, AttributeError):
        return None
    minutos = (h2 * 60 + m2) - (h1 * 60 + m1)
    if minutos < 0:
        minutos += 24 * 60
    return round(minutos / 60, 2)


def sueldos_del_mes(personas: dict, categorias: dict, actividades: list, eventos: list,
                    pct_retencion: float = 0.0) -> list[FilaSueldo]:
    """personas: {codigo: Persona} · categorias: {id: Categoria}
    actividades: list[Actividad] del mes (no anuladas) · eventos: list[Evento] con fecha en el mes."""
    filas: dict[str, FilaSueldo] = {}

    def fila(codigo: str) -> FilaSueldo:
        if codigo not in filas:
            p = personas.get(codigo)
            filas[codigo] = FilaSueldo(codigo=codigo, nombre=p.nombre if p else codigo,
                                       tarifa_hora=float(p.tarifa_hora) if p else 0.0)
            if p is None:
                filas[codigo].alertas.append("Persona no registrada.")
        return filas[codigo]

    for a in actividades:
        f = fila(a.codigo)
        cat = categorias.get(a.categoria_id)
        if cat is not None and not cat.pagable_por_hora:
            if a.estado != "rechazada":
                f.horas_evento += a.horas
            continue
        tarifa = tarifa_aplicable(personas.get(a.codigo), cat)
        if a.estado == APROBADA:
            f.horas_aprobadas += a.horas
            f.monto_horas += a.horas * tarifa
        elif a.estado == PENDIENTE:
            f.horas_pendientes += a.horas
            f.monto_pendiente += a.horas * tarifa

    for ev in eventos:
        if ev.estado not in ESTADOS_QUE_PAGAN:
            continue
        res = calcular_reparto(ev)
        for pago in res.pagos:
            if pago.monto:
                f = fila(pago.codigo)
                rol = pago.rol + (f" – {pago.funcion}" if pago.funcion else "")
                if ev.honorarios_aprobados:
                    f.monto_carreras += pago.monto
                    f.detalle_carreras.append((ev.nombre, rol, pago.monto))
                else:
                    f.monto_carreras_por_aprobar += pago.monto

    for f in filas.values():
        f.monto_horas = round(f.monto_horas)
        f.monto_pendiente = round(f.monto_pendiente)
        f.total_bruto = f.monto_horas + f.monto_carreras
        f.retencion = round(f.total_bruto * pct_retencion / 100)
        f.total_liquido = f.total_bruto - f.retencion
        if f.horas_aprobadas and not f.tarifa_hora:
            f.alertas.append("Tiene horas aprobadas pero su tarifa por hora es $0.")
        if f.horas_pendientes:
            f.alertas.append(f"{f.horas_pendientes:g} h por revisar (no entran al total todavía).")
        if f.monto_carreras_por_aprobar:
            f.alertas.append(f"${round(f.monto_carreras_por_aprobar):,} en honorarios de carrera por aprobar "
                             "(no entran al total todavía).".replace(",", "."))

    return sorted(filas.values(), key=lambda x: x.nombre.lower())


def totales_por(actividades: list, clave, solo_estados: set | None = None) -> dict:
    """Suma horas agrupando por `clave(actividad)`. Útil para ver horas por categoría, producto o persona."""
    tot = defaultdict(float)
    for a in actividades:
        if solo_estados is not None and a.estado not in solo_estados:
            continue
        tot[clave(a)] += a.horas
    return dict(sorted(tot.items(), key=lambda kv: -kv[1]))


def rango_mes(anio: int, mes: int) -> tuple[date, date]:
    """Primer día del mes y primer día del mes siguiente."""
    inicio = date(anio, mes, 1)
    fin = date(anio + (mes == 12), 1 if mes == 12 else mes + 1, 1)
    return inicio, fin
