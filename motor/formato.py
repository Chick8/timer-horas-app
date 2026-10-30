"""Textos y formatos: pesos chilenos, horas, nombres de meses y el calendario del mes."""
from __future__ import annotations

import calendar
from datetime import date

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
DIAS_CORTOS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def pesos(monto: float) -> str:
    """1234567.4 -> '$1.234.567'"""
    signo = "-" if monto < 0 else ""
    return f"{signo}${abs(round(monto)):,.0f}".replace(",", ".")


def horas_texto(h: float) -> str:
    """2.5 -> '2 h 30 min' · 3 -> '3 h' · 0.25 -> '15 min'"""
    minutos = round(h * 60)
    hh, mm = divmod(minutos, 60)
    if hh and mm:
        return f"{hh} h {mm} min"
    if hh:
        return f"{hh} h"
    return f"{mm} min"


def nombre_mes(anio: int, mes: int) -> str:
    return f"{MESES[mes - 1].capitalize()} {anio}"


def fecha_larga(d: date) -> str:
    return f"{DIAS_CORTOS[d.weekday()]} {d.day} de {MESES[d.month - 1]} {d.year}"


def semanas_del_mes(anio: int, mes: int) -> list[list[date | None]]:
    """Filas del calendario (lunes a domingo). None = casilla vacía fuera del mes."""
    cal = calendar.Calendar(firstweekday=0)
    return [[d if d.month == mes else None for d in semana] for semana in cal.monthdatescalendar(anio, mes)]
