"""Reparto del dinero de una carrera entre la empresa, el director de carrera y el equipo TIMER.

Cómo funciona (todo en pesos, valores NETOS sin IVA):
  1. Margen = venta neta − gastos (viáticos, transporte, alojamiento, chips...).
  2. Sobre la "base" (el margen, o la venta neta si así se elige) se aplican los porcentajes:
       empresa %  +  director %  +  equipo %  = 100 %
  3. La parte del director se reparte entre los directores (normalmente uno).
     La parte del equipo se reparte entre técnicos y apoyo en proporción a su "peso"
     (jornadas o días trabajados; 1 si todos trabajaron lo mismo).

Los viáticos son reembolso de gastos, no sueldo: por eso se restan antes de repartir.
"""
from __future__ import annotations

from .modelos import (
    BASE_MARGEN, BASE_VENTA, DIRECTOR, Evento, PagoIntegrante, ReglasReparto, ResultadoReparto,
)

TOLERANCIA_PCT = 0.01


def validar_reglas(r: ReglasReparto) -> tuple[bool, str]:
    for nombre, v in (("empresa", r.pct_empresa), ("director", r.pct_director), ("equipo", r.pct_equipo)):
        if v < 0 or v > 100:
            return False, f"El porcentaje de {nombre} debe estar entre 0 y 100."
    suma = r.pct_empresa + r.pct_director + r.pct_equipo
    if abs(suma - 100) > TOLERANCIA_PCT:
        return False, f"Los porcentajes suman {suma:g} %; deben sumar 100 %."
    if r.base not in (BASE_MARGEN, BASE_VENTA):
        return False, "Base de reparto inválida."
    return True, "OK"


def _repartir(monto: float, integrantes: list) -> list[PagoIntegrante]:
    """Reparte `monto` en proporción a jornadas × ponderación de cada integrante."""
    peso_total = sum(i.peso_final for i in integrantes)
    if monto <= 0 or not integrantes or peso_total <= 0:
        return [PagoIntegrante(i.codigo, i.rol, i.peso, 0.0, i.factor, i.funcion, 0.0) for i in integrantes]
    pagos = [PagoIntegrante(i.codigo, i.rol, i.peso, round(monto * i.peso_final / peso_total), i.factor, i.funcion,
                            i.peso_final / peso_total * 100)
             for i in integrantes]
    # Redondeo a pesos: la diferencia (1-2 pesos) se suma al de mayor participación para que cuadre exacto.
    diferencia = round(monto) - sum(p.monto for p in pagos)
    if diferencia:
        max(pagos, key=lambda p: p.participacion).monto += diferencia
    return pagos


def calcular_reparto(evento: Evento) -> ResultadoReparto:
    r = evento.reglas
    alertas = []
    ok, msg = validar_reglas(r)
    if not ok:
        alertas.append(msg)

    venta = float(evento.venta_neta or 0)
    gastos = sum(float(g.monto or 0) for g in evento.gastos)
    margen = venta - gastos
    margen_pct = (margen / venta * 100) if venta else 0.0

    base = margen if r.base == BASE_MARGEN else venta
    if base <= 0 or not ok:
        if venta and margen <= 0:
            alertas.append("Los gastos son iguales o mayores que la venta: no queda margen para repartir.")
        base_aplicable = 0.0
    else:
        base_aplicable = base

    monto_director = round(base_aplicable * r.pct_director / 100)
    monto_equipo = round(base_aplicable * r.pct_equipo / 100)

    directores = [i for i in evento.equipo if i.rol == DIRECTOR]
    equipo = [i for i in evento.equipo if i.rol != DIRECTOR]
    if monto_director and not directores:
        alertas.append("No hay director de carrera asignado: su parte queda en la empresa.")
        monto_director = 0
    if monto_equipo and not equipo:
        alertas.append("No hay técnicos asignados: la parte del equipo queda en la empresa.")
        monto_equipo = 0

    pagos = _repartir(monto_director, directores) + _repartir(monto_equipo, equipo)

    if r.base == BASE_MARGEN:
        monto_empresa = margen - monto_director - monto_equipo if base_aplicable else margen
    else:
        monto_empresa = venta - gastos - monto_director - monto_equipo
        if monto_empresa < 0:
            alertas.append("Con base en la venta, a la empresa no le alcanza para cubrir los gastos.")

    return ResultadoReparto(
        venta_neta=venta, total_gastos=gastos, margen=margen, margen_pct=margen_pct,
        base_monto=base_aplicable, monto_empresa=monto_empresa, monto_director=float(monto_director),
        monto_equipo=float(monto_equipo), pagos=pagos, alertas=alertas,
    )
