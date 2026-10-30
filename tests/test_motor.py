"""Pruebas del motor de cálculo. Correr con:  python3 -m unittest discover tests"""
import unittest
from datetime import date

from motor import (
    APROBADA, BASE_VENTA, CONFIRMADO, DIRECTOR, PENDIENTE, REALIZADO, RECHAZADA, TECNICO,
    Actividad, Categoria, Evento, Gasto, Integrante, Persona, ReglasReparto,
    calcular_reparto, horas_entre, rango_mes, sueldos_del_mes, validar_actividad, validar_reglas,
)
from motor.formato import horas_texto, pesos, semanas_del_mes


def evento_base(**kw):
    datos = dict(
        id=1, nombre="Trail Cerro", fecha=date(2026, 10, 18), venta_neta=1_000_000, estado=REALIZADO,
        honorarios_aprobados=True,
        gastos=[Gasto("Viáticos", 100_000), Gasto("Alojamiento", 100_000)],
        equipo=[Integrante("t001", DIRECTOR), Integrante("t002", TECNICO), Integrante("t003", TECNICO)],
    )
    datos.update(kw)
    return Evento(**datos)


class Reparto(unittest.TestCase):
    def test_ponderacion_por_funcion(self):
        ev = evento_base(gastos=[], venta_neta=1_000_000, equipo=[
            Integrante("t001", DIRECTOR),
            Integrante("t002", TECNICO, 1, factor=1.5, funcion="Meta"),
            Integrante("t003", TECNICO, 1, factor=1.0, funcion="Partida"),
            Integrante("t004", TECNICO, 2, factor=0.5, funcion="Apoyo")])
        r = calcular_reparto(ev)                     # equipo = 350.000; pesos 1,5 / 1 / 1 -> 3,5
        pagos = {p.codigo: p for p in r.pagos}
        self.assertEqual(pagos["t002"].monto, 150_000)
        self.assertEqual(pagos["t003"].monto, 100_000)
        self.assertEqual(pagos["t004"].monto, 100_000)
        self.assertAlmostEqual(pagos["t002"].participacion, 1.5 / 3.5 * 100)
        self.assertEqual(sum(p.monto for p in r.pagos if p.rol == TECNICO), r.monto_equipo)

    def test_reparto_sobre_margen(self):
        r = calcular_reparto(evento_base())
        self.assertEqual(r.margen, 800_000)
        self.assertAlmostEqual(r.margen_pct, 80)
        self.assertEqual(r.monto_director, 120_000)    # 15 % de 800.000
        self.assertEqual(r.monto_equipo, 280_000)      # 35 %
        self.assertEqual(r.monto_empresa, 400_000)     # 50 %
        pagos = {p.codigo: p.monto for p in r.pagos}
        self.assertEqual(pagos, {"t001": 120_000, "t002": 140_000, "t003": 140_000})
        self.assertEqual(r.alertas, [])

    def test_reparto_por_peso_y_redondeo_cuadra(self):
        ev = evento_base(venta_neta=1_000_001, gastos=[],
                         equipo=[Integrante("t002", TECNICO, 2), Integrante("t003", TECNICO, 1)])
        r = calcular_reparto(ev)
        pagos = {p.codigo: p.monto for p in r.pagos}
        self.assertEqual(sum(pagos.values()), r.monto_equipo)
        self.assertGreater(pagos["t002"], pagos["t003"])

    def test_sin_margen_no_reparte(self):
        r = calcular_reparto(evento_base(venta_neta=150_000))
        self.assertEqual(r.monto_director + r.monto_equipo, 0)
        self.assertTrue(any("margen" in a for a in r.alertas))

    def test_sin_director_su_parte_queda_en_empresa(self):
        r = calcular_reparto(evento_base(equipo=[Integrante("t002", TECNICO)]))
        self.assertEqual(r.monto_director, 0)
        self.assertEqual(r.monto_empresa, 800_000 - 280_000)
        self.assertTrue(r.alertas)

    def test_base_venta(self):
        ev = evento_base(reglas=ReglasReparto(base=BASE_VENTA, pct_empresa=70, pct_director=10, pct_equipo=20))
        r = calcular_reparto(ev)
        self.assertEqual(r.monto_director, 100_000)
        self.assertEqual(r.monto_equipo, 200_000)
        self.assertEqual(r.monto_empresa, 1_000_000 - 200_000 - 300_000)

    def test_porcentajes_deben_sumar_100(self):
        ok, _ = validar_reglas(ReglasReparto(pct_empresa=50, pct_director=20, pct_equipo=20))
        self.assertFalse(ok)
        r = calcular_reparto(evento_base(reglas=ReglasReparto(pct_empresa=50, pct_director=20, pct_equipo=20)))
        self.assertEqual(r.monto_director + r.monto_equipo, 0)


class Sueldos(unittest.TestCase):
    def setUp(self):
        self.personas = {"t001": Persona("t001", "Gabriel", tarifa_hora=8000),
                         "t002": Persona("t002", "Pedro", tarifa_hora=6000),
                         "t003": Persona("t003", "Juan Carlos", tarifa_hora=0)}
        self.cats = {1: Categoria(1, "CRM / HubSpot"),
                     2: Categoria(2, "Soldadura", tarifa_hora_especial=10000),
                     3: Categoria(3, "Cronometraje en carrera", pagable_por_hora=False)}

    def test_horas_aprobadas_pendientes_y_carreras(self):
        d = date(2026, 10, 5)
        acts = [
            Actividad("t001", d, 1, 2.0, "Llamadas a clientes perdidos", estado=APROBADA),
            Actividad("t001", d, 2, 1.5, "Soldar cable antena", estado=APROBADA),
            Actividad("t001", d, 1, 1.0, "Revisión cotizaciones", estado=PENDIENTE),
            Actividad("t001", d, 1, 3.0, "Duplicado", estado=RECHAZADA),
            Actividad("t001", d, 3, 8.0, "Cronometraje", estado=APROBADA),
        ]
        filas = {f.codigo: f for f in sueldos_del_mes(self.personas, self.cats, acts, [evento_base()],
                                                      pct_retencion=15.25)}
        g = filas["t001"]
        self.assertEqual(g.horas_aprobadas, 3.5)
        self.assertEqual(g.monto_horas, 2 * 8000 + 1.5 * 10000)
        self.assertEqual(g.horas_pendientes, 1.0)
        self.assertEqual(g.monto_pendiente, 8000)
        self.assertEqual(g.horas_evento, 8.0)
        self.assertEqual(g.monto_carreras, 120_000)
        self.assertEqual(g.total_bruto, 31_000 + 120_000)
        self.assertEqual(g.retencion, round(151_000 * 0.1525))
        self.assertEqual(g.total_liquido, g.total_bruto - g.retencion)
        self.assertEqual(filas["t002"].monto_carreras, 140_000)

    def test_carrera_sin_aprobar_queda_aparte(self):
        filas = {f.codigo: f for f in sueldos_del_mes(self.personas, self.cats, [],
                                                      [evento_base(honorarios_aprobados=False)])}
        self.assertEqual(filas["t001"].monto_carreras, 0)
        self.assertEqual(filas["t001"].monto_carreras_por_aprobar, 120_000)
        self.assertTrue(any("por aprobar" in a for a in filas["t001"].alertas))

    def test_carrera_confirmada_no_paga_todavia(self):
        filas = sueldos_del_mes(self.personas, self.cats, [], [evento_base(estado=CONFIRMADO)])
        self.assertEqual(filas, [])

    def test_aviso_tarifa_cero(self):
        acts = [Actividad("t003", date(2026, 10, 1), 1, 2, "x", estado=APROBADA)]
        f = sueldos_del_mes(self.personas, self.cats, acts, [])[0]
        self.assertTrue(any("$0" in a for a in f.alertas))


class Iva(unittest.TestCase):
    def test_desglose(self):
        from motor import desglose
        self.assertEqual(desglose(1_773_100), {"neto": 1_490_000, "iva": 283_100, "total": 1_773_100})
        self.assertEqual(desglose(1_490_000, incluye_iva=False)["total"], 1_773_100)
        self.assertEqual(desglose(500_000, 0), {"neto": 500_000, "iva": 0, "total": 500_000})


class Utilidades(unittest.TestCase):
    def test_validar_actividad(self):
        self.assertTrue(validar_actividad(2, "Reunión", 0)[0])
        self.assertFalse(validar_actividad(0, "Reunión", 0)[0])
        self.assertFalse(validar_actividad(2, "  ", 0)[0])
        self.assertFalse(validar_actividad(5, "x", 12)[0])

    def test_horas_entre(self):
        self.assertEqual(horas_entre("09:00", "11:30"), 2.5)
        self.assertEqual(horas_entre("22:00", "01:00"), 3.0)
        self.assertIsNone(horas_entre("x", "1"))

    def test_formatos(self):
        self.assertEqual(pesos(1234567.4), "$1.234.567")
        self.assertEqual(horas_texto(2.5), "2 h 30 min")
        self.assertEqual(horas_texto(0.25), "15 min")
        self.assertEqual(rango_mes(2026, 12), (date(2026, 12, 1), date(2027, 1, 1)))
        semanas = semanas_del_mes(2026, 10)
        self.assertEqual(semanas[0][:3], [None, None, None])   # oct 2026 parte jueves
        self.assertEqual(semanas[0][3], date(2026, 10, 1))


if __name__ == "__main__":
    unittest.main()
