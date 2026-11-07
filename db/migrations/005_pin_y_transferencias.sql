-- =====================================================================
-- Oceanica Gestion | Migracion 005: PIN por empleado y transferencias por confirmar
-- Compatible con MariaDB 10.3+ y MySQL 5.7+/8.
-- =====================================================================

-- PIN de 4 a 6 digitos para cobrar y registrar llegada en el mostrador.
ALTER TABLE usuarios
  ADD COLUMN pin_hash VARCHAR(100) NULL AFTER password_hash;

-- Los metodos que no se pueden verificar al momento (transferencia) quedan "por confirmar".
ALTER TABLE metodos_pago
  ADD COLUMN requiere_confirmacion TINYINT(1) NOT NULL DEFAULT 0 AFTER es_efectivo;

UPDATE metodos_pago SET requiere_confirmacion = 1 WHERE nombre = 'Transferencia';

ALTER TABLE pagos
  ADD COLUMN estado_confirmacion ENUM('confirmado','pendiente','rechazado') NOT NULL DEFAULT 'confirmado' AFTER referencia,
  ADD COLUMN confirmado_por INT UNSIGNED NULL AFTER estado_confirmacion,
  ADD COLUMN confirmado_en DATETIME NULL AFTER confirmado_por,
  ADD KEY ix_pagos_confirmacion (estado_confirmacion),
  ADD CONSTRAINT fk_pagos_confirmo FOREIGN KEY (confirmado_por) REFERENCES usuarios (id);

INSERT INTO configuracion (clave, valor, descripcion) VALUES
  ('entrega_transferencia_pendiente', 'todos',
   'Quien puede entregar una orden cuyo saldo esta cubierto con una transferencia por confirmar: no / admin / todos');

-- El negocio no da descuentos a empleados.
UPDATE configuracion SET valor = '0' WHERE clave = 'descuento_max_pct_empleado';
