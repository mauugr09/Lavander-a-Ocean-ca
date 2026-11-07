-- =====================================================================
-- Oceanica Gestion | Migracion 004: columnas y configuracion del backend
-- =====================================================================

-- Distingue las lineas que calcula el sistema de las que captura el administrador,
-- para poder recalcular una nomina sin perder bonos o descuentos manuales.
ALTER TABLE nomina_detalle
  ADD COLUMN automatico TINYINT(1) NOT NULL DEFAULT 0 AFTER monto;

-- Existencia despues de cada movimiento: permite auditar ajustes (que pueden
-- subir o bajar el inventario) sin depender del texto del motivo.
ALTER TABLE movimientos_inventario
  ADD COLUMN existencia_resultante DECIMAL(10,2) NULL AFTER costo_unitario;

INSERT INTO configuracion (clave, valor, descripcion) VALUES
  ('entrega_requiere_pago_total', 'si', 'Si = no se entrega una orden con saldo pendiente (si/no)'),
  ('descuento_max_pct_empleado',  '10', 'Descuento máximo (%) que puede aplicar un empleado; el administrador no tiene límite'),
  ('nomina_jornada_horas',        '8',  'Horas de una jornada completa, para calcular el valor de la hora extra'),
  ('nomina_factor_hora_extra',    '2',  'Multiplo con el que se paga la hora extra (2 = doble)'),
  ('asistencia_paga_justificada', 'si', 'Si = las faltas justificadas cuentan como dia pagado en nomina (si/no)'),
  ('ticket_ancho',               '42', 'Caracteres por linea del ticket (42 para papel de 80 mm, 32 para 58 mm)'),
  ('impresora_ticket',           '',   'Nombre de la impresora de tickets en Windows; vacio = impresora predeterminada');
