"""Pruebas de los consolidados (semana/mes/año), el simulador de sueldo y la importación sin duplicados."""
import unittest
from datetime import date

import servicios as sv
from motor import consolidado as cons
from tests.conexion_prueba import ConexionPrueba


class Consolidado(unittest.TestCase):
    def setUp(self):
        self.c = ConexionPrueba()
        sv.preparar_base(self.c)
        sv.guardar_persona(self.c, {"codigo": "t001", "nombre": "Gabriel", "tarifa_hora": 25000}, True)
        filas = [
            {"fecha": date(2026, 7, 1), "tipo": "Cotizaciones y propuestas", "descripcion": "Propuesta Speed Lab",
             "horas": 2, "carrera_texto": "Speed Lab Nike", "etiqueta": "A · Fuera de carreras"},
            {"fecha": date(2026, 7, 2), "tipo": "Reunión con cliente", "descripcion": "Reunión Sammis",
             "horas": 1, "carrera_texto": "Desafío Sammis Reyes", "etiqueta": "A · Fuera de carreras"},
            {"fecha": date(2026, 7, 8), "tipo": "CRM HubSpot", "descripcion": "Barrido de contactos",
             "horas": 1.5, "etiqueta": "A · Fuera de carreras"},
            {"fecha": date(2026, 8, 3), "tipo": "Reunión interna de equipo", "descripcion": "Iquique: precio",
             "horas": 0.5, "carrera_texto": "Desafío Sammis Reyes Iquique", "etiqueta": "B · Coordinación de carrera"},
        ]
        ok, msg, err = sv.guardar_lote(self.c, "t001", filas)
        self.assertTrue(ok, (msg, err))
        self.filas = sv.filas_consolidado(self.c, "t001", date(2026, 1, 1), date(2026, 12, 31))

    def test_carrera_y_etiqueta_se_guardan(self):
        self.assertEqual(len(self.filas), 4)
        speed = next(f for f in self.filas if "Speed" in f["descripcion"])
        self.assertEqual(speed["carrera"], "Speed Lab Nike")
        self.assertEqual(speed["etiqueta"], "A · Fuera de carreras")

    def test_por_defecto_b_queda_fuera(self):
        fuera = {"etiqueta": {e for e in {f["etiqueta"] for f in self.filas} if cons.excluida_por_defecto(e)}}
        dentro = cons.incluidas_por_filtros(self.filas, fuera)
        t = cons.totales(self.filas, dentro, retencion_pct=15.25)
        self.assertEqual(t["horas"], 4.5)
        self.assertEqual(t["bruto"], 112_500)
        self.assertEqual(t["retencion"], 17_156)
        self.assertEqual(t["horas_fuera"], 0.5)

    def test_dejar_fuera_una_carrera_cambia_el_numero(self):
        todas = {f["id"] for f in self.filas}
        sin_sammis = cons.incluidas_por_filtros(self.filas, {"carrera": {"Desafío Sammis Reyes", "Desafío Sammis Reyes Iquique"}})
        self.assertEqual(cons.totales(self.filas, todas)["horas"], 5.0)
        self.assertEqual(cons.totales(self.filas, sin_sammis)["horas"], 3.5)
        # Una marca a mano manda sobre el filtro
        sammis = next(f["id"] for f in self.filas if f["descripcion"] == "Reunión Sammis")
        con_una = cons.incluidas_por_filtros(self.filas, {"carrera": {"Desafío Sammis Reyes"}}, {sammis: True})
        self.assertIn(sammis, con_una)
        # Tarifa simulada
        self.assertEqual(cons.totales(self.filas, todas, tarifa=20000)["bruto"], 100_000)

    def test_periodos(self):
        todas = {f["id"] for f in self.filas}
        semanas = cons.por_periodo(self.filas, todas, "Semana", "Carrera")
        self.assertEqual({x["Período"] for x in semanas}, {"Sem 27 · 29-06", "Sem 28 · 06-07", "Sem 32 · 03-08"})
        cols, cruz = cons.tabla_cruzada(self.filas, todas, "Mes", "Etiqueta")
        self.assertEqual([r["Período"] for r in cruz], ["jul 2026", "ago 2026"])
        self.assertEqual(cruz[0]["A · Fuera de carreras"], 4.5)
        self.assertEqual(cruz[1]["Total horas"], 0.5)
        anio = cons.por_periodo(self.filas, todas, "Año", "Persona")
        self.assertEqual(anio[0]["Horas"], 5.0)
        est = cons.estadistica(self.filas, todas, "Tipo de actividad")
        self.assertEqual(est[0]["Tipo de actividad"], "Cotizaciones y propuestas")
        self.assertAlmostEqual(sum(r["% del total"] for r in est), 100)

    def test_promedio_mensual(self):
        todas = {f["id"] for f in self.filas}
        t = cons.totales(self.filas, todas, desde=date(2026, 7, 1), hasta=date(2026, 8, 31))
        self.assertEqual(t["meses_activos"], 2)
        self.assertAlmostEqual(t["horas_mes"], 5.0 / (62 / 30.4375))
        self.assertEqual(t["bruto_mes_activo"], 62_500)

    def test_volver_a_subir_no_duplica(self):
        repetida = [{"fecha": date(2026, 7, 8), "tipo": "CRM HubSpot", "descripcion": "barrido de  contactos",
                     "horas": 1.5, "etiqueta": "C · otra", "carrera_texto": "X"},
                    {"fecha": date(2026, 7, 9), "tipo": "CRM HubSpot", "descripcion": "Nueva", "horas": 1}]
        ok, msg, _ = sv.guardar_lote(self.c, "t001", repetida)
        self.assertTrue(ok, msg)
        self.assertIn("1 ya estaban", msg)
        filas = sv.filas_consolidado(self.c, "t001", date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(len(filas), 5)
        barrido = next(f for f in filas if f["descripcion"] == "Barrido de contactos")
        self.assertEqual(barrido["etiqueta"], "A · Fuera de carreras")   # no se pisa la que ya tenía
        self.assertEqual(barrido["carrera"], "X")                         # la vacía sí se completa

    def test_escenarios(self):
        ok, _ = sv.guardar_escenario(self.c, "Feedback JC", "t001", {"tarifa": 25000}, {1, 2}, "admin")
        self.assertTrue(ok)
        ok, msg = sv.guardar_escenario(self.c, "feedback jc", "t001", {}, set(), "admin")
        self.assertFalse(ok)
        e = sv.escenarios(self.c, "t001")
        self.assertEqual(e[0]["excluidas"], {1, 2})
        self.assertEqual(sv.escenarios(self.c, None), [])
        sv.borrar_escenario(self.c, e[0]["id"])
        self.assertEqual(sv.escenarios(self.c, "t001"), [])

    def test_excel(self):
        todas = {f["id"] for f in self.filas}
        datos = sv.excel_consolidado(self.filas, todas, "Mes", "Carrera", None, 15.25, "Prueba",
                                     date(2026, 1, 1), date(2026, 12, 31),
                                     [{"Escenario": "Actual", "Horas": 5, "Bruto": 1, "Líquido": 1, "Diferencia": 0}])
        self.assertGreater(len(datos), 3000)


if __name__ == "__main__":
    unittest.main()
