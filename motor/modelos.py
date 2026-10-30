"""Fichas de datos de la app de horas de TIMER.

Todo lo que entra y sale del motor de cálculo es una de estas fichas.
No dependen de Streamlit ni de la base de datos: así se pueden probar solas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

# Estados de una actividad registrada
PENDIENTE = "pendiente"      # la persona la cargó; falta que administración la revise
APROBADA = "aprobada"        # entra al sueldo
RECHAZADA = "rechazada"      # no entra al sueldo (queda el motivo)

DESCRIPCION_ESTADO = {PENDIENTE: "Por revisar", APROBADA: "Aprobada", RECHAZADA: "Rechazada"}

# Estados de una carrera / evento
COTIZADO = "cotizado"
CONFIRMADO = "confirmado"
REALIZADO = "realizado"
PAGADO = "pagado"
PERDIDO = "perdido"
ESTADOS_EVENTO = [COTIZADO, CONFIRMADO, REALIZADO, PAGADO, PERDIDO]
NOMBRE_ESTADO_EVENTO = {
    COTIZADO: "Cotizado", CONFIRMADO: "Confirmado", REALIZADO: "Realizado",
    PAGADO: "Pagado por el cliente", PERDIDO: "Perdido / no se hizo",
}
# Solo las carreras ya hechas entran al sueldo del mes. Las cotizadas/confirmadas son estimación.
ESTADOS_QUE_PAGAN = {REALIZADO, PAGADO}

# Roles dentro de una carrera
DIRECTOR = "director"
TECNICO = "tecnico"
APOYO = "apoyo"
ROLES = {DIRECTOR: "Director de carrera", TECNICO: "Técnico TIMER", APOYO: "Apoyo"}

# Sobre qué se calculan los porcentajes del reparto
BASE_MARGEN = "margen"   # venta neta − gastos (recomendado)
BASE_VENTA = "venta"     # venta neta (los gastos salen de la parte de la empresa)
BASES_REPARTO = {BASE_MARGEN: "Margen (venta neta − gastos)", BASE_VENTA: "Venta neta"}

# Tipos de gasto de una carrera
TIPOS_GASTO = ["Viáticos", "Transporte / bencina / peajes", "Alojamiento", "Chips e insumos",
               "Arriendo de equipos", "Personal externo", "Otros"]


@dataclass
class Persona:
    codigo: str
    nombre: str
    cargo: str = ""
    tarifa_hora: float = 0.0      # CLP por hora
    activo: bool = True


@dataclass
class Categoria:
    id: int
    nombre: str
    grupo: str = ""
    pagable_por_hora: bool = True          # False = se paga por el reparto de la carrera, no por hora
    tarifa_hora_especial: Optional[float] = None   # si está, reemplaza la tarifa de la persona


@dataclass
class Actividad:
    codigo: str                 # persona
    fecha: date
    categoria_id: int
    horas: float
    descripcion: str = ""
    producto_id: Optional[int] = None
    evento_id: Optional[int] = None
    cliente: str = ""
    estado: str = PENDIENTE
    id: Optional[int] = None


@dataclass
class Gasto:
    tipo: str
    monto: float
    descripcion: str = ""


@dataclass
class Integrante:
    codigo: str
    rol: str = TECNICO
    peso: float = 1.0        # jornadas o días trabajados
    factor: float = 1.0      # ponderación por la función que cumplió (meta, partida, apoyo...). 1 = normal
    funcion: str = ""
    factor_manual: Optional[float] = None   # si se escribió a mano (reemplaza la del nivel)

    @property
    def peso_final(self) -> float:
        """Jornadas × ponderación: en esa proporción se reparte la parte del equipo."""
        return max(self.peso, 0) * max(self.factor, 0)


@dataclass
class ReglasReparto:
    base: str = BASE_MARGEN
    pct_empresa: float = 50.0
    pct_director: float = 15.0
    pct_equipo: float = 35.0


@dataclass
class Evento:
    id: Optional[int]
    nombre: str
    fecha: Optional[date]
    venta_neta: float = 0.0          # SIN IVA: es lo que realmente es de TIMER
    estado: str = COTIZADO
    tasa_iva: float = 19.0           # 19 = factura afecta · 0 = factura exenta
    honorarios_aprobados: bool = False   # el reparto al equipo ya fue revisado y aprobado
    cliente: str = ""
    producto_id: Optional[int] = None
    reglas: ReglasReparto = field(default_factory=ReglasReparto)
    gastos: list = field(default_factory=list)       # list[Gasto]
    equipo: list = field(default_factory=list)       # list[Integrante]


@dataclass
class PagoIntegrante:
    codigo: str
    rol: str
    peso: float
    monto: float
    factor: float = 1.0
    funcion: str = ""
    participacion: float = 0.0     # % de su grupo (director o equipo)


@dataclass
class ResultadoReparto:
    venta_neta: float
    total_gastos: float
    margen: float
    margen_pct: float          # margen / venta
    base_monto: float          # monto sobre el que se aplican los %
    monto_empresa: float
    monto_director: float
    monto_equipo: float
    pagos: list                # list[PagoIntegrante]
    alertas: list


@dataclass
class FilaSueldo:
    codigo: str
    nombre: str
    tarifa_hora: float
    horas_aprobadas: float = 0.0        # pagables por hora
    monto_horas: float = 0.0
    horas_pendientes: float = 0.0       # pagables por hora, todavía sin revisar
    monto_pendiente: float = 0.0
    horas_evento: float = 0.0           # horas en categorías que se pagan por reparto (solo informativo)
    monto_carreras: float = 0.0
    monto_carreras_por_aprobar: float = 0.0   # carreras realizadas cuyo reparto falta aprobar
    detalle_carreras: list = field(default_factory=list)   # [(nombre evento, rol, monto)]
    total_bruto: float = 0.0
    retencion: float = 0.0
    total_liquido: float = 0.0
    alertas: list = field(default_factory=list)
