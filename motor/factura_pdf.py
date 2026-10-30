"""Lee una factura electrónica chilena en PDF (la que emite TIMER) y saca sus datos principales.

Funciona con PDFs que tienen texto (los que genera el sistema de facturación). Si el PDF es una
foto escaneada no se puede leer: en ese caso los datos se escriben a mano en la pantalla.
Todo lo leído se muestra para revisar ANTES de guardar.
"""
from __future__ import annotations

import io
import re
from datetime import date

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
         "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}

_RUT = r"(\d{1,2}\.?\d{3}\.?\d{3}\s*-\s*[\dkK])"


def texto_del_pdf(contenido: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("Falta el paquete pypdf. Corre: python3 -m pip install -r requirements.txt") from e
    lector = PdfReader(io.BytesIO(contenido))
    return "\n".join((p.extract_text() or "") for p in lector.pages)


def _monto(patron: str, texto: str) -> int | None:
    m = re.search(patron + r"[^\d\n]*?\$?\s*([\d\.]+)\s*$", texto, flags=re.IGNORECASE | re.MULTILINE)
    if not m:
        return None
    try:
        return int(m.group(1).replace(".", ""))
    except ValueError:
        return None


def _rut(r: str) -> str:
    return re.sub(r"\s+", "", r).upper()


def _fecha(texto: str) -> date | None:
    m = re.search(r"Fecha\s*(?:de\s*)?Emisi[oó]n\s*:?\s*(\d{1,2})\s+de\s+([A-Za-zñÑ]+)\s+(?:de|del)\s+(\d{4})",
                  texto, flags=re.IGNORECASE)
    if m and m.group(2).lower() in MESES:
        try:
            return date(int(m.group(3)), MESES[m.group(2).lower()], int(m.group(1)))
        except ValueError:
            pass
    m = re.search(r"Fecha\s*(?:de\s*)?Emisi[oó]n\s*:?\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})", texto, flags=re.IGNORECASE)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    return None


def _descripcion(texto: str) -> str:
    lineas = texto.splitlines()
    inicio = next((i for i, l in enumerate(lineas) if re.match(r"\s*C[oó]digo\s+Descripci[oó]n", l, re.IGNORECASE)), None)
    if inicio is None:
        return ""
    partes = []
    for linea in lineas[inicio + 1:]:
        l = linea.strip()
        if not l or re.match(r"(Adic\.|%Desc)", l):
            continue
        if re.match(r"^\d+([.,]\d+)?\s*(un|uni|unid)\b", l, re.IGNORECASE) or re.match(r"Forma de Pago|Timbre", l, re.IGNORECASE):
            break
        partes.append(l)
    desc = " ".join(partes)
    # Quita el código del producto al comienzo (ej. "TCRONO-XCO ")
    desc = re.sub(r"^[A-Z0-9][A-Z0-9\-_]{2,}\s+", "", desc)
    return desc.strip()


def leer_factura_texto(texto: str) -> dict:
    """Saca los datos de la factura a partir de su texto. Siempre devuelve un dict (con avisos si falta algo)."""
    avisos = []
    plano = texto.upper()
    exenta = "EXENTA" in plano

    numero = None
    m = re.search(r"FACTURA[^\n]*\n(?:[^\n]*\n){0,2}?\s*N\s*[º°oO]\.?\s*:?\s*(\d+)", texto, flags=re.IGNORECASE)
    m = m or re.search(r"N\s*[º°]\s*:?\s*(\d+)", texto)
    if m:
        numero = m.group(1)

    cliente = ""
    m = re.search(r"SE[ÑN]OR(?:\(ES\)|ES)?\s*:\s*(.+)", texto, flags=re.IGNORECASE)
    if m:
        cliente = m.group(1).strip()
    rut_cliente = ""
    if m:
        r = re.search(r"R\.?\s*U\.?\s*T\.?\s*:?\s*" + _RUT, texto[m.end():])
        if r:
            rut_cliente = _rut(r.group(1))
    ruts = [_rut(x) for x in re.findall(r"R\.?\s*U\.?\s*T\.?\s*:?\s*" + _RUT, texto)]
    rut_emisor = next((r for r in ruts if r != rut_cliente), "")
    emisor = texto.strip().splitlines()[0].strip() if texto.strip() else ""

    neto = _monto(r"MONTO\s+NETO", texto)
    exento = _monto(r"MONTO\s+EXENTO", texto) or 0
    iva = _monto(r"\bI\.?\s*V\.?\s*A\b\.?(?:\s*\d+\s*%)?", texto)
    total = _monto(r"^\s*TOTAL", texto)

    if neto is None and exento:
        neto = exento
    if iva is None:
        iva = 0
    if neto is None and total is not None:
        neto = total - iva
    if total is None and neto is not None:
        total = neto + iva
    if neto is None:
        avisos.append("No se encontró el monto neto: escríbelo a mano.")
    elif total is not None and (neto + iva) != total and (neto + iva + exento) != total:
        avisos.append("Neto + IVA no calza con el total: revisa los montos.")
    fecha = _fecha(texto)
    if fecha is None:
        avisos.append("No se encontró la fecha de emisión.")
    if numero is None:
        avisos.append("No se encontró el número de factura.")
    if not cliente:
        avisos.append("No se encontró el nombre del cliente.")

    return {
        "numero": numero or "", "fecha": fecha, "cliente": cliente, "rut_cliente": rut_cliente,
        "emisor": emisor, "rut_emisor": rut_emisor, "descripcion": _descripcion(texto),
        "neto": neto or 0, "iva": iva or 0, "total": total or 0,
        "tasa_iva": 0.0 if (exenta or not iva) else 19.0, "avisos": avisos,
    }


def leer_factura(contenido: bytes) -> dict:
    try:
        texto = texto_del_pdf(contenido)
    except RuntimeError:
        raise
    except Exception:  # PDF dañado o protegido
        return {**leer_factura_texto(""), "avisos": ["No se pudo abrir el PDF. Escribe los datos a mano."]}
    if len(texto.strip()) < 20:
        return {**leer_factura_texto(""), "avisos": ["El PDF no tiene texto (¿es una foto escaneada?). "
                                                    "Escribe los datos a mano."]}
    return leer_factura_texto(texto)
