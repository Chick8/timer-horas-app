"""Pruebas de los servicios con una base SQLite en memoria. Correr con:  python3 -m unittest discover tests"""
import unittest
from datetime import date, timedelta

import servicios as sv
from motor import APROBADA, DIRECTOR, REALIZADO, RECHAZADA, TECNICO
from tests.conexion_prueba import ConexionPrueba


class Servicios(unittest.TestCase):
    def setUp(self):
        self.c = ConexionPrueba()
        sv.preparar_base(self.c)
        sv.preparar_base(self.c)   # dos veces no duplica

        for cod, nombre, tarifa in (("t001", "Gabriel", 8000), ("t002", "Pedro", 6000)):
            ok, msg = sv.guardar_persona(self.c, {"codigo": cod, "nombre": nombre, "tarifa_hora": tarifa}, True)
            self.assertTrue(ok, msg)
        self.cats = {c.nombre: c.id for c in sv.categorias(self.c).values()}
        self.dia = sv.hoy() - timedelta(days=1)

    def test_actualiza_base_antigua(self):
        from tests.conexion_prueba import ConexionPrueba
        c = ConexionPrueba()
        c.db.execute("alter table eventos drop column tasa_iva")
        sv.preparar_base(c)
        self.assertIn("tasa_iva", {f["name"] for f in c.execute("pragma table_info(eventos)").mappings().all()})

    def test_datos_iniciales(self):
        self.assertGreater(len(self.cats), 10)
        self.assertGreater(len(sv.productos(self.c)), 5)
        self.assertEqual(sv.configuracion(self.c)["pct_empresa"], 50)
        self.assertEqual(sv.siguiente_codigo(self.c), "t003")

    def test_pin_y_bloqueo(self):
        self.assertFalse(sv.asignar_pin(self.c, "t001", "1111", "1111")[0])
        self.assertTrue(sv.asignar_pin(self.c, "t001", "2580", "2580")[0])
        self.assertEqual(sv.personas_para_ingresar(self.c), [("t001", "Gabriel")])
        self.assertTrue(sv.login_persona(self.c, "t001", "2580")[0])
        for _ in range(5):
            ok, msg = sv.login_persona(self.c, "t001", "0000")
        self.assertIn("bloqueado", msg)
        self.assertFalse(sv.login_persona(self.c, "t001", "2580")[0])

    def _carrito(self):
        return [
            {"categoria_id": self.cats["Reunión con cliente"], "horas": 2, "descripcion": "Reu cliente gravel",
             "cliente": "La Minga"},
            {"categoria_id": self.cats["Soldadura y reparación electrónica"], "horas": 1.5,
             "descripcion": "Soldar antena"},
            {"categoria_id": self.cats["Envíos y despachos (Starken, etc.)"], "horas": 0.5,
             "descripcion": "Paquete a Starken"},
        ]

    def test_jornada_carrito_y_revision(self):
        ok, msg = sv.guardar_jornada(self.c, "t001", self.dia, self._carrito())
        self.assertTrue(ok, msg)
        acts = sv.actividades_de_dia(self.c, "t001", self.dia)
        self.assertEqual(sum(a.horas for a in acts), 4.0)
        self.assertEqual(sv.horas_por_dia(self.c, "t001", self.dia.year, self.dia.month)[self.dia], 4.0)

        # La persona puede borrar una pendiente; no una ya aprobada.
        self.assertTrue(sv.anular_mi_actividad(self.c, acts[2].id, "t001")[0])
        sv.revisar(self.c, [acts[0].id], APROBADA, "gabriel")
        self.assertFalse(sv.anular_mi_actividad(self.c, acts[0].id, "t001")[0])
        self.assertFalse(sv.revisar(self.c, [acts[1].id], RECHAZADA, "gabriel")[0])  # falta motivo
        self.assertTrue(sv.revisar(self.c, [acts[1].id], RECHAZADA, "gabriel", "Duplicada")[0])

        f = {x.codigo: x for x in sv.sueldos_mes(self.c, self.dia.year, self.dia.month)}["t001"]
        self.assertEqual(f.horas_aprobadas, 2)
        self.assertEqual(f.monto_horas, 16000)
        self.assertEqual(f.horas_pendientes, 0)
        tabla = sv.tabla_mes(self.c, self.dia.year, self.dia.month)
        self.assertEqual(len(tabla), 2)
        self.assertIn("Reunión con cliente", sv.analisis_mes(self.c, self.dia.year, self.dia.month)["Por categoría"])
        self.assertTrue(sv.a_csv(tabla, "Prueba").startswith(b"\xef\xbb\xbf"))

    def test_jornada_invalida_no_guarda_nada(self):
        malo = self._carrito() + [{"categoria_id": self.cats["Otro"], "horas": 15, "descripcion": "x"}]
        ok, msg = sv.guardar_jornada(self.c, "t001", self.dia, malo)
        self.assertFalse(ok)
        self.assertIn("Actividad 4", msg)
        self.assertEqual(sv.actividades_de_dia(self.c, "t001", self.dia), [])
        self.assertFalse(sv.guardar_jornada(self.c, "t001", sv.hoy() + timedelta(days=5), self._carrito())[0])

    def test_carrera_reparto_y_sueldo(self):
        datos = {"nombre": "Gravel La Minga", "fecha": self.dia, "estado": REALIZADO, "venta_neta": 2_000_000,
                 "base_reparto": "margen", "pct_empresa": 50, "pct_director": 15, "pct_equipo": 35}
        gastos = [{"tipo": "Viáticos", "monto": 300_000}, {"tipo": "Alojamiento", "monto": 200_000},
                  {"tipo": "Otros", "monto": 0}]
        equipo = [{"codigo": "t001", "rol": DIRECTOR, "peso": 1}, {"codigo": "t002", "rol": TECNICO, "peso": 2}]
        ok, msg, eid = sv.guardar_evento(self.c, None, datos, gastos, equipo)
        self.assertTrue(ok, msg)
        ev = next(e for e in sv.eventos(self.c) if e.id == eid)
        self.assertEqual(len(ev.gastos), 2)
        self.assertEqual(ev.tasa_iva, 19)

        # Horas de preparación cargadas a la carrera: se ven como costo interno.
        sv.guardar_jornada(self.c, "t002", self.dia, [{
            "categoria_id": self.cats["Armado de mochilas / kits de carrera"], "horas": 3,
            "descripcion": "Kits", "evento_id": eid}])
        r = sv.resumen_evento(self.c, ev)
        self.assertEqual(r["reparto"].margen, 1_500_000)
        self.assertEqual(r["reparto"].monto_director, 225_000)
        self.assertEqual(r["horas_internas"], 3)
        self.assertEqual(r["costo_horas_internas"], 18_000)

        self.assertEqual(len(sv.carreras_por_aprobar(self.c)), 1)
        filas = {f.codigo: f for f in sv.sueldos_mes(self.c, self.dia.year, self.dia.month, pct_retencion=0)}
        self.assertEqual(filas["t001"].monto_carreras, 0)
        self.assertEqual(filas["t001"].monto_carreras_por_aprobar, 225_000)
        self.assertTrue(sv.aprobar_honorarios_carrera(self.c, eid, "admin")[0])
        self.assertEqual(sv.carreras_por_aprobar(self.c), [])
        filas = {f.codigo: f for f in sv.sueldos_mes(self.c, self.dia.year, self.dia.month, pct_retencion=0)}
        self.assertEqual(filas["t001"].monto_carreras, 225_000)
        self.assertEqual(filas["t002"].monto_carreras, 525_000)

        # Guardar sin cambios mantiene la aprobación; cambiar el reparto la quita
        self.assertNotIn("por aprobar", sv.guardar_evento(self.c, eid, datos, gastos, equipo)[1])
        datos["pct_director"], datos["pct_equipo"] = 20, 30
        ok, msg, _ = sv.guardar_evento(self.c, eid, datos, gastos, equipo)
        self.assertIn("por aprobar", msg)
        self.assertEqual(len(sv.carreras_por_aprobar(self.c)), 1)
        # Editar: porcentajes que no suman 100 se rechazan
        datos["pct_equipo"] = 40
        self.assertFalse(sv.guardar_evento(self.c, eid, datos, gastos, equipo)[0])

    def test_configuracion(self):
        ok, _ = sv.guardar_configuracion(self.c, {"pct_empresa": 60, "pct_director": 10, "pct_equipo": 30,
                                                  "base_reparto": "margen", "pct_retencion": 15.25})
        self.assertTrue(ok)
        self.assertEqual(sv.configuracion(self.c)["pct_empresa"], 60)
        self.assertFalse(sv.guardar_configuracion(self.c, {"pct_empresa": 60, "pct_director": 10, "pct_equipo": 10,
                                                           "base_reparto": "margen", "pct_retencion": 0})[0])

    def test_categoria_especial(self):
        ok, _ = sv.guardar_categoria(self.c, {"nombre": "Soldadura avanzada", "grupo": "Taller",
                                              "tarifa_hora_especial": 12000})
        self.assertTrue(ok)
        self.assertFalse(sv.guardar_categoria(self.c, {"nombre": "soldadura avanzada"})[0])


if __name__ == "__main__":
    unittest.main()


class EditarYBorrar(unittest.TestCase):
    def setUp(self):
        self.c = ConexionPrueba()
        sv.preparar_base(self.c)
        sv.guardar_persona(self.c, {"codigo": "t001", "nombre": "Gabriel", "tarifa_hora": 1000}, True)
        self.cats = {c.nombre: c.id for c in sv.categorias(self.c).values()}
        self.dia = sv.hoy() - timedelta(days=2)

    def test_editar_actividad(self):
        sv.guardar_jornada(self.c, "t001", self.dia, [{"categoria_id": self.cats["Otro"], "horas": 2, "descripcion": "x"}])
        a = sv.actividades_de_dia(self.c, "t001", self.dia)[0]
        nuevo = {"fecha": self.dia, "categoria_id": self.cats["Reunión con cliente"], "horas": 3, "descripcion": "Reu"}
        self.assertTrue(sv.editar_actividad(self.c, a.id, nuevo, "t001")[0])
        a = sv.actividades_de_dia(self.c, "t001", self.dia)[0]
        self.assertEqual((a.horas, a.descripcion), (3, "Reu"))
        self.assertFalse(sv.editar_actividad(self.c, a.id, dict(nuevo, horas=17), "t001")[0])
        sv.revisar(self.c, [a.id], APROBADA, "admin")
        self.assertFalse(sv.editar_actividad(self.c, a.id, nuevo, "t001")[0])   # persona no puede
        self.assertTrue(sv.editar_actividad(self.c, a.id, dict(nuevo, horas=4))[0])  # admin sí

    def test_borrar_carrera(self):
        ok, _, eid = sv.guardar_evento(self.c, None, {"nombre": "Ejemplo", "estado": "realizado", "venta_neta": 100,
                                                      "base_reparto": "margen", "pct_empresa": 50, "pct_director": 15,
                                                      "pct_equipo": 35}, [{"tipo": "Otros", "monto": 10}],
                                       [{"codigo": "t001", "rol": "director", "peso": 1}])
        sv.guardar_jornada(self.c, "t001", self.dia, [{"categoria_id": self.cats["Otro"], "horas": 1,
                                                        "descripcion": "prep", "evento_id": eid}])
        self.assertTrue(sv.eliminar_evento(self.c, eid)[0])
        self.assertEqual(sv.eventos(self.c), [])
        self.assertIsNone(sv.actividades_de_dia(self.c, "t001", self.dia)[0].evento_id)
        self.assertTrue(sv.borrar_datos_de_prueba(self.c)[0])
        self.assertEqual(sv.actividades_de_dia(self.c, "t001", self.dia), [])


class Funciones(unittest.TestCase):
    def test_ponderacion_desde_nivel_y_manual(self):
        c = ConexionPrueba()
        sv.preparar_base(c)
        for cod in ("t001", "t002", "t003"):
            sv.guardar_persona(c, {"codigo": cod, "nombre": cod, "tarifa_hora": 0}, True)
        self.assertEqual(len(sv.lista_funciones(c)), 9)
        ok, _, eid = sv.guardar_evento(c, None, {"nombre": "X", "estado": "realizado", "venta_neta": 1_000_000,
                                                 "base_reparto": "margen", "pct_empresa": 65, "pct_director": 0,
                                                 "pct_equipo": 35}, [], [
            {"codigo": "t001", "rol": "tecnico", "peso": 1, "funcion": "Meta – cronometraje principal"},   # 1,5
            {"codigo": "t002", "rol": "tecnico", "peso": 1, "funcion": "Apoyo en meta (respaldo)"},        # 0,7
            {"codigo": "t003", "rol": "tecnico", "peso": 1, "funcion": "Partida", "factor": 1.8}])          # manual
        self.assertTrue(ok)
        ev = sv.eventos(c)[0]
        self.assertEqual([i.factor for i in ev.equipo], [1.5, 0.7, 1.8])
        ok, _ = sv.guardar_funciones(c, [{"nombre": "Meta – cronometraje principal", "nivel": 1},
                                         {"nombre": "Apoyo en meta (respaldo)", "nivel": 3}],
                                     {"factor_nivel1": 2, "factor_nivel2": 1, "factor_nivel3": 0.5})
        self.assertTrue(ok)
        ev = sv.eventos(c)[0]
        self.assertEqual([i.factor for i in ev.equipo], [2.0, 0.5, 1.8])
        self.assertFalse(sv.guardar_funciones(c, [{"nombre": "A", "nivel": 4}],
                                              {"factor_nivel1": 2, "factor_nivel2": 1, "factor_nivel3": 0.5})[0])


class EdicionEnTabla(unittest.TestCase):
    def test_todo_o_nada(self):
        c = ConexionPrueba()
        sv.preparar_base(c)
        sv.guardar_persona(c, {"codigo": "t001", "nombre": "G", "tarifa_hora": 0}, True)
        cats = {x.nombre: x.id for x in sv.categorias(c).values()}
        dia = sv.hoy() - timedelta(days=1)
        sv.guardar_jornada(c, "t001", dia, [{"categoria_id": cats["Otro"], "horas": 1, "descripcion": "a"},
                                            {"categoria_id": cats["Otro"], "horas": 2, "descripcion": "b"}])
        a, b = sv.actividades_de_dia(c, "t001", dia)
        ok, msg, _ = sv.guardar_cambios_tabla(c, [{"id": a.id, "fecha": dia, "categoria_id": cats["Partida"] if "Partida" in cats else cats["Otro"],
                                                   "horas": 1.5, "descripcion": "a2"}], [b.id], "t001")
        self.assertTrue(ok)
        acts = sv.actividades_de_dia(c, "t001", dia)
        self.assertEqual([(x.horas, x.descripcion) for x in acts], [(1.5, "a2")])
        with self.assertRaises(sv.CambiosRechazados):
            sv.guardar_cambios_tabla(c, [{"id": a.id, "fecha": dia, "categoria_id": cats["Otro"], "horas": 30,
                                          "descripcion": "x"}], [], "t001")
