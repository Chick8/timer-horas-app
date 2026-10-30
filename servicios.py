"""Lógica de la app: une la base de datos (repositorio) con el motor de cálculo.

Aquí no hay pantallas: app.py llama a estas funciones. Así se pueden probar solas.
Todas reciben `conn`, una conexión abierta dentro de una transacción.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from basedatos import datos_iniciales, repositorio as repo
from motor import (
    APROBADA, BASE_MARGEN, BASES_REPARTO, DESCRIPCION_ESTADO, ESTADOS_EVENTO, ESTADOS_QUE_PAGAN,
    MAX_HORAS_DIA, PENDIENTE, RECHAZADA, ROLES, Actividad, Categoria, Evento, Gasto, Integrante,
    Persona, ReglasReparto, calcular_reparto, rango_mes, sueldos_del_mes, tarifa_aplicable,
    totales_por, validar_actividad, validar_reglas,
)
from motor import consolidado as cons
from motor.factura_pdf import leer_factura
from seguridad import hash_secreto, pin_valido, verificar_secreto

ZONA = ZoneInfo("America/Santiago")
MAX_INTENTOS_PIN = 5
MINUTOS_BLOQUEO = 15
PATRON_CODIGO = re.compile(r"^t\d{3}$")


# ------------------------------------------------------------------ conversiones
def ahora() -> datetime:
    return datetime.now(ZONA)


def hoy() -> date:
    return ahora().date()


def _fecha(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _momento(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=ZONA)
    d = datetime.fromisoformat(str(v))
    return d if d.tzinfo else d.replace(tzinfo=ZONA)


def _num(v) -> float:
    return float(v or 0)


def _a_persona(f: dict) -> Persona:
    return Persona(codigo=f["codigo"], nombre=(f["nombre"] or "").strip(), cargo=f.get("cargo") or "",
                   tarifa_hora=_num(f["tarifa_hora"]), activo=bool(f["activo"]))


def _a_categoria(f: dict) -> Categoria:
    especial = f.get("tarifa_hora_especial")
    return Categoria(id=int(f["id"]), nombre=f["nombre"], grupo=f.get("grupo") or "",
                     pagable_por_hora=bool(f["pagable_por_hora"]),
                     tarifa_hora_especial=float(especial) if especial not in (None, 0) else None)


def _a_actividad(f: dict) -> Actividad:
    return Actividad(codigo=f["codigo"], fecha=_fecha(f["fecha"]), categoria_id=int(f["categoria_id"]),
                     horas=_num(f["horas"]), descripcion=f.get("descripcion") or "",
                     producto_id=int(f["producto_id"]) if f.get("producto_id") is not None else None,
                     evento_id=int(f["evento_id"]) if f.get("evento_id") is not None else None,
                     cliente=f.get("cliente") or "", estado=f["estado"], id=int(f["id"]))


# ------------------------------------------------------------------ primera vez
def preparar_base(conn) -> None:
    """Si la base está vacía, carga configuración, categorías y productos iniciales."""
    repo.actualizar_estructura(conn)
    if repo.contar(conn, "configuracion") == 0:
        repo.crear_configuracion(conn, datos_iniciales.NOMBRE_EMPRESA)
    if repo.contar(conn, "categorias") == 0:
        for i, (nombre, grupo, pagable) in enumerate(datos_iniciales.CATEGORIAS):
            repo.crear_categoria(conn, nombre, grupo, pagable, None, orden=i)
    if repo.contar(conn, "productos") == 0:
        for i, nombre in enumerate(datos_iniciales.PRODUCTOS):
            repo.crear_producto(conn, nombre, orden=i)
    if repo.contar(conn, "funciones") == 0:
        for i, (nombre, nivel) in enumerate(datos_iniciales.FUNCIONES):
            repo.crear_funcion(conn, nombre, nivel, orden=i)


def configuracion(conn) -> dict:
    c = repo.configuracion(conn) or {}
    return {
        "nombre_empresa": c.get("nombre_empresa") or "TIMER",
        "pct_retencion": _num(c.get("pct_retencion")),
        "base_reparto": c.get("base_reparto") or BASE_MARGEN,
        "pct_empresa": _num(c.get("pct_empresa")),
        "pct_director": _num(c.get("pct_director")),
        "pct_equipo": _num(c.get("pct_equipo")),
        "razon_social": c.get("razon_social") or "Grupo Tecnológico Alameda SpA",
        "rut_empresa": c.get("rut_empresa") or "76.415.603-K",
        "direccion_empresa": c.get("direccion_empresa") or "",
        "email_finanzas": c.get("email_finanzas") or "",
        "dias_pago": int(c.get("dias_pago") or 5),
        "factor_nivel1": _num(c.get("factor_nivel1")) if c.get("factor_nivel1") is not None else 1.5,
        "factor_nivel2": _num(c.get("factor_nivel2")) if c.get("factor_nivel2") is not None else 1.0,
        "factor_nivel3": _num(c.get("factor_nivel3")) if c.get("factor_nivel3") is not None else 0.7,
    }


def guardar_configuracion(conn, datos: dict) -> tuple[bool, str]:
    reglas = ReglasReparto(base=datos.get("base_reparto", BASE_MARGEN), pct_empresa=_num(datos.get("pct_empresa")),
                           pct_director=_num(datos.get("pct_director")), pct_equipo=_num(datos.get("pct_equipo")))
    ok, msg = validar_reglas(reglas)
    if not ok:
        return False, msg
    ret = _num(datos.get("pct_retencion"))
    if not 0 <= ret <= 100:
        return False, "La retención debe estar entre 0 y 100 %."
    repo.guardar_configuracion(conn, **datos)
    return True, "Configuración guardada. Las carreras NUEVAS usarán estos porcentajes."


# ------------------------------------------------------------------ personas
def personas(conn) -> dict[str, Persona]:
    return {f["codigo"]: _a_persona(f) for f in repo.personas(conn)}


def lista_personas(conn) -> list[dict]:
    return repo.personas(conn)


def personas_para_ingresar(conn) -> list[tuple[str, str]]:
    filas = [f for f in repo.personas(conn) if f["activo"] and f["tiene_pin"]]
    return sorted(((f["codigo"], f["nombre"].strip()) for f in filas), key=lambda x: x[1].lower())


def login_persona(conn, codigo: str, pin: str) -> tuple[bool, str]:
    f = repo.persona_para_login(conn, codigo)
    if f is None or not f["activo"]:
        return False, "Usuario no encontrado o desactivado. Habla con la administración."
    bloqueo = _momento(f.get("bloqueado_hasta"))
    if bloqueo and bloqueo > ahora():
        return False, (f"Demasiados intentos con PIN incorrecto. Prueba de nuevo después de las "
                       f"{bloqueo.astimezone(ZONA):%H:%M}.")
    if not f["pin_hash"]:
        return False, "Todavía no tienes PIN. Pídelo a la administración."
    if verificar_secreto(pin or "", f["pin_hash"]):
        if f["intentos_fallidos"]:
            repo.guardar_intentos(conn, codigo, 0, None)
        return True, "OK"
    intentos = int(f["intentos_fallidos"] or 0) + 1
    if intentos >= MAX_INTENTOS_PIN:
        hasta = (ahora() + timedelta(minutes=MINUTOS_BLOQUEO)).isoformat()
        repo.guardar_intentos(conn, codigo, 0, hasta)
        return False, (f"PIN incorrecto. Por seguridad tu usuario quedó bloqueado {MINUTOS_BLOQUEO} minutos.")
    repo.guardar_intentos(conn, codigo, intentos, None)
    return False, f"PIN incorrecto. Te quedan {MAX_INTENTOS_PIN - intentos} intento(s)."


def asignar_pin(conn, codigo: str, pin: str, confirmacion: str) -> tuple[bool, str]:
    if pin != confirmacion:
        return False, "Los dos PIN no coinciden."
    ok, msg = pin_valido(pin)
    if not ok:
        return False, msg
    if not repo.guardar_pin(conn, codigo, hash_secreto(pin)):
        return False, "No se encontró esa persona."
    return True, "PIN guardado. Entrégaselo en persona o por mensaje privado."


def siguiente_codigo(conn) -> str:
    numeros = [int(f["codigo"][1:]) for f in repo.personas(conn) if PATRON_CODIGO.match(f["codigo"])]
    return f"t{(max(numeros) + 1) if numeros else 1:03d}"


def guardar_persona(conn, datos: dict, nueva: bool) -> tuple[bool, str]:
    codigo = (datos.get("codigo") or "").strip().lower()
    nombre = (datos.get("nombre") or "").strip()
    cargo = (datos.get("cargo") or "").strip()
    try:
        tarifa = float(datos.get("tarifa_hora") or 0)
    except (TypeError, ValueError):
        return False, "La tarifa debe ser un número."
    if not nombre:
        return False, "Falta el nombre."
    if tarifa < 0:
        return False, "La tarifa no puede ser negativa."
    if nueva:
        if not PATRON_CODIGO.match(codigo):
            return False, "El código debe ser una t y 3 números (ej. t004)."
        if codigo in {f["codigo"] for f in repo.personas(conn)}:
            return False, f"El código {codigo} ya existe."
        repo.crear_persona(conn, codigo, nombre, cargo, tarifa)
        return True, f"{nombre} quedó creado con código {codigo}. Ahora asígnale un PIN."
    if not repo.actualizar_persona(conn, codigo, nombre, cargo, tarifa, bool(datos.get("activo", True))):
        return False, "No se encontró esa persona."
    return True, f"Datos de {nombre} actualizados."


# ------------------------------------------------------------------ categorías y productos
def categorias(conn, solo_activas: bool = False) -> dict[int, Categoria]:
    return {int(f["id"]): _a_categoria(f) for f in repo.categorias(conn) if f["activo"] or not solo_activas}


def lista_categorias(conn) -> list[dict]:
    return repo.categorias(conn)


def productos(conn, solo_activos: bool = False) -> dict[int, str]:
    return {int(f["id"]): f["nombre"] for f in repo.productos(conn) if f["activo"] or not solo_activos}


def lista_productos(conn) -> list[dict]:
    return repo.productos(conn)


def guardar_categoria(conn, datos: dict, id_: int | None = None) -> tuple[bool, str]:
    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        return False, "Falta el nombre de la categoría."
    otras = {f["nombre"].lower() for f in repo.categorias(conn) if id_ is None or int(f["id"]) != id_}
    if nombre.lower() in otras:
        return False, "Ya existe una categoría con ese nombre."
    especial = _num(datos.get("tarifa_hora_especial")) or None
    if id_ is None:
        repo.crear_categoria(conn, nombre, (datos.get("grupo") or "").strip(),
                             bool(datos.get("pagable_por_hora", True)), especial, orden=100)
        return True, f"Categoría «{nombre}» creada."
    repo.actualizar_categoria(conn, id_, nombre, (datos.get("grupo") or "").strip(),
                              bool(datos.get("pagable_por_hora", True)), especial, bool(datos.get("activo", True)))
    return True, f"Categoría «{nombre}» actualizada."


def guardar_producto(conn, nombre: str, id_: int | None = None, activo: bool = True) -> tuple[bool, str]:
    nombre = (nombre or "").strip()
    if not nombre:
        return False, "Falta el nombre."
    otros = {f["nombre"].lower() for f in repo.productos(conn) if id_ is None or int(f["id"]) != id_}
    if nombre.lower() in otros:
        return False, "Ya existe un producto con ese nombre."
    if id_ is None:
        repo.crear_producto(conn, nombre, orden=100)
        return True, f"Producto «{nombre}» creado."
    repo.actualizar_producto(conn, id_, nombre, activo)
    return True, f"Producto «{nombre}» actualizado."


# ------------------------------------------------------------------ jornadas (el "carrito")
def actividades_de_dia(conn, codigo: str, dia: date) -> list[Actividad]:
    filas = repo.actividades_entre(conn, dia.isoformat(), (dia + timedelta(days=1)).isoformat(), codigo)
    return [_a_actividad(f) for f in filas]


def horas_por_dia(conn, codigo: str | None, anio: int, mes: int) -> dict[date, float]:
    desde, hasta = rango_mes(anio, mes)
    tot: dict[date, float] = {}
    for f in repo.actividades_entre(conn, desde.isoformat(), hasta.isoformat(), codigo):
        if f["estado"] == RECHAZADA:
            continue
        d = _fecha(f["fecha"])
        tot[d] = tot.get(d, 0.0) + _num(f["horas"])
    return tot


def guardar_jornada(conn, codigo: str, dia: date, items: list[dict], creado_por: str = "persona") -> tuple[bool, str]:
    """Guarda todas las actividades del carrito juntas (si una está mal, no se guarda ninguna)."""
    if not items:
        return False, "El carrito está vacío: agrega al menos una actividad."
    if dia > hoy() + timedelta(days=1):
        return False, "No se pueden cargar horas de días futuros."
    cats = categorias(conn)
    cargadas = sum(a.horas for a in actividades_de_dia(conn, codigo, dia))
    acumulado = cargadas
    for n, it in enumerate(items, start=1):
        if int(it["categoria_id"]) not in cats:
            return False, f"Actividad {n}: categoría no válida."
        ok, msg = validar_actividad(float(it["horas"]), it.get("descripcion", ""), acumulado)
        if not ok:
            return False, f"Actividad {n}: {msg}"
        acumulado += float(it["horas"])
    for it in items:
        repo.insertar_actividad(conn, {
            "codigo": codigo, "fecha": dia.isoformat(), "categoria_id": int(it["categoria_id"]),
            "producto_id": it.get("producto_id"), "evento_id": it.get("evento_id"),
            "cliente": (it.get("cliente") or "").strip(), "descripcion": it["descripcion"].strip(),
            "horas": round(float(it["horas"]), 2), "hora_inicio": it.get("hora_inicio"),
            "hora_fin": it.get("hora_fin"),
        }, creado_por)
    total = sum(float(i["horas"]) for i in items)
    return True, f"Jornada guardada: {len(items)} actividad(es), {total:g} h. Quedan por revisar."


def anular_mi_actividad(conn, id_: int, codigo: str) -> tuple[bool, str]:
    f = repo.actividad(conn, id_)
    if f is None or f["codigo"] != codigo or f["anulada"]:
        return False, "No se encontró esa actividad."
    if f["estado"] != PENDIENTE:
        return False, "Esa actividad ya fue revisada: pide a administración que la corrija."
    repo.anular_actividad(conn, id_)
    return True, "Actividad eliminada."


def anular_actividad_admin(conn, id_: int) -> tuple[bool, str]:
    if repo.actividad(conn, id_) is None:
        return False, "No se encontró esa actividad."
    repo.anular_actividad(conn, id_)
    return True, "Actividad anulada (queda en el historial)."


def revisar(conn, ids: list[int], estado: str, por: str, motivo: str = "") -> tuple[bool, str]:
    if estado not in (APROBADA, RECHAZADA, PENDIENTE):
        return False, "Estado inválido."
    if estado == RECHAZADA and not motivo.strip():
        return False, "Para rechazar escribe el motivo (la persona lo verá)."
    if not ids:
        return False, "No elegiste ninguna actividad."
    for i in ids:
        repo.revisar_actividad(conn, int(i), estado, motivo.strip(), por, ahora().isoformat())
    return True, f"{len(ids)} actividad(es) marcadas como «{DESCRIPCION_ESTADO[estado]}»."


# ------------------------------------------------------------------ tablas de actividades
def _tabla_actividades(conn, filas: list[dict]) -> list[dict]:
    pers = personas(conn)
    cats = categorias(conn)
    prods = productos(conn)
    evs = {int(e["id"]): e["nombre"] for e in repo.eventos(conn)}
    salida = []
    for f in filas:
        a = _a_actividad(f)
        cat = cats.get(a.categoria_id)
        tarifa = tarifa_aplicable(pers.get(a.codigo), cat)
        pagable = cat.pagable_por_hora if cat else True
        salida.append({
            "id": a.id,
            "Fecha": a.fecha,
            "Persona": pers[a.codigo].nombre if a.codigo in pers else a.codigo,
            "Categoría": cat.nombre if cat else "?",
            "Grupo": cat.grupo if cat else "",
            "Producto": prods.get(a.producto_id, "") if a.producto_id else "",
            "Carrera": evs.get(a.evento_id, "") if a.evento_id else "",
            "Cliente": a.cliente,
            "Descripción": a.descripcion,
            "Horas": a.horas,
            "Valor": round(a.horas * tarifa) if pagable else 0,
            "Se paga": "Por hora" if pagable else "Por reparto de carrera",
            "Estado": DESCRIPCION_ESTADO.get(a.estado, a.estado),
            "Motivo": f.get("motivo_revision") or "",
        })
    return salida


def tabla_por_revisar(conn) -> list[dict]:
    return _tabla_actividades(conn, repo.actividades_por_revisar(conn))


def tabla_mes(conn, anio: int, mes: int, codigo: str | None = None) -> list[dict]:
    desde, hasta = rango_mes(anio, mes)
    return _tabla_actividades(conn, repo.actividades_entre(conn, desde.isoformat(), hasta.isoformat(), codigo))


def analisis_mes(conn, anio: int, mes: int) -> dict:
    """Horas (no rechazadas) del mes agrupadas de varias formas."""
    desde, hasta = rango_mes(anio, mes)
    acts = [_a_actividad(f) for f in repo.actividades_entre(conn, desde.isoformat(), hasta.isoformat())]
    acts = [a for a in acts if a.estado != RECHAZADA]
    pers, cats, prods = personas(conn), categorias(conn), productos(conn)
    return {
        "Por persona": totales_por(acts, lambda a: pers[a.codigo].nombre if a.codigo in pers else a.codigo),
        "Por grupo": totales_por(acts, lambda a: cats[a.categoria_id].grupo if a.categoria_id in cats else "?"),
        "Por categoría": totales_por(acts, lambda a: cats[a.categoria_id].nombre if a.categoria_id in cats else "?"),
        "Por producto": totales_por(acts, lambda a: prods.get(a.producto_id, "Sin producto")),
        "total": sum(a.horas for a in acts),
    }


# ------------------------------------------------------------------ carreras
def _armar_eventos(conn) -> list[Evento]:
    conf = configuracion(conn)
    niveles = niveles_de_funciones(conn)
    gastos_por = {}
    for g in repo.gastos(conn):
        gastos_por.setdefault(int(g["evento_id"]), []).append(Gasto(g["tipo"], _num(g["monto"]), g["descripcion"] or ""))
    equipo_por = {}
    for i in repo.equipo(conn):
        funcion = i.get("funcion") or ""
        equipo_por.setdefault(int(i["evento_id"]), []).append(Integrante(
            i["codigo"], i["rol"], _num(i["peso"]), factor=factor_de(conf, niveles, funcion, i.get("factor")),
            funcion=funcion, factor_manual=_num(i["factor"]) if i.get("factor") is not None else None))
    salida = []
    for e in repo.eventos(conn):
        eid = int(e["id"])
        salida.append(Evento(
            id=eid, nombre=e["nombre"], fecha=_fecha(e["fecha"]), venta_neta=_num(e["venta_neta"]),
            estado=e["estado"], cliente=e["cliente"] or "",
            tasa_iva=_num(e["tasa_iva"]) if e.get("tasa_iva") is not None else 19.0,
            honorarios_aprobados=bool(e.get("honorarios_aprobados")),
            producto_id=int(e["producto_id"]) if e.get("producto_id") is not None else None,
            reglas=ReglasReparto(base=e["base_reparto"], pct_empresa=_num(e["pct_empresa"]),
                                 pct_director=_num(e["pct_director"]), pct_equipo=_num(e["pct_equipo"])),
            gastos=gastos_por.get(eid, []), equipo=equipo_por.get(eid, []),
        ))
    return salida


def eventos(conn) -> list[Evento]:
    return _armar_eventos(conn)


def datos_extra_evento(conn, id_: int) -> dict:
    e = repo.evento(conn, id_) or {}
    return {"hubspot_deal": e.get("hubspot_deal") or "", "notas": e.get("notas") or ""}


def guardar_evento(conn, id_: int | None, datos: dict, gastos: list[dict], equipo: list[dict]) -> tuple[bool, str, int | None]:
    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        return False, "Falta el nombre de la carrera.", None
    if datos.get("estado") not in ESTADOS_EVENTO:
        return False, "Estado inválido.", None
    if datos.get("base_reparto") not in BASES_REPARTO:
        return False, "Base de reparto inválida.", None
    reglas = ReglasReparto(base=datos["base_reparto"], pct_empresa=_num(datos.get("pct_empresa")),
                           pct_director=_num(datos.get("pct_director")), pct_equipo=_num(datos.get("pct_equipo")))
    ok, msg = validar_reglas(reglas)
    if not ok:
        return False, msg, None
    if _num(datos.get("venta_neta")) < 0:
        return False, "La venta no puede ser negativa.", None
    tasa_iva = _num(datos.get("tasa_iva", 19))
    if not 0 <= tasa_iva <= 100:
        return False, "Tasa de IVA inválida.", None
    if any(_num(g.get("monto")) < 0 for g in gastos):
        return False, "Los gastos no pueden ser negativos.", None
    gastos = [g for g in gastos if _num(g.get("monto")) > 0]
    pers = personas(conn)
    equipo = [i for i in equipo if i.get("codigo")]
    for i in equipo:
        if i["codigo"] not in pers:
            return False, f"Persona desconocida en el equipo: {i['codigo']}", None
        if i.get("rol") not in ROLES:
            return False, "Rol inválido en el equipo.", None
        if _num(i.get("peso")) < 0:
            return False, "Las jornadas no pueden ser negativas.", None
        if i.get("factor") is not None and not 0 <= _num(i.get("factor")) <= 10:
            return False, "La ponderación debe estar entre 0 y 10.", None
    fila = {
        "nombre": nombre, "fecha": datos["fecha"].isoformat() if datos.get("fecha") else None,
        "cliente": (datos.get("cliente") or "").strip(), "producto_id": datos.get("producto_id"),
        "estado": datos["estado"], "venta_neta": round(_num(datos.get("venta_neta"))),
        "tasa_iva": tasa_iva,
        "base_reparto": reglas.base, "pct_empresa": reglas.pct_empresa, "pct_director": reglas.pct_director,
        "pct_equipo": reglas.pct_equipo, "hubspot_deal": (datos.get("hubspot_deal") or "").strip(),
        "notas": (datos.get("notas") or "").strip(),
    }
    if id_ is None:
        id_ = repo.crear_evento(conn, fila)
        texto = f"Carrera «{nombre}» creada."
    else:
        antes = next((e for e in _armar_eventos(conn) if e.id == id_), None)
        repo.actualizar_evento(conn, id_, fila)
        texto = f"Carrera «{nombre}» guardada."
    repo.reemplazar_gastos(conn, id_, [{"tipo": g["tipo"], "descripcion": g.get("descripcion", ""),
                                        "monto": round(_num(g["monto"]))} for g in gastos])
    repo.reemplazar_equipo(conn, id_, [{"codigo": i["codigo"], "rol": i["rol"], "peso": _num(i.get("peso", 1)),
                                        "funcion": (i.get("funcion") or "").strip(),
                                        "factor": _num(i["factor"]) if i.get("factor") is not None else None}
                                       for i in equipo])
    if texto.endswith("guardada."):
        despues = next((e for e in _armar_eventos(conn) if e.id == id_), None)
        if antes is not None and antes.honorarios_aprobados and despues is not None:
            if _firma_reparto(antes) != _firma_reparto(despues):
                repo.aprobar_honorarios(conn, id_, False, None, None)
                texto += " Como cambió el reparto, los honorarios vuelven a quedar por aprobar."
    return True, texto, id_


def _firma_reparto(ev: Evento) -> list:
    """Lo que le toca a cada uno: si cambia, la aprobación de honorarios deja de valer."""
    if ev.estado not in ESTADOS_QUE_PAGAN:
        return []
    return sorted((p.codigo, p.rol, round(p.monto)) for p in calcular_reparto(ev).pagos)


def resumen_evento(conn, ev: Evento) -> dict:
    """Reparto + costo de las horas internas que se cargaron a esta carrera."""
    res = calcular_reparto(ev)
    pers, cats = personas(conn), categorias(conn)
    horas_internas = 0.0
    costo_internas = 0.0
    if ev.id is not None:
        for f in repo.actividades_de_evento(conn, ev.id):
            a = _a_actividad(f)
            if a.estado == RECHAZADA:
                continue
            horas_internas += a.horas
            cat = cats.get(a.categoria_id)
            if cat is None or cat.pagable_por_hora:
                costo_internas += a.horas * tarifa_aplicable(pers.get(a.codigo), cat)
    return {
        "reparto": res,
        "horas_internas": horas_internas,
        "costo_horas_internas": round(costo_internas),
        "resultado_final_empresa": res.monto_empresa - round(costo_internas),
        "nombres": {c: p.nombre for c, p in pers.items()},
    }


# ------------------------------------------------------------------ sueldos
def sueldos_mes(conn, anio: int, mes: int, pct_retencion: float | None = None):
    desde, hasta = rango_mes(anio, mes)
    acts = [_a_actividad(f) for f in repo.actividades_entre(conn, desde.isoformat(), hasta.isoformat())]
    evs = [e for e in _armar_eventos(conn) if e.fecha and desde <= e.fecha < hasta]
    if pct_retencion is None:
        pct_retencion = configuracion(conn)["pct_retencion"]
    return sueldos_del_mes(personas(conn), categorias(conn), acts, evs, pct_retencion)


def carreras_pendientes_del_mes(conn, anio: int, mes: int) -> list[Evento]:
    """Carreras del mes que todavía no están realizadas (no entran al sueldo)."""
    desde, hasta = rango_mes(anio, mes)
    return [e for e in _armar_eventos(conn)
            if e.fecha and desde <= e.fecha < hasta and e.estado not in ESTADOS_QUE_PAGAN and e.estado != "perdido"]


def filas_sueldo_tabla(filas) -> list[dict]:
    return [{
        "Código": f.codigo, "Nombre": f.nombre, "Tarifa/h": f.tarifa_hora,
        "Horas aprobadas": round(f.horas_aprobadas, 2), "Pago horas": f.monto_horas,
        "Pago carreras": f.monto_carreras, "Total bruto": f.total_bruto, "Retención": f.retencion,
        "Total líquido": f.total_liquido, "Horas por revisar": round(f.horas_pendientes, 2),
        "Monto por revisar": f.monto_pendiente, "Horas en carrera": round(f.horas_evento, 2),
    } for f in filas]


def a_csv(filas: list[dict], titulo: str = "") -> bytes:
    """CSV que Excel abre bien (separador ; y acentos correctos)."""
    salida = io.StringIO()
    esc = csv.writer(salida, delimiter=";")
    if titulo:
        esc.writerow([titulo])
    if filas:
        claves = [k for k in filas[0].keys() if k != "id"]
        esc.writerow(claves)
        for f in filas:
            fila = []
            for k in claves:
                v = f[k]
                if isinstance(v, float):
                    v = f"{v:g}".replace(".", ",")
                elif isinstance(v, date):
                    v = v.strftime("%d-%m-%Y")
                fila.append(v)
            esc.writerow(fila)
    return salida.getvalue().encode("utf-8-sig")


MAX_HORAS = MAX_HORAS_DIA


# ------------------------------------------------------------------ facturas y cobranza
def leer_pdf_factura(contenido: bytes) -> dict:
    """Lee el PDF de una factura (no guarda nada)."""
    return leer_factura(contenido)


def guardar_factura(conn, datos: dict, evento_id: int | None, pct_del_total: float,
                    nombre_evento: str = "", archivo: bytes | None = None,
                    archivo_nombre: str | None = None) -> tuple[bool, str, int | None]:
    """Guarda una factura. Si evento_id es None, crea la carrera con esa factura.

    pct_del_total: qué parte del valor total de la carrera es esta factura (100 = todo, 50 = anticipo...).
    Con eso se calcula el valor total (neto) de la carrera cuando todavía no está definido."""
    neto = round(_num(datos.get("neto")))
    iva = round(_num(datos.get("iva")))
    total = round(_num(datos.get("total"))) or neto + iva
    numero = str(datos.get("numero") or "").strip()
    if neto <= 0:
        return False, "El monto neto de la factura debe ser mayor que 0.", None
    if not 0 < pct_del_total <= 100:
        return False, "El porcentaje de la factura debe estar entre 1 y 100 %.", None
    if numero and repo.factura_por_numero(conn, numero):
        return False, f"La factura N° {numero} ya está registrada.", None
    tasa_iva = 19.0 if iva else 0.0
    valor_carrera = round(neto * 100 / pct_del_total)
    fecha = datos.get("fecha")

    if evento_id is None:
        nombre = (nombre_evento or "").strip() or (datos.get("descripcion") or "").strip()[:80] or f"Factura {numero}"
        conf = configuracion(conn)
        ok, msg, evento_id = guardar_evento(conn, None, {
            "nombre": nombre, "fecha": fecha, "cliente": datos.get("cliente", ""), "estado": "confirmado",
            "venta_neta": valor_carrera, "tasa_iva": tasa_iva, "base_reparto": conf["base_reparto"],
            "pct_empresa": conf["pct_empresa"], "pct_director": conf["pct_director"], "pct_equipo": conf["pct_equipo"],
            "notas": f"Creada desde la factura N° {numero}." if numero else "",
        }, [], [])
        if not ok:
            return False, msg, None
        texto = f"Carrera «{nombre}» creada con valor neto {_pesos(valor_carrera)}"
    else:
        ev = repo.evento(conn, evento_id)
        if ev is None:
            return False, "No se encontró la carrera.", None
        if _num(ev["venta_neta"]) == 0:
            repo.fijar_venta_evento(conn, evento_id, valor_carrera, tasa_iva)
            texto = f"Factura agregada; valor de la carrera fijado en {_pesos(valor_carrera)} neto"
        else:
            texto = "Factura agregada a la carrera"
    repo.insertar_factura(conn, {
        "evento_id": evento_id, "numero": numero, "fecha": fecha.isoformat() if fecha else None,
        "cliente": (datos.get("cliente") or "").strip(), "rut_cliente": (datos.get("rut_cliente") or "").strip(),
        "descripcion": (datos.get("descripcion") or "").strip(), "neto": neto, "iva": iva, "total": total,
        "pagada": bool(datos.get("pagada", False)),
        "fecha_pago": datos["fecha_pago"].isoformat() if datos.get("fecha_pago") else None,
        "archivo_nombre": archivo_nombre, "archivo": archivo,
    })
    return True, texto + (f" (factura N° {numero})." if numero else "."), evento_id


def _pesos(m: float) -> str:
    return f"${round(m):,}".replace(",", ".")


def cobranza(conn, ev: Evento) -> dict:
    """Cuánto de la carrera ya se facturó y cuánto ya pagó el cliente (montos netos)."""
    filas = repo.facturas(conn, ev.id) if ev.id is not None else []
    contrato = float(ev.venta_neta or 0)
    facturado = sum(_num(f["neto"]) for f in filas)
    pagado = sum(_num(f["neto"]) for f in filas if f["pagada"])
    pct = (lambda x: x / contrato * 100 if contrato else 0.0)
    detalle = [{
        "id": int(f["id"]), "N°": f["numero"], "Fecha": _fecha(f["fecha"]), "Neto": _num(f["neto"]),
        "IVA": _num(f["iva"]), "Total": _num(f["total"]), "% de la carrera": round(pct(_num(f["neto"])), 1),
        "Pagada": bool(f["pagada"]), "Fecha de pago": _fecha(f["fecha_pago"]), "PDF": bool(f["archivo_nombre"]),
    } for f in filas]
    avisos = []
    if contrato and facturado > contrato + 1:
        avisos.append(f"Se facturó más que el valor de la carrera ({pct(facturado):.0f} %). Revisa el valor neto.")
    return {"contrato": contrato, "facturado": facturado, "pagado": pagado, "por_facturar": max(contrato - facturado, 0),
            "por_cobrar": facturado - pagado, "pct_facturado": pct(facturado), "pct_pagado": pct(pagado),
            "facturas": detalle, "avisos": avisos}


def marcar_pago_factura(conn, id_: int, pagada: bool, fecha_pago: date | None) -> tuple[bool, str]:
    repo.marcar_pago_factura(conn, id_, pagada, (fecha_pago or hoy()).isoformat() if pagada else None)
    return True, "Pago registrado." if pagada else "Factura marcada como no pagada."


def anular_factura(conn, id_: int) -> tuple[bool, str]:
    repo.anular_factura(conn, id_)
    return True, "Factura quitada de la carrera (queda en el historial)."


def archivo_factura(conn, id_: int) -> tuple[bytes, str] | None:
    f = repo.archivo_factura(conn, id_)
    if not f or f["archivo"] is None:
        return None
    return bytes(f["archivo"]), f["archivo_nombre"] or f"factura_{id_}.pdf"


# ------------------------------------------------------------------ carga rápida de muchos días
def _categoria_por_texto(cats: dict, texto: str) -> int | None:
    """Encuentra la categoría por su nombre (o 'Grupo · Nombre'), sin importar mayúsculas."""
    t = (texto or "").strip().lower()
    if not t:
        return None
    for i, c in cats.items():
        if t in (c.nombre.lower(), f"{c.grupo} · {c.nombre}".lower()):
            return i
    for i, c in cats.items():   # coincidencia parcial: "soldadura" -> "Soldadura y reparación electrónica"
        if t in c.nombre.lower():
            return i
    return None


def guardar_lote(conn, codigo: str, filas: list[dict], creado_por: str = "persona") -> tuple[bool, str, list[str]]:
    """Guarda muchas actividades de distintos días de una vez (todo o nada).

    Cada fila: fecha (date), tipo (texto o id de categoría), descripcion, horas, y opcional evento_id, cliente.
    Devuelve (ok, mensaje, lista de errores por fila)."""
    cats = categorias(conn)
    errores, limpias = [], []
    for n, f in enumerate(filas, start=1):
        fecha = _fecha(f.get("fecha"))
        cat = f.get("categoria_id") or _categoria_por_texto(cats, str(f.get("tipo") or ""))
        try:
            horas = float(f.get("horas") or 0)
        except (TypeError, ValueError):
            horas = 0
        desc = str(f.get("descripcion") or "").strip()
        if fecha is None:
            errores.append(f"Fila {n}: falta la fecha.")
            continue
        if fecha > hoy():
            errores.append(f"Fila {n}: la fecha {fecha:%d-%m-%Y} es futura.")
            continue
        if cat is None:
            errores.append(f"Fila {n}: no reconozco el tipo de actividad «{f.get('tipo') or ''}».")
            continue
        ok, msg = validar_actividad(horas, desc, 0)
        if not ok:
            errores.append(f"Fila {n}: {msg}")
            continue
        limpias.append({"fecha": fecha, "categoria_id": int(cat), "horas": round(horas, 2), "descripcion": desc,
                        "evento_id": f.get("evento_id"), "cliente": str(f.get("cliente") or "").strip(),
                        "producto_id": f.get("producto_id"), "etiqueta": str(f.get("etiqueta") or "").strip(),
                        "carrera_texto": str(f.get("carrera_texto") or "").strip()})
    # Filas que ya estaban guardadas (mismo día, descripción y horas): no se duplican,
    # solo se les completa la etiqueta / carrera si les faltaba. Así se puede volver a subir el mismo Excel.
    repetidas, nuevas = [], []
    vistas: dict[str, list[dict]] = {}
    for f in limpias:
        dia = f["fecha"].isoformat()
        if dia not in vistas:
            vistas[dia] = repo.actividades_de_dia_persona(conn, codigo, dia)
        igual = next((x for x in vistas[dia] if _normal(x["descripcion"]) == _normal(f["descripcion"])
                      and abs(_num(x["horas"]) - f["horas"]) < 0.001), None)
        if igual is not None:
            vistas[dia] = [x for x in vistas[dia] if x is not igual]
            repetidas.append((int(igual["id"]), f))
        else:
            nuevas.append(f)
    limpias = nuevas
    # Máximo de horas por día, sumando lo que ya estaba guardado
    por_dia: dict[date, float] = {}
    for f in limpias:
        por_dia[f["fecha"]] = por_dia.get(f["fecha"], 0.0) + f["horas"]
    for dia, h in sorted(por_dia.items()):
        ya = sum(a.horas for a in actividades_de_dia(conn, codigo, dia))
        if ya + h > MAX_HORAS_DIA:
            errores.append(f"El {dia:%d-%m-%Y} sumaría {ya + h:g} h (máximo {MAX_HORAS_DIA:g} h por día).")
    if errores:
        return False, "No se guardó nada: corrige las filas marcadas.", errores
    if not limpias and not repetidas:
        return False, "No hay filas para guardar.", []
    for id_, f in repetidas:
        repo.completar_etiqueta(conn, id_, f["etiqueta"], f["carrera_texto"])
    for f in limpias:
        repo.insertar_actividad(conn, {
            "codigo": codigo, "fecha": f["fecha"].isoformat(), "categoria_id": f["categoria_id"],
            "producto_id": f["producto_id"], "evento_id": f["evento_id"], "cliente": f["cliente"],
            "descripcion": f["descripcion"], "horas": f["horas"], "hora_inicio": None, "hora_fin": None,
            "etiqueta": f["etiqueta"], "carrera_texto": f["carrera_texto"],
        }, creado_por)
    total = sum(f["horas"] for f in limpias)
    msg = (f"Se guardaron {len(limpias)} actividades en {len(por_dia)} día(s): {total:g} h. Quedan por revisar."
           if limpias else "No había actividades nuevas.")
    if repetidas:
        msg += f" {len(repetidas)} ya estaban guardadas (no se duplicaron; se les completó la etiqueta)."
    return True, msg, []


def _normal(t) -> str:
    return " ".join(str(t or "").lower().split())


def leer_planilla(contenido: bytes, nombre: str) -> list[dict]:
    """Lee un Excel o CSV con columnas Fecha, Tipo de actividad, Descripción, Horas, Carrera, Cliente."""
    import pandas as pd
    if nombre.lower().endswith(".csv"):
        texto = contenido.decode("utf-8-sig", errors="replace")
        sep = ";" if texto.count(";") > texto.count(",") else ","
        df = pd.read_csv(io.StringIO(texto), sep=sep)
    else:
        df = pd.read_excel(io.BytesIO(contenido))
    columnas = {c: str(c).strip().lower() for c in df.columns}
    df = df.rename(columns=columnas)

    def col(*nombres):
        for n in nombres:
            if n in df.columns:
                return n
        return None
    c_fecha, c_tipo = col("fecha", "día", "dia"), col("tipo de actividad", "tipo", "categoría", "categoria")
    c_desc, c_horas = col("descripción", "descripcion", "detalle"), col("horas", "hrs", "h")
    c_carrera, c_cliente = col("carrera", "evento"), col("cliente")
    c_etiqueta = col("etiqueta", "bloque")
    filas = []
    for _, r in df.iterrows():
        if all(pd.isna(v) for v in r.values):
            continue
        fecha = pd.to_datetime(r[c_fecha], dayfirst=True, errors="coerce") if c_fecha else pd.NaT
        horas = pd.to_numeric(str(r[c_horas]).replace(",", "."), errors="coerce") if c_horas else None
        filas.append({
            "fecha": None if pd.isna(fecha) else fecha.date(),
            "tipo": "" if not c_tipo or pd.isna(r[c_tipo]) else str(r[c_tipo]),
            "descripcion": "" if not c_desc or pd.isna(r[c_desc]) else str(r[c_desc]),
            "horas": None if horas is None or pd.isna(horas) else float(horas),
            "carrera": "" if not c_carrera or pd.isna(r[c_carrera]) else str(r[c_carrera]),
            "cliente": "" if not c_cliente or pd.isna(r[c_cliente]) else str(r[c_cliente]),
            "etiqueta": "" if not c_etiqueta or pd.isna(r[c_etiqueta]) else str(r[c_etiqueta]),
        })
    return filas


def plantilla_excel(conn) -> bytes:
    """Excel de ejemplo para la carga rápida, con la lista de tipos de actividad válidos."""
    import pandas as pd
    cats = categorias(conn, True)
    ejemplo = pd.DataFrame([
        {"Fecha": "07-04-2026", "Tipo de actividad": "Reunión con cliente", "Descripción": "Reunión cotización trail",
         "Horas": 2, "Carrera": "", "Cliente": "Cliente X", "Etiqueta": ""},
        {"Fecha": "07-04-2026", "Tipo de actividad": "CRM HubSpot (gestión y métricas)",
         "Descripción": "Ordenar negocios y etapas", "Horas": 1.5, "Carrera": "", "Cliente": "", "Etiqueta": ""},
    ])
    tipos = pd.DataFrame([{"Grupo": c.grupo, "Tipo de actividad": c.nombre,
                           "Se paga": "Por hora" if c.pagable_por_hora else "Por reparto de carrera"}
                          for c in cats.values()])
    salida = io.BytesIO()
    with pd.ExcelWriter(salida, engine="openpyxl") as w:
        ejemplo.to_excel(w, sheet_name="Horas", index=False)
        tipos.to_excel(w, sheet_name="Tipos válidos", index=False)
    return salida.getvalue()


# ------------------------------------------------------------------ resumen de un período
def resumen_periodo(conn, codigo: str | None, desde: date, hasta: date) -> dict:
    """Horas y montos entre dos fechas (ambas incluidas), por mes y por categoría."""
    filas = repo.actividades_entre(conn, desde.isoformat(), (hasta + timedelta(days=1)).isoformat(), codigo)
    pers, cats = personas(conn), categorias(conn)
    por_mes: dict[tuple, dict] = {}
    por_cat: dict[str, dict] = {}
    tot = {"horas": 0.0, "aprobadas": 0.0, "pendientes": 0.0, "monto_aprobado": 0.0, "monto_pendiente": 0.0,
           "horas_carrera": 0.0, "dias": set()}
    for f in filas:
        a = _a_actividad(f)
        if a.estado == RECHAZADA:
            continue
        cat = cats.get(a.categoria_id)
        pagable = cat.pagable_por_hora if cat else True
        valor = a.horas * tarifa_aplicable(pers.get(a.codigo), cat) if pagable else 0.0
        m = por_mes.setdefault((a.fecha.year, a.fecha.month), {"horas": 0.0, "aprobadas": 0.0, "pendientes": 0.0,
                                                                "monto": 0.0, "dias": set()})
        m["horas"] += a.horas
        m["monto"] += valor
        m["dias"].add(a.fecha)
        c = por_cat.setdefault(cat.nombre if cat else "?", {"grupo": cat.grupo if cat else "", "horas": 0.0, "monto": 0.0})
        c["horas"] += a.horas
        c["monto"] += valor
        tot["horas"] += a.horas
        tot["dias"].add(a.fecha)
        if not pagable:
            tot["horas_carrera"] += a.horas
        elif a.estado == APROBADA:
            m["aprobadas"] += a.horas
            tot["aprobadas"] += a.horas
            tot["monto_aprobado"] += valor
        else:
            m["pendientes"] += a.horas
            tot["pendientes"] += a.horas
            tot["monto_pendiente"] += valor
    from motor.formato import nombre_mes
    meses = [{"Mes": nombre_mes(a, m), "Días con registro": len(v["dias"]), "Horas": round(v["horas"], 2),
              "Aprobadas": round(v["aprobadas"], 2), "Por revisar": round(v["pendientes"], 2),
              "Valor estimado": round(v["monto"])} for (a, m), v in sorted(por_mes.items())]
    categorias_ = [{"Grupo": v["grupo"], "Categoría": k, "Horas": round(v["horas"], 2), "Valor estimado": round(v["monto"])}
                   for k, v in sorted(por_cat.items(), key=lambda kv: -kv[1]["horas"])]
    tot["dias"] = len(tot["dias"])
    tot["monto_total"] = round(tot["monto_aprobado"] + tot["monto_pendiente"])
    return {"meses": meses, "categorias": categorias_, "total": tot}


# ------------------------------------------------------------------ editar y borrar
def editar_actividad(conn, id_: int, datos: dict, codigo_persona: str | None = None) -> tuple[bool, str]:
    """Corrige una actividad ya guardada. Si la edita la persona (codigo_persona), solo puede si está por revisar."""
    f = repo.actividad(conn, id_)
    if f is None or f["anulada"]:
        return False, "No se encontró esa actividad."
    if codigo_persona is not None:
        if f["codigo"] != codigo_persona:
            return False, "No se encontró esa actividad."
        if f["estado"] != PENDIENTE:
            return False, "Esa actividad ya fue revisada: pide a administración que la corrija."
    fecha = _fecha(datos.get("fecha"))
    if fecha is None or fecha > hoy():
        return False, "Fecha inválida (no puede ser futura)."
    if int(datos.get("categoria_id") or 0) not in categorias(conn):
        return False, "Tipo de actividad inválido."
    horas = float(datos.get("horas") or 0)
    otras = sum(a.horas for a in actividades_de_dia(conn, f["codigo"], fecha) if a.id != id_)
    ok, msg = validar_actividad(horas, datos.get("descripcion", ""), otras)
    if not ok:
        return False, msg
    repo.actualizar_actividad(conn, id_, {
        "fecha": fecha.isoformat(), "categoria_id": int(datos["categoria_id"]), "producto_id": datos.get("producto_id"),
        "evento_id": datos.get("evento_id"), "cliente": (datos.get("cliente") or "").strip(),
        "descripcion": datos["descripcion"].strip(), "horas": round(horas, 2),
    })
    return True, "Actividad corregida."


def eliminar_evento(conn, id_: int) -> tuple[bool, str]:
    e = repo.evento(conn, id_)
    if e is None:
        return False, "No se encontró la carrera."
    repo.borrar_evento(conn, id_)
    return True, f"Carrera «{e['nombre']}» borrada (con sus gastos, equipo y facturas). Las horas cargadas a ella se mantienen."


def borrar_datos_de_prueba(conn) -> tuple[bool, str]:
    repo.borrar_movimientos(conn)
    return True, "Listo: se borraron todas las horas, carreras y facturas. Personas, categorías y ajustes se mantienen."


def actividad_por_id(conn, id_: int):
    f = repo.actividad(conn, id_)
    return _a_actividad(f) if f and not f["anulada"] else None



# ------------------------------------------------------------------ pagos de carrera y boletas de honorarios
ESTADOS_BOLETA = {"pendiente": "Por solicitar", "solicitada": "Boleta solicitada", "recibida": "Boleta recibida",
                  "pagada": "Pagada"}


def montos_honorarios(bruto: float, pct_retencion: float) -> dict:
    """Boleta de honorarios: la persona boletea el BRUTO; TIMER retiene el % y lo paga al SII; la persona recibe el líquido."""
    bruto = round(bruto)
    retencion = round(bruto * pct_retencion / 100)
    return {"bruto": bruto, "retencion": retencion, "liquido": bruto - retencion}


def pagos_de_carrera(conn, ev: Evento) -> list[dict]:
    """Lo que le toca a cada persona en la carrera (sumando si tiene más de un rol), con el estado de su boleta."""
    res = calcular_reparto(ev)
    conf = configuracion(conn)
    pers = personas(conn)
    contactos = {f["codigo"]: f for f in repo.personas(conn)}
    bols = {b["codigo"]: b for b in repo.boletas(conn, ev.id)} if ev.id is not None else {}
    por_persona: dict[str, dict] = {}
    for p in res.pagos:
        d = por_persona.setdefault(p.codigo, {"roles": [], "jornadas": 0.0, "bruto": 0.0})
        d["roles"].append(ROLES.get(p.rol, p.rol) + (f" – {p.funcion}" if p.funcion else ""))
        d["jornadas"] += p.peso
        d["bruto"] += p.monto
    salida = []
    for codigo, d in por_persona.items():
        m = montos_honorarios(d["bruto"], conf["pct_retencion"])
        b = bols.get(codigo, {})
        salida.append({
            "codigo": codigo, "nombre": pers[codigo].nombre if codigo in pers else codigo,
            "email": (contactos.get(codigo) or {}).get("email") or "",
            "roles": " + ".join(dict.fromkeys(d["roles"])), "jornadas": d["jornadas"], **m,
            "estado": b.get("estado", "pendiente"), "numero_boleta": b.get("numero", ""),
            "tiene_pdf": bool(b.get("archivo_nombre")),
        })
    return sorted(salida, key=lambda x: x["nombre"].lower())


def mensaje_boleta(conn, ev: Evento, pago: dict) -> tuple[str, str]:
    """Asunto y texto del correo que pide la boleta de honorarios a una persona."""
    conf = configuracion(conn)
    fecha = f" ({ev.fecha:%d-%m-%Y})" if ev.fecha else ""
    nombre = pago["nombre"].split(" ")[0]
    pct = f"{conf['pct_retencion']:g}".replace(".", ",")
    asunto = f"Boleta de honorarios – {ev.nombre}{fecha}"
    cuerpo = f"""Hola {nombre}:

Gracias por tu trabajo en {ev.nombre}{fecha}. Ya está calculado y aprobado tu pago:

  • Rol: {pago['roles']} ({pago['jornadas']:g} jornada{'s' if pago['jornadas'] != 1 else ''})
  • Monto BRUTO a boletear: {_pesos(pago['bruto'])}
  • Retención {pct} % (la paga TIMER al SII): {_pesos(pago['retencion'])}
  • Líquido que recibirás: {_pesos(pago['liquido'])}

Por favor emite una boleta de honorarios electrónica en sii.cl con estos datos:
  • Receptor: {conf['razon_social']}
  • RUT: {conf['rut_empresa']}
  • Dirección: {conf['direccion_empresa']}
  • Detalle: Servicios de cronometraje – {ev.nombre}{fecha}
  • Monto bruto: {_pesos(pago['bruto'])}
  • Retención: elige «Retención del receptor» (la retiene TIMER)

Respóndenos este correo con el PDF de la boleta (o súbela en la app, pestaña «Mis honorarios»).
Te transferimos el líquido dentro de {conf['dias_pago']} días hábiles desde que recibamos la boleta.

¡Gracias!
Equipo TIMER
{conf['email_finanzas']}"""
    return asunto, cuerpo


def enlace_correo(email: str, asunto: str, cuerpo: str) -> str:
    from urllib.parse import quote
    return f"mailto:{quote(email)}?subject={quote(asunto)}&body={quote(cuerpo)}"


def cambiar_estado_boleta(conn, ev: Evento, codigo: str, estado: str, numero: str = "",
                          archivo: bytes | None = None, archivo_nombre: str | None = None,
                          codigo_persona: str | None = None) -> tuple[bool, str]:
    if estado not in ESTADOS_BOLETA:
        return False, "Estado inválido."
    pago = next((p for p in pagos_de_carrera(conn, ev) if p["codigo"] == codigo), None)
    if pago is None:
        return False, "Esa persona no está en el equipo de la carrera."
    if codigo_persona is not None and codigo_persona != codigo:
        return False, "Solo puedes subir tu propia boleta."
    if estado in ("recibida", "pagada") and not (numero or pago["numero_boleta"]):
        return False, "Escribe el N° de la boleta."
    repo.guardar_boleta(conn, ev.id, codigo, estado, numero or pago["numero_boleta"], pago["bruto"],
                        archivo_nombre, archivo)
    return True, f"{pago['nombre']}: {ESTADOS_BOLETA[estado].lower()}."


def mis_pagos(conn, codigo: str) -> list[dict]:
    """Carreras REALIZADAS o PAGADAS donde participó la persona, con su monto y estado de boleta."""
    salida = []
    for ev in _armar_eventos(conn):
        if ev.estado not in ESTADOS_QUE_PAGAN:
            continue
        p = next((x for x in pagos_de_carrera(conn, ev) if x["codigo"] == codigo), None)
        if p and p["bruto"]:
            salida.append({"evento": ev, "aprobado": ev.honorarios_aprobados, **p})
    return sorted(salida, key=lambda x: x["evento"].fecha or date.min, reverse=True)


def archivo_boleta(conn, evento_id: int, codigo: str) -> tuple[bytes, str] | None:
    f = repo.archivo_boleta(conn, evento_id, codigo)
    if not f or f["archivo"] is None:
        return None
    return bytes(f["archivo"]), f["archivo_nombre"] or "boleta.pdf"


def guardar_contacto(conn, codigo: str, email: str, telefono: str) -> tuple[bool, str]:
    email = (email or "").strip()
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return False, "Ese correo no parece válido."
    repo.guardar_contacto(conn, codigo, email, (telefono or "").strip())
    return True, "Contacto guardado."



# ------------------------------------------------------------------ funciones y ponderaciones
def niveles_de_funciones(conn) -> dict[str, int]:
    return {f["nombre"]: int(f["nivel"]) for f in repo.funciones(conn)}


def lista_funciones(conn, solo_activas: bool = False) -> list[dict]:
    return [f for f in repo.funciones(conn) if f["activo"] or not solo_activas]


def factor_de(conf: dict, niveles: dict, funcion: str, factor_manual=None) -> float:
    """Ponderación de un integrante: la escrita a mano, o la del nivel de su función, o 1 si no tiene función."""
    if factor_manual is not None and factor_manual == factor_manual:   # no es NaN
        return float(factor_manual)
    nivel = niveles.get(funcion or "")
    return float(conf.get(f"factor_nivel{nivel}", 1.0)) if nivel else 1.0


def guardar_funciones(conn, lista: list[dict], factores: dict) -> tuple[bool, str]:
    limpias, vistos = [], set()
    for f in lista:
        nombre = (f.get("nombre") or "").strip()
        if not nombre:
            continue
        if nombre.lower() in vistos:
            return False, f"La función «{nombre}» está repetida."
        nivel = int(f.get("nivel") or 2)
        if nivel not in (1, 2, 3):
            return False, f"Nivel inválido en «{nombre}» (debe ser 1, 2 o 3)."
        vistos.add(nombre.lower())
        limpias.append({"nombre": nombre, "nivel": nivel, "activo": bool(f.get("activo", True))})
    for k in ("factor_nivel1", "factor_nivel2", "factor_nivel3"):
        if not 0 < _num(factores.get(k)) <= 10:
            return False, "Las ponderaciones de nivel deben estar entre 0 y 10."
    repo.reemplazar_funciones(conn, limpias)
    repo.guardar_configuracion(conn, **{k: _num(v) for k, v in factores.items()})
    return True, "Funciones y ponderaciones guardadas. Se aplican a todas las carreras (salvo ponderaciones escritas a mano)."



# ------------------------------------------------------------------ aprobación de honorarios de carreras
def carreras_por_aprobar(conn) -> list[dict]:
    """Carreras realizadas o pagadas cuyo reparto al equipo falta aprobar."""
    salida = []
    for ev in _armar_eventos(conn):
        if ev.estado in ESTADOS_QUE_PAGAN and not ev.honorarios_aprobados:
            res = calcular_reparto(ev)
            salida.append({"evento": ev, "reparto": res, "total": res.monto_director + res.monto_equipo})
    return salida


def aprobar_honorarios_carrera(conn, id_: int, por: str, aprobar: bool = True) -> tuple[bool, str]:
    ev = next((e for e in _armar_eventos(conn) if e.id == id_), None)
    if ev is None:
        return False, "No se encontró la carrera."
    if aprobar:
        if ev.estado not in ESTADOS_QUE_PAGAN:
            return False, "Solo se aprueban honorarios de carreras «Realizado» o «Pagado»."
        res = calcular_reparto(ev)
        if res.alertas and not res.pagos:
            return False, "La carrera no tiene reparto que aprobar: " + " ".join(res.alertas)
        repo.aprobar_honorarios(conn, id_, True, por, ahora().isoformat())
        return True, f"Honorarios de «{ev.nombre}» aprobados: entran a la liquidación de {ev.fecha:%m-%Y}." if ev.fecha \
            else f"Honorarios de «{ev.nombre}» aprobados."
    repo.aprobar_honorarios(conn, id_, False, None, None)
    return True, f"Se quitó la aprobación de «{ev.nombre}»."


# ------------------------------------------------------------------ edición en tabla
def guardar_cambios_tabla(conn, cambios: list[dict], borrar: list[int], codigo_persona: str | None = None) -> tuple[bool, str, list[str]]:
    """Aplica varias correcciones y borrados de actividades. Si una falla, no se guarda ninguna."""
    errores = []
    for c in cambios:
        ok, msg = editar_actividad(conn, c["id"], c, codigo_persona)
        if not ok:
            errores.append(f"{c.get('fecha'):%d-%m-%Y} · {c.get('descripcion', '')[:30]}: {msg}" if c.get("fecha") else msg)
    for i in borrar:
        ok, msg = (anular_mi_actividad(conn, i, codigo_persona) if codigo_persona else anular_actividad_admin(conn, i))
        if not ok:
            errores.append(msg)
    if errores:
        raise CambiosRechazados(errores)
    partes = []
    if cambios:
        partes.append(f"{len(cambios)} corregida(s)")
    if borrar:
        partes.append(f"{len(borrar)} borrada(s)")
    return True, "Actividades: " + " y ".join(partes) + ".", []


class CambiosRechazados(Exception):
    """Se lanza para deshacer la transacción completa cuando alguna corrección no es válida."""
    def __init__(self, errores):
        super().__init__("; ".join(errores))
        self.errores = errores


def filas_editables(conn, anio: int, mes: int, codigo: str | None = None) -> list[dict]:
    """Actividades del mes con sus datos crudos (ids) para la tabla editable."""
    desde, hasta = rango_mes(anio, mes)
    pers = personas(conn)
    salida = []
    for f in repo.actividades_entre(conn, desde.isoformat(), hasta.isoformat(), codigo):
        a = _a_actividad(f)
        salida.append({"id": a.id, "codigo": a.codigo, "persona": pers[a.codigo].nombre if a.codigo in pers else a.codigo,
                       "fecha": a.fecha, "categoria_id": a.categoria_id, "descripcion": a.descripcion, "horas": a.horas,
                       "producto_id": a.producto_id, "evento_id": a.evento_id, "cliente": a.cliente,
                       "estado": a.estado, "motivo": f.get("motivo_revision") or ""})
    return salida


# ------------------------------------------------------------------ consolidados y simulador de sueldo
def filas_consolidado(conn, codigo: str | None, desde: date, hasta: date) -> list[dict]:
    """Actividades (sin rechazadas) entre dos fechas, con todos los textos para agrupar."""
    pers, cats, prods = personas(conn), categorias(conn), productos(conn)
    evs = {e.id: e.nombre for e in eventos(conn)}
    salida = []
    for f in repo.actividades_entre(conn, desde.isoformat(), (hasta + timedelta(days=1)).isoformat(), codigo):
        if f["estado"] == RECHAZADA:
            continue
        cat = cats.get(int(f["categoria_id"]))
        ev = int(f["evento_id"]) if f.get("evento_id") is not None else None
        persona = pers.get(f["codigo"])
        salida.append({
            "id": int(f["id"]), "codigo": f["codigo"], "persona": persona.nombre if persona else f["codigo"],
            "fecha": _fecha(f["fecha"]), "categoria": cat.nombre if cat else "?", "grupo": cat.grupo if cat else "",
            "producto": prods.get(int(f["producto_id"])) if f.get("producto_id") is not None else "",
            "carrera": (evs.get(ev) if ev else "") or (f.get("carrera_texto") or ""),
            "cliente": f.get("cliente") or "", "etiqueta": f.get("etiqueta") or "",
            "descripcion": f.get("descripcion") or "", "horas": _num(f["horas"]),
            "estado": DESCRIPCION_ESTADO.get(f["estado"], f["estado"]),
            "pagable": cat.pagable_por_hora if cat else True,
            "tarifa": tarifa_aplicable(persona, cat),
        })
    return salida


def escenarios(conn, codigo: str | None) -> list[dict]:
    salida = []
    for e in repo.escenarios(conn, codigo):
        try:
            par, exc = json.loads(e["parametros"] or "{}"), set(json.loads(e["excluidas"] or "[]"))
        except ValueError:
            par, exc = {}, set()
        salida.append({"id": int(e["id"]), "nombre": e["nombre"], "parametros": par, "excluidas": exc,
                       "creado_por": e["creado_por"], "creado_en": str(e["creado_en"])[:16]})
    return salida


def guardar_escenario(conn, nombre: str, codigo: str | None, parametros: dict, excluidas: set,
                      creado_por: str) -> tuple[bool, str]:
    nombre = (nombre or "").strip()
    if not nombre:
        return False, "Ponle un nombre al escenario (ej. «Propuesta Gabriel» o «Feedback JC»)."
    if any(e["nombre"].lower() == nombre.lower() for e in escenarios(conn, codigo)):
        return False, f"Ya existe un escenario llamado «{nombre}». Usa otro nombre o borra el anterior."
    repo.guardar_escenario(conn, nombre, codigo, json.dumps(parametros, ensure_ascii=False),
                           json.dumps(sorted(excluidas)), creado_por)
    return True, f"Escenario «{nombre}» guardado."


def borrar_escenario(conn, id_: int) -> tuple[bool, str]:
    repo.borrar_escenario(conn, id_)
    return True, "Escenario borrado."


def excel_consolidado(filas: list[dict], incluidas: set, periodo: str, dimension: str, tarifa: float | None,
                      retencion_pct: float, titulo: str, desde: date, hasta: date,
                      comparacion: list[dict] | None = None) -> bytes:
    """Excel con resumen, consolidado por período, estadística por tarea y detalle (con columna Incluida)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    tot = cons.totales(filas, incluidas, tarifa, retencion_pct, desde, hasta)
    wb = Workbook()
    cab, negrita = PatternFill("solid", fgColor="1B263D"), Font(bold=True)
    pesos, horas_fmt = '"$"#,##0', "0.00"

    def encabezar(ws, fila, nombres):
        for i, n in enumerate(nombres, 1):
            c = ws.cell(row=fila, column=i, value=n)
            c.font, c.fill = Font(bold=True, color="FFFFFF"), cab
            ws.column_dimensions[get_column_letter(i)].width = max(12, min(48, len(str(n)) + 6))

    ws = wb.active
    ws.title = "Resumen"
    ws["A1"], ws["A1"].font = titulo, Font(bold=True, size=14)
    ws["A2"] = f"Período: {desde:%d-%m-%Y} a {hasta:%d-%m-%Y} · Tarifa: " + (f"${tarifa:,.0f}".replace(",", ".") if tarifa else "la de cada persona/categoría")
    datos = [("Horas incluidas", tot["horas"], horas_fmt), ("Horas dejadas fuera", tot["horas_fuera"], horas_fmt),
             ("Valor bruto", tot["bruto"], pesos), (f"Retención ({retencion_pct:g} %)", tot["retencion"], pesos),
             ("Líquido", tot["liquido"], pesos), ("Promedio horas por mes", tot["horas_mes"], horas_fmt),
             ("Promedio horas por semana", tot["horas_semana"], horas_fmt),
             ("Boleta mensual equivalente (bruto)", tot["bruto_mes"], pesos),
             ("Meses con actividad", tot["meses_activos"], "0"),
             ("Boleta por mes con actividad (bruto)", tot["bruto_mes_activo"], pesos)]
    for i, (n, v, fmt) in enumerate(datos, 4):
        ws.cell(row=i, column=1, value=n)
        c = ws.cell(row=i, column=2, value=round(v, 2))
        c.number_format = fmt
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 40, 16
    if comparacion:
        r0 = 4 + len(datos) + 2
        ws.cell(row=r0 - 1, column=1, value="Comparación de escenarios").font = negrita
        encabezar(ws, r0, ["Escenario", "Horas", "Bruto", "Líquido", "Diferencia bruto vs actual"])
        for j, e in enumerate(comparacion, r0 + 1):
            for k, v in enumerate([e["Escenario"], e["Horas"], e["Bruto"], e["Líquido"], e["Diferencia"]], 1):
                c = ws.cell(row=j, column=k, value=v)
                c.number_format = horas_fmt if k == 2 else pesos if k > 2 else "General"
        ws.column_dimensions["A"].width = 40

    columnas, cruz = cons.tabla_cruzada(filas, incluidas, periodo, dimension, tarifa)
    w2 = wb.create_sheet(f"Por {periodo.lower()}")
    encabezar(w2, 1, ["Período", *columnas, "Total horas", "Valor"])
    for i, r in enumerate(cruz, 2):
        for k, n in enumerate(["Período", *columnas, "Total horas", "Valor"], 1):
            c = w2.cell(row=i, column=k, value=r[n])
            c.number_format = pesos if n == "Valor" else horas_fmt if k > 1 else "General"

    w3 = wb.create_sheet("Cuánto toma cada tarea")
    est = cons.estadistica(filas, incluidas, dimension, tarifa)
    nombres = [dimension, "Registros", "Días", "Horas", "Promedio por registro", "Mediana", "Máximo", "% del total", "Valor"]
    encabezar(w3, 1, nombres)
    for i, r in enumerate(est, 2):
        for k, n in enumerate(nombres, 1):
            c = w3.cell(row=i, column=k, value=round(r[n], 2) if isinstance(r[n], float) else r[n])
            c.number_format = pesos if n == "Valor" else "0.0" if n == "% del total" else horas_fmt if k > 3 else "General"

    w4 = wb.create_sheet("Detalle")
    nombres = ["Incluida", "Fecha", "Persona", "Tipo de actividad", "Descripción", "Horas", "Valor", "Carrera",
               "Cliente", "Etiqueta", "Estado"]
    encabezar(w4, 1, nombres)
    gris = PatternFill("solid", fgColor="EEEEEE")
    for i, f in enumerate(sorted(filas, key=lambda x: (x["fecha"], x["id"])), 2):
        dentro = f["id"] in incluidas
        vals = ["Sí" if dentro else "No", f["fecha"], f["persona"], f["categoria"], f["descripcion"], f["horas"],
                cons.valor_fila(f, tarifa) if dentro else 0, f["carrera"], f["cliente"], f["etiqueta"], f["estado"]]
        for k, v in enumerate(vals, 1):
            c = w4.cell(row=i, column=k, value=v)
            if k == 2:
                c.number_format = "DD-MM-YYYY"
            elif k == 6:
                c.number_format = horas_fmt
            elif k == 7:
                c.number_format = pesos
            if k == 5:
                c.alignment = Alignment(wrap_text=True, vertical="top")
            if not dentro:
                c.fill = gris
    w4.column_dimensions["E"].width = 60
    w4.freeze_panes = "A2"
    w4.auto_filter.ref = f"A1:K{len(filas) + 1}"
    salida = io.BytesIO()
    wb.save(salida)
    return salida.getvalue()
