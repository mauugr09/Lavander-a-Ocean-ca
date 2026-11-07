-- =====================================================================
-- Oceanica Gestion | Migracion 003: catalogos y configuracion inicial
-- No se inventan precios ni clientes: se cargan despues desde Excel/CSV.
-- El usuario administrador lo crea el instalador (init_db.py), con la
-- contrasena que elija el dueño; nunca hay credenciales fijas en el codigo.
-- =====================================================================

INSERT INTO roles (nombre, descripcion) VALUES
  ('administrador', 'Acceso total: usuarios, sueldos, nomina, reportes y respaldos'),
  ('empleado', 'Ordenes, clientes, cobros e inventario; sin sueldos ni nomina');

INSERT INTO metodos_pago (nombre, es_efectivo) VALUES
  ('Efectivo', 1),
  ('Tarjeta', 0),
  ('Transferencia', 0);

INSERT INTO categorias_servicio (nombre) VALUES
  ('Lavado por kilo'),
  ('Planchado'),
  ('Edredones y cobijas'),
  ('Tintorería'),
  ('Otros');

INSERT INTO categorias_insumo (nombre) VALUES
  ('Detergentes y suavizantes'),
  ('Empaque y bolsas'),
  ('Ganchos y etiquetas'),
  ('Limpieza y mantenimiento'),
  ('Otros');

INSERT INTO conceptos_nomina (clave, nombre, tipo) VALUES
  ('SUELDO',   'Sueldo base',        'percepcion'),
  ('HEXTRA',   'Horas extra',        'percepcion'),
  ('BONO',     'Bono',               'percepcion'),
  ('OTRAPERC', 'Otra percepción',    'percepcion'),
  ('FALTA',    'Descuento por falta','deduccion'),
  ('RETARDO',  'Descuento por retardo','deduccion'),
  ('DESCMAN',  'Descuento manual',   'deduccion');

INSERT INTO configuracion (clave, valor, descripcion) VALUES
  ('negocio_nombre',        'Lavandería Oceánica', 'Nombre que aparece en tickets y reportes'),
  ('negocio_telefono',      '',                    'Teléfono para el ticket'),
  ('negocio_direccion',     '',                    'Dirección para el ticket'),
  ('ticket_pie',            'Gracias por su preferencia', 'Texto al pie del ticket'),
  ('folio_prefijo',         'OC',                  'Prefijo del folio de órdenes'),
  ('dias_entrega_default',  '2',                   'Días para la fecha promesa por omisión'),
  ('hora_entrada_tolerancia_min', '10',            'Minutos de tolerancia antes de contar retardo'),
  ('respaldo_hora',         '21:00',               'Hora del respaldo automático diario'),
  ('respaldo_retencion_dias','30',                 'Días que se conservan los respaldos locales'),
  ('respaldo_ruta_externa', '',                    'Carpeta del disco externo o USB para la copia');
