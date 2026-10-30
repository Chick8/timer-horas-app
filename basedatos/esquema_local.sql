-- Misma estructura que crear_base_de_datos.sql, pero para el MODO PRUEBA LOCAL (SQLite).
-- La app lo usa sola cuando no hay datos de Supabase en .streamlit/secrets.toml.
-- Si cambias una tabla aquí, cámbiala también en crear_base_de_datos.sql.

create table if not exists configuracion (
  id              integer primary key default 1 check (id = 1),
  nombre_empresa  text not null default 'TIMER',
  zona_horaria    text not null default 'America/Santiago',
  pct_retencion   real not null default 15.25,
  base_reparto    text not null default 'margen',
  pct_empresa     real not null default 50,
  pct_director    real not null default 15,
  pct_equipo      real not null default 35,
  actualizado_en  text not null default current_timestamp
);

create table if not exists personas (
  codigo            text primary key,
  nombre            text not null,
  cargo             text not null default '',
  tarifa_hora       real not null default 0,
  activo            integer not null default 1,
  pin_hash          text,
  intentos_fallidos integer not null default 0,
  bloqueado_hasta   text,
  creado_en         text not null default current_timestamp
);

create table if not exists categorias (
  id                   integer primary key autoincrement,
  nombre               text not null unique,
  grupo                text not null default '',
  pagable_por_hora     integer not null default 1,
  tarifa_hora_especial real,
  activo               integer not null default 1,
  orden                integer not null default 0
);

create table if not exists productos (
  id      integer primary key autoincrement,
  nombre  text not null unique,
  activo  integer not null default 1,
  orden   integer not null default 0
);

create table if not exists eventos (
  id            integer primary key autoincrement,
  nombre        text not null,
  fecha         text,
  cliente       text not null default '',
  producto_id   integer references productos(id),
  estado        text not null default 'cotizado',
  venta_neta    real not null default 0,
  tasa_iva      real not null default 19,
  honorarios_aprobados boolean not null default false,
  aprobado_por  text,
  aprobado_en   text,
  base_reparto  text not null default 'margen',
  pct_empresa   real not null default 50,
  pct_director  real not null default 15,
  pct_equipo    real not null default 35,
  hubspot_deal  text not null default '',
  notas         text not null default '',
  creado_en     text not null default current_timestamp
);

create table if not exists evento_gastos (
  id           integer primary key autoincrement,
  evento_id    integer not null references eventos(id) on delete cascade,
  tipo         text not null,
  descripcion  text not null default '',
  monto        real not null default 0
);

create table if not exists evento_equipo (
  id         integer primary key autoincrement,
  evento_id  integer not null references eventos(id) on delete cascade,
  codigo     text not null references personas(codigo),
  rol        text not null default 'tecnico',
  peso       real not null default 1,
  funcion    text not null default '',
  factor     real
);

create table if not exists facturas (
  id               integer primary key autoincrement,
  evento_id        integer not null references eventos(id),
  numero           text not null default '',
  fecha            text,
  cliente          text not null default '',
  rut_cliente      text not null default '',
  descripcion      text not null default '',
  neto             real not null default 0,
  iva              real not null default 0,
  total            real not null default 0,
  pagada           integer not null default 0,
  fecha_pago       text,
  archivo_nombre   text,
  archivo          blob,
  anulada          integer not null default 0,
  creado_en        text not null default current_timestamp
);
create index if not exists facturas_por_evento on facturas (evento_id);

create table if not exists boletas (
  id             integer primary key autoincrement,
  evento_id      integer not null references eventos(id) on delete cascade,
  codigo         text not null references personas(codigo),
  estado         text not null default 'pendiente',
  numero         text not null default '',
  monto_bruto    real not null default 0,
  archivo_nombre text,
  archivo        blob,
  actualizado_en text not null default current_timestamp,
  unique (evento_id, codigo)
);

create table if not exists funciones (
  id      integer primary key autoincrement,
  nombre  text not null unique,
  nivel   integer not null default 2,
  activo  integer not null default 1,
  orden   integer not null default 0
);

create table if not exists actividades (
  id              integer primary key autoincrement,
  codigo          text not null references personas(codigo),
  fecha           text not null,
  categoria_id    integer not null references categorias(id),
  producto_id     integer references productos(id),
  evento_id       integer references eventos(id),
  cliente         text not null default '',
  descripcion     text not null,
  horas           real not null check (horas > 0 and horas <= 16),
  hora_inicio     text,
  hora_fin        text,
  estado          text not null default 'pendiente',
  motivo_revision text not null default '',
  revisado_por    text,
  revisado_en     text,
  anulada         integer not null default 0,
  etiqueta        text not null default '',
  carrera_texto   text not null default '',
  creado_por      text not null default 'persona',
  creado_en       text not null default current_timestamp
);
create index if not exists actividades_por_persona on actividades (codigo, fecha);
create index if not exists actividades_por_evento  on actividades (evento_id);

create table if not exists escenarios (
  id          integer primary key autoincrement,
  nombre      text not null,
  codigo      text,
  parametros  text not null default '{}',
  excluidas   text not null default '[]',
  creado_por  text not null default '',
  creado_en   text not null default (datetime('now'))
);
