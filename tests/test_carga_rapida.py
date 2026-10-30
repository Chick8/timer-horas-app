"""Pruebas de la carga rápida de muchos días y del resumen por período."""
import unittest
from datetime import date, timedelta

import servicios as sv
from motor import APROBADA
from tests.conexion_prueba import ConexionPrueba


class CargaRapida(unittest.TestCase):
    def setUp(self):
        self.c = ConexionPrueba()
        sv.preparar_base(self.c)
        sv.guardar_persona(self.c, {"codigo": "t001", "nombre": "Gabriel", "tarifa_hora": 10000}, True)
        self.d1, self.d2 = date(2026, 4, 7), date(2026, 5, 12)

    def test_lote_y_resumen(self):
        filas = [
            {"fecha": self.d1, "tipo": "Reunión con cliente", "descripcion": "Reu trail", "horas": 2},
            {"fecha": self.d1, "tipo": "crm hubspot", "descripcion": "Ordenar negocios", "horas": 1.5},
            {"fecha": self.d2, "tipo": "Soldadura", "descripcion": "Soldar antena", "horas": 1},
            {"fecha": self.d2, "tipo": "Montaje y cronometraje en carrera", "descripcion": "Carrera", "horas": 8},
        ]
        ok, msg, errores = sv.guardar_lote(self.c, "t001", filas)
        self.assertTrue(ok, (msg, errores))
        r = sv.resumen_periodo(self.c, "t001", date(2026, 4, 1), date(2026, 10, 31))
        self.assertEqual(r["total"]["horas"], 12.5)
        self.assertEqual(r["total"]["dias"], 2)
        self.assertEqual(r["total"]["pendientes"], 4.5)
        self.assertEqual(r["total"]["horas_carrera"], 8)
        self.assertEqual(r["total"]["monto_total"], 45_000)
        self.assertEqual([m["Mes"] for m in r["meses"]], ["Abril 2026", "Mayo 2026"])
        acts = sv.actividades_de_dia(self.c, "t001", self.d1)
        sv.revisar(self.c, [a.id for a in acts], APROBADA, "admin")
        r = sv.resumen_periodo(self.c, "t001", date(2026, 4, 1), date(2026, 10, 31))
        self.assertEqual(r["total"]["aprobadas"], 3.5)
        self.assertEqual(sv.resumen_periodo(self.c, None, date(2026, 4, 1), date(2026, 4, 30))["total"]["horas"], 3.5)

    def test_lote_con_errores_no_guarda_nada(self):
        filas = [
            {"fecha": self.d1, "tipo": "Reunión con cliente", "descripcion": "ok", "horas": 2},
            {"fecha": None, "tipo": "Otro", "descripcion": "sin fecha", "horas": 1},
            {"fecha": self.d1, "tipo": "No existe", "descripcion": "x", "horas": 1},
            {"fecha": sv.hoy() + timedelta(days=3), "tipo": "Otro", "descripcion": "futuro", "horas": 1},
            {"fecha": self.d2, "tipo": "Otro", "descripcion": "", "horas": 1},
        ]
        ok, _, errores = sv.guardar_lote(self.c, "t001", filas)
        self.assertFalse(ok)
        self.assertEqual(len(errores), 4)
        self.assertEqual(sv.actividades_de_dia(self.c, "t001", self.d1), [])

    def test_maximo_por_dia(self):
        filas = [{"fecha": self.d1, "tipo": "Otro", "descripcion": "a", "horas": 10},
                 {"fecha": self.d1, "tipo": "Otro", "descripcion": "b", "horas": 7}]
        ok, _, errores = sv.guardar_lote(self.c, "t001", filas)
        self.assertFalse(ok)
        self.assertIn("17", errores[0])

    def test_plantilla_ida_y_vuelta(self):
        contenido = sv.plantilla_excel(self.c)
        filas = sv.leer_planilla(contenido, "plantilla.xlsx")
        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[0]["fecha"], date(2026, 4, 7))
        self.assertEqual(filas[1]["horas"], 1.5)
        ok, msg, errores = sv.guardar_lote(self.c, "t001", filas)
        self.assertTrue(ok, errores)
        csv = "Fecha;Tipo de actividad;Descripción;Horas\n03-06-2026;Otro;Algo;1,5\n".encode()
        self.assertEqual(sv.leer_planilla(csv, "x.csv")[0]["horas"], 1.5)


if __name__ == "__main__":
    unittest.main()
