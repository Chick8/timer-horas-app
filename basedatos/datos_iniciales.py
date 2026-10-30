"""Lo que se carga solo la primera vez que se abre la app (si las tablas están vacías).

Todo esto se puede cambiar después desde Administración → Categorías y productos.
"""

# (nombre, grupo, pagable_por_hora)
CATEGORIAS = [
    ("Reunión con cliente", "Comercial", True),
    ("Llamadas / seguimiento a clientes", "Comercial", True),
    ("Cotizaciones y propuestas", "Comercial", True),
    ("CRM HubSpot (gestión y métricas)", "Comercial", True),
    ("Reunión interna de equipo", "Gestión", True),
    ("Administración, pagos y rendiciones", "Gestión", True),
    ("Prueba y preparación de equipos", "Taller", True),
    ("Armado de mochilas / kits de carrera", "Taller", True),
    ("Soldadura y reparación electrónica", "Taller", True),
    ("Chips y números (codificación, armado)", "Taller", True),
    ("Envíos y despachos (Starken, etc.)", "Logística", True),
    ("Compras y retiro de materiales", "Logística", True),
    ("Traslado / viaje a carrera", "Carrera", False),
    ("Montaje y cronometraje en carrera", "Carrera", False),
    ("Resultados y post-carrera", "Carrera", True),
    ("Desarrollo / software / web", "Desarrollo", True),
    ("Otro", "Otros", True),
]

PRODUCTOS = [
    "General (no asociado a un producto)",
    "Running / calle",
    "Trail running",
    "Ciclismo ruta / MTB",
    "Gravel",
    "Downhill / enduro",
    "Natación / triatlón",
    "Pruebas físicas (Speed Lab, 40 yardas)",
    "Arriendo / venta de equipos",
]

NOMBRE_EMPRESA = "TIMER"

# Funciones dentro de una carrera: (nombre, nivel). Nivel 1 = mayor responsabilidad / mejor pagado.
FUNCIONES = [
    ("Meta – cronometraje principal", 1),
    ("Coordinación y movilización del equipo", 1),
    ("Montaje técnico (antenas, alfombras, sistema)", 1),
    ("Partida", 2),
    ("Puntos de control / parciales", 2),
    ("Entrega de kits y chips", 2),
    ("Resultados y pantalla", 2),
    ("Apoyo en meta (respaldo)", 3),
    ("Apoyo general / logística", 3),
]

NIVELES = {1: "Nivel 1 · Alta responsabilidad", 2: "Nivel 2 · Operación", 3: "Nivel 3 · Apoyo"}
