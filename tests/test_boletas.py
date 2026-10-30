"""Pruebas de pagos por carrera y solicitud de boletas de honorarios."""
import unittest
from datetime import date

import servicios as sv
from tests.conexion_prueba import ConexionPrueba


class Boletas(unittest.TestCase):
    def setUp(self):
        self.c = ConexionPrueba()
        sv.preparar_base(self.c)
        for cod, nombre in (("t001", "Gabriel Del Río"), ("t002", "Pedro")):
            sv.guardar_persona(self.c, {"codigo": cod, "nombre": nombre, "tarifa_hora": 0}, True)
        self.assertTrue(sv.guardar_contacto(self.c, "t002", "pedro@ejemplo.cl", "+56 9 1234 5678")[0])
        self.assertFalse(sv.guardar_contacto(self.c, "t002", "no-es-correo", "")[0])
        ok, _, self.eid = sv.guardar_evento(self.c, None, {
            "nombre": "XCO Antofagasta", "fecha": date(2026, 10, 18), "estado": "realizado", "venta_neta": 1_490_000,
            "base_reparto": "margen", "pct_empresa": 70, "pct_director": 20, "pct_equipo": 10},
            [{"tipo": "Viáticos", "monto": 566_103}],
            [{"codigo": "t001", "rol": "director", "peso": 1}, {"codigo": "t002", "rol": "tecnico", "peso": 1}])
        self.ev = next(e for e in sv.eventos(self.c) if e.id == self.eid)

    def test_montos_y_mensaje(self):
        pagos = {p["codigo"]: p for p in sv.pagos_de_carrera(self.c, self.ev)}
        p = pagos["t002"]
        self.assertEqual(p["bruto"], 92_390)                        # 10 % de 923.897
        self.assertEqual(p["retencion"], round(92_390 * 0.1525))
        self.assertEqual(p["liquido"], p["bruto"] - p["retencion"])
        self.assertEqual(p["email"], "pedro@ejemplo.cl")
        asunto, cuerpo = sv.mensaje_boleta(self.c, self.ev, p)
        self.assertIn("XCO Antofagasta (18-10-2026)", asunto)
        self.assertIn("$92.390", cuerpo)
        self.assertIn("76.415.603-K", cuerpo)
        self.assertIn("Hola Pedro", cuerpo)
        self.assertTrue(sv.enlace_correo(p["email"], asunto, cuerpo).startswith("mailto:pedro%40ejemplo.cl?subject="))

    def test_flujo_boleta(self):
        self.assertTrue(sv.cambiar_estado_boleta(self.c, self.ev, "t002", "solicitada")[0])
        self.assertFalse(sv.cambiar_estado_boleta(self.c, self.ev, "t002", "recibida")[0])   # falta N°
        self.assertFalse(sv.cambiar_estado_boleta(self.c, self.ev, "t002", "recibida", "15", codigo_persona="t001")[0])
        self.assertTrue(sv.cambiar_estado_boleta(self.c, self.ev, "t002", "recibida", "15", b"%PDF", "b15.pdf",
                                                 codigo_persona="t002")[0])
        self.assertEqual(sv.archivo_boleta(self.c, self.eid, "t002"), (b"%PDF", "b15.pdf"))
        self.assertTrue(sv.cambiar_estado_boleta(self.c, self.ev, "t002", "pagada")[0])
        mis = sv.mis_pagos(self.c, "t002")
        self.assertEqual(len(mis), 1)
        self.assertEqual((mis[0]["estado"], mis[0]["numero_boleta"]), ("pagada", "15"))
        self.assertTrue(sv.eliminar_evento(self.c, self.eid)[0])
        self.assertEqual(sv.mis_pagos(self.c, "t002"), [])


if __name__ == "__main__":
    unittest.main()
