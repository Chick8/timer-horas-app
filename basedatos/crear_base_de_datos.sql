-- =====================================================================
--  HORAS TIMER — Registro de actividades, sueldos y reparto de carreras
--  Crea todas las tablas en Supabase (PostgreSQL).
--
--  CÓMO USARLO: Supabase → SQL Editor → New query → pegar TODO este
--  archivo → botón "Run". Se puede correr más de una vez sin problema
--  (no duplica nada ni borra datos).
--
--  Las categorías, líneas de producto y la configuración inicial NO van
--  aquí: la app las carga sola la primera vez que se abre.
--
--  Al final debe aparecer una tablita con todas las tablas y
--  "seguridad_activada" en cada una.
-- =====================================================================


-- 1. CONFIGURACIÓN GENERAL (una sola fila) ----------------------------
create table if not exists configuracion (
  id              smallint primary key default 1 check (id = 1),
  nombre_empresa  text not null default 'TIMER',
  zona_horaria    text not null default 'America/Santiago',
  pct_retencion   real not null default 15.25 check (pct_retencion between 0 and 100),
  base_reparto    text not null default 'margen' check (base_reparto in ('margen', 'venta')),
  pct_empresa     real not null default 50 check (pct_empresa between 0 and 100),
  pct_director    real not null default 15 check (pct_director between 0 and 100),
  pct_equipo      real not null default 35 check (pct_equipo between 0 and 100),
  actualizado_en  timestamptz not null default now()
);


-- 2. PERSONAS DEL EQUIPO ----------------------------------------------
create table if not exists personas (
  codigo            text primary key,                        -- ej. t001
  nombre            text not null check (length(trim(nombre)) > 0),
  cargo             text not null default '',
  tarifa_hora       numeric(10,0) not null default 0 check (tarifa_hora >= 0),   -- CLP
  activo            boolean not null default true,
  pin_hash          text,
  intentos_fallidos smallint not null default 0,
  bloqueado_hasta   timestamptz,
  creado_en         timestamptz not null default now()
);


-- 3. CATEGORÍAS DE ACTIVIDAD (qué tipo de trabajo fue) -----------------
create table if not exists categorias (
  id                   bigint generated always as identity primary key,
  nombre               text not null unique,
  grupo                text not null default '',
  pagable_por_hora     boolean not null default true,   -- false = se paga por reparto de carrera
  tarifa_hora_especial numeric(10,0),                   -- vacío = usa la tarifa de la persona
  activo               boolean not null default true,
  orden                smallint not null default 0
);


-- 4. LÍNEAS DE PRODUCTO (running, trail, ciclismo...) ------------------
create table if not exists productos (
  id      bigint generated always as identity primary key,
  nombre  text not null unique,
  activo  boolean not null default true,
  orden   smallint not null default 0
);


-- 5. CARRERAS / EVENTOS (con su cotización y reglas de reparto) ---------
create table if not exists eventos (
  id            bigint generated always as identity primary key,
  nombre        text not null check (length(trim(nombre)) > 0),
  fecha         date,
  cliente       text not null default '',
  producto_id   bigint references productos(id),
  estado        text not null default 'cotizado'
                  check (estado in ('cotizado', 'confirmado', 'realizado', 'pagado', 'perdido')),
  venta_neta    numeric(12,0) not null default 0 check (venta_neta >= 0),   -- CLP sin IVA
  tasa_iva      real not null default 19,          -- 19 = factura afecta, 0 = exenta
  base_reparto  text not null default 'margen' check (base_reparto in ('margen', 'venta')),
  pct_empresa   real not null default 50,
  pct_director  real not null default 15,
  pct_equipo    real not null default 35,
  hubspot_deal  text not null default '',          -- enlace o ID del negocio en HubSpot
  notas         text not null default '',
  creado_en     timestamptz not null default now()
);

-- (si la tabla ya existía de antes, esto le agrega la columna del IVA)
alter table eventos add column if not exists tasa_iva real not null default 19;

create table if not exists evento_gastos (
  id           bigint generated always as identity primary key,
  evento_id    bigint not null references eventos(id) on delete cascade,
  tipo         text not null,
  descripcion  text not null default '',
  monto        numeric(12,0) not null default 0 check (monto >= 0)
);

create table if not exists evento_equipo (
  id         bigint generated always as identity primary key,
  evento_id  bigint not null references eventos(id) on delete cascade,
  codigo     text not null references personas(codigo),
  rol        text not null default 'tecnico' check (rol in ('director', 'tecnico', 'apoyo')),
  peso       real not null default 1 check (peso >= 0)
);


-- 5b. FACTURAS de cada carrera (anticipo 50 %, saldo, o 100 %) -------
create table if not exists facturas (
  id               bigint generated always as identity primary key,
  evento_id        bigint not null references eventos(id),
  numero           text not null default '',
  fecha            date,
  cliente          text not null default '',
  rut_cliente      text not null default '',
  descripcion      text not null default '',
  neto             numeric(12,0) not null default 0 check (neto >= 0),
  iva              numeric(12,0) not null default 0 check (iva >= 0),
  total            numeric(12,0) not null default 0 check (total >= 0),
  pagada           boolean not null default false,
  fecha_pago       date,
  archivo_nombre   text,
  archivo          bytea,                    -- el PDF de la factura
  anulada          boolean not null default false,
  creado_en        timestamptz not null default now()
);
create index if not exists facturas_por_evento on facturas (evento_id);


-- 5c. BOLETAS DE HONORARIOS por carrera (una por persona y carrera) ----
create table if not exists boletas (
  id             bigint generated always as identity primary key,
  evento_id      bigint not null references eventos(id) on delete cascade,
  codigo         text not null references personas(codigo),
  estado         text not null default 'pendiente'
                   check (estado in ('pendiente', 'solicitada', 'recibida', 'pagada')),
  numero         text not null default '',
  monto_bruto    numeric(12,0) not null default 0,
  archivo_nombre text,
  archivo        bytea,
  actualizado_en timestamptz not null default now(),
  unique (evento_id, codigo)
);

-- Columnas agregadas después de la primera versión
alter table personas      add column if not exists email text not null default '';
alter table personas      add column if not exists telefono text not null default '';
alter table configuracion add column if not exists razon_social text not null default 'Grupo Tecnológico Alameda SpA';
alter table configuracion add column if not exists rut_empresa text not null default '76.415.603-K';
alter table configuracion add column if not exists direccion_empresa text not null default 'Huérfanos 1055 dp 503, Santiago';
alter table configuracion add column if not exists email_finanzas text not null default 'finanzas@timer-crono.com';
alter table configuracion add column if not exists dias_pago integer not null default 5;


-- 5d. FUNCIONES dentro de una carrera (meta, partida, apoyo...) y su nivel --
--     Nivel 1 / 2 / 3 = los tres rangos de pago; la ponderación de cada nivel está en configuracion.
create table if not exists funciones (
  id      bigint generated always as identity primary key,
  nombre  text not null unique,
  nivel   smallint not null default 2 check (nivel between 1 and 3),
  activo  boolean not null default true,
  orden   smallint not null default 0
);
alter table configuracion add column if not exists factor_nivel1 real not null default 1.5;
alter table configuracion add column if not exists factor_nivel2 real not null default 1.0;
alter table configuracion add column if not exists factor_nivel3 real not null default 0.7;
alter table evento_equipo add column if not exists funcion text not null default '';
alter table evento_equipo add column if not exists factor real;
alter table eventos add column if not exists honorarios_aprobados boolean not null default false;
alter table eventos add column if not exists aprobado_por text;
alter table eventos add column if not exists aprobado_en text;


-- 6. ACTIVIDADES (cada línea del "carrito" de una jornada) --------------
--    Nunca se borran: si una está mal, se ANULA y queda registro.
create table if not exists actividades (
  id              bigint generated always as identity primary key,
  codigo          text not null references personas(codigo),
  fecha           date not null,
  categoria_id    bigint not null references categorias(id),
  producto_id     bigint references productos(id),
  evento_id       bigint references eventos(id),
  cliente         text not null default '',
  descripcion     text not null check (length(trim(descripcion)) > 0),
  horas           numeric(5,2) not null check (horas > 0 and horas <= 16),
  hora_inicio     text,
  hora_fin        text,
  estado          text not null default 'pendiente'
                    check (estado in ('pendiente', 'aprobada', 'rechazada')),
  motivo_revision text not null default '',
  revisado_por    text,
  revisado_en     timestamptz,
  anulada         boolean not null default false,
  etiqueta        text not null default '',
  carrera_texto   text not null default '',
  creado_por      text not null default 'persona',
  creado_en       timestamptz not null default now()
);
create index if not exists actividades_por_persona on actividades (codigo, fecha);
create index if not exists actividades_por_fecha   on actividades (fecha);
create index if not exists actividades_por_evento  on actividades (evento_id);

create or replace function impedir_borrado() returns trigger
language plpgsql set search_path = public as $$
begin
  raise exception 'No se permite borrar registros de %: use "anular" en su lugar.', tg_table_name;
end $$;

drop trigger if exists actividades_no_borrar on actividades;
create trigger actividades_no_borrar before delete on actividades
  for each row execute function impedir_borrado();


-- 7. SEGURIDAD ----------------------------------------------------------
--    Row Level Security sin reglas públicas: nadie entra con las llaves
--    públicas de Supabase. Solo la app (con la contraseña de la base de
--    datos, guardada en secreto) puede leer y escribir.
alter table configuracion  enable row level security;
alter table personas       enable row level security;
alter table categorias     enable row level security;
alter table productos      enable row level security;
alter table eventos        enable row level security;
alter table evento_gastos  enable row level security;
alter table evento_equipo  enable row level security;
alter table actividades    enable row level security;
alter table facturas       enable row level security;
alter table boletas        enable row level security;
alter table funciones      enable row level security;

create table if not exists escenarios (
  id          bigint generated always as identity primary key,
  nombre      text not null,
  codigo      text,
  parametros  text not null default '{}',
  excluidas   text not null default '[]',
  creado_por  text not null default '',
  creado_en   timestamptz not null default now()
);
alter table escenarios     enable row level security;


-- 8. VERIFICACIÓN ---------------------------------------------------------
select c.relname as tabla,
       case when c.relrowsecurity then 'seguridad_activada' else 'SIN SEGURIDAD' end as seguridad
from pg_class c
where c.relnamespace = 'public'::regnamespace and c.relkind = 'r'
order by c.relname;
