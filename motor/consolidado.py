"""Consolidados de horas (día / semana / mes / trimestre / año) y simulador de sueldo.

Funciones puras: reciben filas ya leídas de la base (diccionarios) y el conjunto de ids que
"entran" al cálculo. No tocan la base de datos, así se pueden probar solas.

Cada fila es un dict con al menos: id, fecha (date), horas, pagable (bool), tarifa (float),
y los textos categoria, grupo, producto, carrera, cliente, etiqueta, persona, estado, descripcion.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import median

PERIODOS = ("Día", "Semana", "Mes", "Trimestre", "Año")
DIMENSIONES = {
    "Tipo de actividad": "categoria",
    "Grupo de actividad": "grupo",
    "Producto": "producto",
    "Carrera": "carrera",
    "Cliente": "cliente",
    "Etiqueta": "etiqueta",
    "Persona": "persona",
    "Estado": "estado",
}
SIN_DATO = "(sin dato)"
MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def clave_periodo(d: date, periodo: str) -> tuple[str, str]:
    """(clave para ordenar, nombre para mostrar) del período al que pertenece una fecha."""
    if periodo == "Día":
        return d.isoformat(), d.strftime("%d-%m-%Y")
    if periodo == "Semana":
        lunes = d - timedelta(days=d.weekday())
        anio, sem, _ = d.isocalendar()
        return f"{anio}-{sem:02d}", f"Sem {sem:02d} · {lunes:%d-%m}"
    if periodo == "Mes":
        return f"{d.year}-{d.month:02d}", f"{MESES[d.month - 1]} {d.year}"
    if periodo == "Trimestre":
        t = (d.month - 1) // 3 + 1
        return f"{d.year}-T{t}", f"T{t} {d.year}"
    return str(d.year), str(d.year)


def texto_dim(f: dict, campo: str) -> str:
    v = str(f.get(campo) or "").strip()
    return v or SIN_DATO


def valor_fila(f: dict, tarifa_simulada: float | None = None) -> float:
    """Valor en pesos de una actividad: horas × tarifa (0 si se paga por reparto de carrera)."""
    if not f.get("pagable", True):
        return 0.0
    tarifa = tarifa_simulada if tarifa_simulada else float(f.get("tarifa") or 0)
    return float(f["horas"]) * tarifa


def _meses_entre(desde: date, hasta: date) -> float:
    return max(((hasta - desde).days + 1) / 30.4375, 1 / 30.4375)


def totales(filas: list[dict], incluidas: set, tarifa: float | None = None, retencion_pct: float = 0.0,
            desde: date | None = None, hasta: date | None = None) -> dict:
    """Totales de lo incluido + promedios para pensar un sueldo fijo."""
    dentro = [f for f in filas if f["id"] in incluidas]
    horas = sum(float(f["horas"]) for f in dentro)
    horas_todo = sum(float(f["horas"]) for f in filas)
    bruto = sum(valor_fila(f, tarifa) for f in dentro)
    bruto_todo = sum(valor_fila(f, tarifa) for f in filas)
    ret = round(bruto * retencion_pct / 100)
    meses_activos = {(f["fecha"].year, f["fecha"].month) for f in dentro}
    semanas_activas = {tuple(f["fecha"].isocalendar()[:2]) for f in dentro}
    if desde and hasta:
        meses_periodo = _meses_entre(desde, hasta)
    elif dentro:
        meses_periodo = _meses_entre(min(f["fecha"] for f in dentro), max(f["fecha"] for f in dentro))
    else:
        meses_periodo = 1.0
    return {
        "registros": len(dentro), "registros_todo": len(filas),
        "horas": horas, "horas_todo": horas_todo, "horas_fuera": horas_todo - horas,
        "bruto": bruto, "bruto_todo": bruto_todo, "retencion": ret, "liquido": bruto - ret,
        "dias": len({f["fecha"] for f in dentro}),
        "meses_activos": len(meses_activos), "semanas_activas": len(semanas_activas),
        "meses_periodo": meses_periodo,
        "horas_mes": horas / meses_periodo if meses_periodo else 0.0,
        "horas_semana": horas / (meses_periodo * 4.348) if meses_periodo else 0.0,
        "bruto_mes": bruto / meses_periodo if meses_periodo else 0.0,
        "horas_mes_activo": horas / len(meses_activos) if meses_activos else 0.0,
        "bruto_mes_activo": bruto / len(meses_activos) if meses_activos else 0.0,
    }


def por_periodo(filas: list[dict], incluidas: set, periodo: str, dimension: str,
                tarifa: float | None = None) -> list[dict]:
    """Filas largas (Período, dimensión, Horas, Valor) para gráficos, ordenadas por período."""
    campo = DIMENSIONES[dimension]
    acum: dict[tuple, dict] = {}
    for f in filas:
        if f["id"] not in incluidas:
            continue
        orden, nombre = clave_periodo(f["fecha"], periodo)
        k = (orden, texto_dim(f, campo))
        a = acum.setdefault(k, {"orden": orden, "Período": nombre, dimension: k[1], "Horas": 0.0, "Valor": 0.0})
        a["Horas"] += float(f["horas"])
        a["Valor"] += valor_fila(f, tarifa)
    return [acum[k] for k in sorted(acum)]


def tabla_cruzada(filas: list[dict], incluidas: set, periodo: str, dimension: str,
                  tarifa: float | None = None) -> tuple[list[str], list[dict]]:
    """Períodos en filas × valores de la dimensión en columnas (horas), más Total y Valor."""
    largas = por_periodo(filas, incluidas, periodo, dimension, tarifa)
    columnas = sorted({x[dimension] for x in largas}, key=lambda c: (c == SIN_DATO, c))
    salida: dict[str, dict] = {}
    for x in largas:
        r = salida.setdefault(x["orden"], {"Período": x["Período"], **{c: 0.0 for c in columnas},
                                           "Total horas": 0.0, "Valor": 0.0})
        r[x[dimension]] += x["Horas"]
        r["Total horas"] += x["Horas"]
        r["Valor"] += x["Valor"]
    return columnas, [salida[k] for k in sorted(salida)]


def estadistica(filas: list[dict], incluidas: set, dimension: str, tarifa: float | None = None) -> list[dict]:
    """Cuánto toma cada tipo de tarea: n.º de registros, total, promedio, mediana y máximo."""
    campo = DIMENSIONES[dimension]
    grupos: dict[str, list[dict]] = {}
    for f in filas:
        if f["id"] in incluidas:
            grupos.setdefault(texto_dim(f, campo), []).append(f)
    total = sum(float(f["horas"]) for g in grupos.values() for f in g) or 1.0
    salida = []
    for nombre, g in grupos.items():
        hs = [float(f["horas"]) for f in g]
        salida.append({
            dimension: nombre, "Registros": len(g), "Días": len({f["fecha"] for f in g}),
            "Horas": sum(hs), "Promedio por registro": sum(hs) / len(hs), "Mediana": median(hs),
            "Máximo": max(hs), "% del total": 100 * sum(hs) / total,
            "Valor": sum(valor_fila(f, tarifa) for f in g),
        })
    return sorted(salida, key=lambda r: -r["Horas"])


def incluidas_por_filtros(filas: list[dict], fuera: dict[str, set], manual: dict | None = None) -> set:
    """Ids que entran: todo menos lo que cae en un filtro "dejar fuera"; luego las marcas a mano mandan.

    fuera = {"etiqueta": {...}, "carrera": {...}, ...} con valores de texto (SIN_DATO para vacíos).
    manual = {id: True/False} con lo que se marcó o desmarcó fila por fila."""
    manual = manual or {}
    dentro = set()
    for f in filas:
        excluida = any(texto_dim(f, campo) in valores for campo, valores in fuera.items() if valores)
        incluir = manual.get(f["id"], not excluida)
        if incluir:
            dentro.add(f["id"])
    return dentro


def excluida_por_defecto(etiqueta: str) -> bool:
    """Etiquetas que por defecto NO entran al sueldo: B (coordinación pagada en la boleta) y X (no cobrar)."""
    e = (etiqueta or "").strip().upper()
    return e.startswith("B ·") or e.startswith("B -") or e.startswith("X ·") or e.startswith("X -")
