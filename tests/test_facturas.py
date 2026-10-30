"""Pruebas del lector de facturas y de la cobranza por carrera."""
import unittest
from datetime import date

import servicios as sv
from motor.factura_pdf import leer_factura_texto
from tests.conexion_prueba import ConexionPrueba

# Texto con la misma forma que el PDF que genera el sistema de facturación (datos ficticios).
TEXTO = """EMPRESA EMISORA DE PRUEBA SPA
 Giro: SERVICIOS DEPORTIVOS
SEÑOR(ES): CLUB DEPORTIVO EJEMPLO SPA
R.U.T.: 76.111.222- 3
GIRO: EVENTOS
R.U.T.:76.999.888- K
FACTURA ELECTRONICA
Nº2001
S.I.I. - SANTIAGO CENTRO
Fecha Emision: 5 de Noviembre del 2026
Codigo Descripcion Cantidad Precio %Impto
Adic.* %Desc. Valor
TCRONO-TRAIL Cronometraje con chip Trail Cerro
Anticipo 50 %.
1 un 1.000.000 1.000.000
Forma de Pago:Contado
MONTO NETO $ 1.000.000
I.V.A. 19% $ 190.000
IMPUESTO ADICIONAL $ 0
TOTAL $ 1.190.000"""


class LectorFactura(unittest.TestCase):
    def test_lee_campos(self):
        d = leer_factura_texto(TEXTO)
        self.assertEqual(d["numero"], "2001")
        self.assertEqual(d["fecha"], date(2026, 11, 5))
        self.assertEqual(d["cliente"], "CLUB DEPORTIVO EJEMPLO SPA")
        self.assertEqual(d["rut_cliente"], "76.111.222-3")
        self.assertEqual(d["rut_emisor"], "76.999.888-K")
        self.assertEqual((d["neto"], d["iva"], d["total"]), (1_000_000, 190_000, 1_190_000))
        self.assertEqual(d["descripcion"], "Cronometraje con chip Trail Cerro Anticipo 50 %.")
        self.assertEqual(d["tasa_iva"], 19.0)
        self.assertEqual(d["avisos"], [])

    def test_exenta(self):
        t = TEXTO.replace("FACTURA ELECTRONICA", "FACTURA NO AFECTA O EXENTA ELECTRONICA") \
                 .replace("MONTO NETO $ 1.000.000\nI.V.A. 19% $ 190.000", "MONTO EXENTO $ 1.000.000") \
                 .replace("TOTAL $ 1.190.000", "TOTAL $ 1.000.000")
        d = leer_factura_texto(t)
        self.assertEqual((d["neto"], d["iva"], d["total"], d["tasa_iva"]), (1_000_000, 0, 1_000_000, 0.0))

    def test_texto_vacio(self):
        d = leer_factura_texto("")
        self.assertTrue(d["avisos"])
        self.assertEqual(d["neto"], 0)


class Cobranza(unittest.TestCase):
    def setUp(self):
        self.c = ConexionPrueba()
        sv.preparar_base(self.c)

    def test_anticipo_y_saldo(self):
        d = leer_factura_texto(TEXTO)
        ok, msg, eid = sv.guardar_factura(self.c, d, None, 50, "Trail Cerro", b"%PDF-1.4 x", "f2001.pdf")
        self.assertTrue(ok, msg)
        ev = next(e for e in sv.eventos(self.c) if e.id == eid)
        self.assertEqual(ev.venta_neta, 2_000_000)      # 1.000.000 es el 50 %
        self.assertEqual(ev.estado, "confirmado")
        self.assertFalse(sv.guardar_factura(self.c, d, eid, 50)[0])   # mismo N° no se repite

        saldo = dict(d, numero="2050", fecha=date(2026, 11, 20))
        self.assertTrue(sv.guardar_factura(self.c, saldo, eid, 50)[0])
        cob = sv.cobranza(self.c, ev)
        self.assertEqual(cob["facturado"], 2_000_000)
        self.assertEqual(cob["pct_facturado"], 100)
        self.assertEqual(cob["pagado"], 0)
        primera = cob["facturas"][0]
        self.assertEqual(primera["% de la carrera"], 50)
        sv.marcar_pago_factura(self.c, primera["id"], True, date(2026, 11, 10))
        cob = sv.cobranza(self.c, ev)
        self.assertEqual(cob["pct_pagado"], 50)
        self.assertEqual(cob["por_cobrar"], 1_000_000)
        self.assertEqual(sv.archivo_factura(self.c, primera["id"]), (b"%PDF-1.4 x", "f2001.pdf"))
        sv.anular_factura(self.c, cob["facturas"][1]["id"])
        self.assertEqual(sv.cobranza(self.c, ev)["facturado"], 1_000_000)

    def test_factura_a_carrera_sin_valor(self):
        ok, _, eid = sv.guardar_evento(self.c, None, {"nombre": "X", "estado": "cotizado", "base_reparto": "margen",
                                                      "pct_empresa": 50, "pct_director": 15, "pct_equipo": 35}, [], [])
        self.assertTrue(ok)
        sv.guardar_factura(self.c, leer_factura_texto(TEXTO), eid, 100)
        ev = next(e for e in sv.eventos(self.c) if e.id == eid)
        self.assertEqual(ev.venta_neta, 1_000_000)


if __name__ == "__main__":
    unittest.main()
