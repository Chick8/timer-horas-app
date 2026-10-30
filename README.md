# Horas TIMER — actividades, sueldos y reparto de carreras

App web para que cada persona de TIMER registre **qué hizo y cuántas horas**, día por día, y para que la administración calcule **cuánto pagarle a cada uno**: por horas y por su parte en las carreras.

Está construida sobre la misma base que la app de asistencia (`~/asistencia_app`): mismo PIN cifrado, misma seguridad y misma forma de trabajar (Streamlit + Supabase). **Es otra app, separada**: no comparte código ni datos con la del restaurante.

## Qué hace

**Cada persona** (la dirección normal):
1. Elige su nombre y escribe su PIN.
2. **Registro de jornada**: elige el día en el calendario y va armando un **carrito** con las actividades de ese día. Cada actividad tiene: tipo de actividad, descripción, horas (o «desde–hasta»), y opcionalmente línea de producto, carrera y cliente. Por ejemplo: *2 h reunión con cliente → 1 h 30 min probar equipos y armar mochilas → 45 min soldar antena → 30 min paquete a Starken*. Al final aprieta **Guardar jornada** y se guarda todo junto.
3. **Carga masiva de horas**: una tabla tipo Excel para cargar muchos días de una vez (por ejemplo, horas atrasadas). También se puede descargar la plantilla Excel, llenarla y subirla. La planilla puede traer las columnas opcionales **Carrera** (aunque la carrera no esté creada) y **Etiqueta**. Si se sube dos veces el mismo archivo, las filas iguales (mismo día, descripción y horas) no se duplican.
4. **Resumen de horas**: horas y valor estimado entre dos fechas (por ejemplo, desde abril), por mes y por tipo de actividad.
4b. **Consolidados y simulador**: junta las horas por día, semana, mes, trimestre o año, agrupadas por tipo de actividad, carrera, cliente, etiqueta, etc. Arriba se elige **qué entra al sueldo** (dejar fuera etiquetas, carreras o tipos, o marcar actividad por actividad) y el total —bruto, líquido, boleta mensual equivalente y horas por semana— cambia al instante. Cada versión se guarda como **escenario** para compararlas (ej. «Mi propuesta» vs «Feedback JC»). Incluye «Cuánto toma cada tarea» (promedio y mediana por tipo) y descarga en Excel. Las etiquetas que empiezan con «B ·» o «X ·» quedan fuera por defecto.
5. **Mis honorarios**: las carreras en que participó, con su monto bruto, retención y líquido, y el estado de su boleta de honorarios. Desde ahí puede subir su boleta (N° y PDF).
6. **Mi calendario**: calendario con sus horas por día, cuántas están aprobadas o por revisar, y una estimación de lo que lleva ganado.

**Administración** (la misma dirección terminada en `?modo=admin`):
- **Aprobación de horas**: aprobar las horas (una por una, varias o todas) o rechazarlas con un motivo.
- **Liquidación mensual**: por persona, horas aprobadas × tarifa + su parte de las carreras realizadas, menos la retención de boleta de honorarios. Se puede descargar para abrir en Excel.
- **Consolidados y simulador**: lo mismo que ve cada persona, pero para una persona o para todo el equipo.
- **Registro de horas**: horas del mes por persona, por grupo (Comercial, Taller, Logística…), por categoría y por línea de producto. Así se ve en qué se va el tiempo del equipo.
- **Carreras y Honorarios**: cada carrera con su venta neta, sus gastos (viáticos, transporte, alojamiento, chips…) y su equipo. Calcula el margen y lo reparte por porcentajes entre **empresa / director de carrera / equipo TIMER**. Sirve también para **simular una cotización** antes de enviarla.
- **Pagos al equipo y boletas** (dentro de cada carrera «Realizado»): cuánto le toca a cada persona y el correo listo para pedirle su boleta de honorarios (se abre en tu programa de correo), con el seguimiento: por solicitar → solicitada → recibida → pagada.
- **Personas**: tarifas, PIN y altas; también se pueden **cargar horas por otra persona** (cuando alguien las manda por WhatsApp).
- **Configuración**: categorías de actividad, líneas de producto, porcentajes por defecto y retención.

## Cómo se calcula

**Pago por horas** = horas *aprobadas* × tarifa por hora de la persona. Una categoría puede tener una **tarifa especial** (por ejemplo, soldadura más cara) que reemplaza la de la persona.

**IVA de la venta**: en la carrera puedes escribir directamente **lo que el cliente transfirió** (total con IVA) y la app separa el IVA (19 %, se paga al SII) del **neto**, que es lo que realmente es de TIMER. Si la factura es exenta, elige «Factura exenta» y no se descuenta IVA. Ejemplo: transferencia de $1.773.100 → IVA $283.100 → neto $1.490.000.

**Facturas de la carrera**: en «Carreras y Honorarios» → «📄 Registrar factura (PDF)» subes el PDF de la factura que emitió TIMER y la app lee N°, fecha, cliente, RUT, neto, IVA y total (revísalos antes de guardar). Indicas si esa factura es el 100 %, el 50 % (anticipo o saldo) u otro porcentaje de la carrera: con eso crea la carrera con su valor total, o la suma a una carrera existente. En cada carrera se ve cuánto está **facturado**, cuánto **pagó el cliente** y cuánto falta por facturar, y se puede descargar el PDF.

**Reparto de una carrera** (todo en pesos netos, sin IVA):
```
margen   = venta neta − gastos (viáticos, transporte, alojamiento, chips, …)
empresa  = margen × % empresa
director = margen × % director          → al/los director(es) de esa carrera
equipo   = margen × % equipo            → entre técnicos y apoyo, según jornadas trabajadas
```
Los porcentajes por defecto (**50 / 15 / 35**) son un punto de partida: **hay que definirlos con el equipo**. Se cambian en Ajustes, y cada carrera puede tener los suyos. También se puede calcular sobre la venta neta en vez del margen.

**Ponderación por función**: dentro de una carrera no todas las funciones pesan lo mismo. Cada función (Meta, Partida, Apoyo en meta, Coordinación del equipo…) pertenece a un **nivel 1, 2 o 3** (los tres rangos de pago), y cada nivel tiene una ponderación (por defecto ×1,5 / ×1 / ×0,7). La parte del equipo se reparte según **jornadas × ponderación**. Se activa en cada carrera con «Ponderar por función»; las funciones y ponderaciones se editan en Configuración, y en un caso especial se puede escribir la ponderación a mano.

Para **no pagar dos veces**, las categorías «Traslado / viaje a carrera» y «Montaje y cronometraje en carrera» vienen marcadas como *se paga por reparto*: sus horas se registran (para ver el esfuerzo real) pero no suman al pago por hora. Se puede cambiar en Ajustes.

Si alguien carga horas de preparación a una carrera (armar kits, codificar chips…), la pantalla de la carrera muestra ese costo y **lo que realmente le queda a la empresa**.

Solo las carreras en estado **Realizado** o **Pagado** entran al sueldo del mes. Las cotizadas o confirmadas se ven como estimación.

**Retención**: 15,25 % (boleta de honorarios 2026). Se puede cambiar o poner en 0.

## Probarla en tu Mac (modo prueba local, sin Supabase)

Abre la Terminal y haz cada paso en orden.

**Paso 1 — Instalar los paquetes (una sola vez):**
```bash
cd ~/timer_horas_app
python3 -m pip install -r requirements.txt
```

**Paso 2 — Abrir la app:**
```bash
streamlit run app.py
```
Se abre el navegador. Como todavía no hay datos de Supabase, arranca en **modo prueba local**: los datos quedan en la carpeta `datos_local` de este Mac.
- Personas de ejemplo: Gabriel, Pedro y Juan Carlos, todos con PIN **2580**.
- Administración: botón «Administración» abajo, usuario **admin**, contraseña **timer**.
- En «Carreras y Honorarios» hay un botón para cargar una carrera de ejemplo.

Para parar la app: en la Terminal, **Ctrl + C**. Para empezar de cero, borra la carpeta `datos_local`.

**Pruebas automáticas** (revisan los cálculos):
```bash
python3 -m unittest discover tests
```

## Pasarla a la nube (para que todo el equipo la use desde el celular)

1. En Supabase crea un **proyecto nuevo** (por ejemplo «timer-horas»; región São Paulo). Guarda la contraseña de la base de datos.
2. Supabase → SQL Editor → New query → pega todo `basedatos/crear_base_de_datos.sql` → **Run**.
3. En la Terminal: `python3 crear_secretos.py` (te pregunta los datos de Supabase y tu contraseña de administración).
4. `python3 probar_conexion.py` → debe terminar en **TODO OK**.
5. `streamlit run app.py` → ya no aparece el aviso de modo prueba. Las categorías y productos se cargan solos.
6. Subir a GitHub y Streamlit Cloud (igual que la app de asistencia) y pegar el contenido de `secrets.toml` en Settings → Secrets.

## Qué hay en esta carpeta

```
timer_horas_app/
├── app.py                  ← la app (pantallas del equipo y de administración)
├── servicios.py            ← lo que hace la app por dentro (sin pantallas)
├── seguridad.py            ← cifrado de PIN y contraseñas
├── crear_secretos.py       ← crea el archivo secreto haciéndote preguntas
├── probar_conexion.py      ← revisa que el Mac llegue a Supabase
├── motor/                  ← las cuentas: sueldos, reparto de carreras, formatos
├── basedatos/
│   ├── crear_base_de_datos.sql  ← tablas para Supabase
│   ├── esquema_local.sql        ← las mismas tablas para el modo prueba
│   ├── datos_iniciales.py       ← categorías y productos de partida
│   └── repositorio.py           ← consultas a la base de datos
├── assets/                 ← logos TIMER / TMR
├── tests/                  ← pruebas automáticas
└── .streamlit/             ← colores de la app (y el archivo secreto, que no se comparte)
```

## Pendiente / ideas siguientes

- Definir con el equipo los porcentajes de reparto y las tarifas por hora de cada persona.
- Cerrar el mes (bloquear cambios una vez pagado), como en la app de asistencia.
- Traer las carreras directamente desde los negocios ganados en HubSpot.
- Descargar la liquidación de cada persona en PDF.
