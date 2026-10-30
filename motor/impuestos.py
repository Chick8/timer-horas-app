"""IVA de la venta de una carrera.

Cuando TIMER emite una FACTURA AFECTA, el cliente paga:   total = neto + IVA (19 %)
El IVA NO es plata de TIMER: se declara y paga al SII (descontando el IVA de las compras).
Por eso el reparto se calcula siempre sobre el NETO.

Con FACTURA EXENTA no hay IVA: lo transferido es el neto.
"""
from __future__ import annotations

IVA_CHILE = 19.0


def desglose(monto: float, tasa_iva: float = IVA_CHILE, incluye_iva: bool = True) -> dict:
    """Devuelve neto, IVA y total (en pesos enteros) a partir de un monto con o sin IVA."""
    monto = float(monto or 0)
    tasa = float(tasa_iva or 0)
    if incluye_iva:
        neto = round(monto / (1 + tasa / 100))
        total = round(monto)
    else:
        neto = round(monto)
        total = round(monto * (1 + tasa / 100))
    return {"neto": neto, "iva": total - neto, "total": total}
