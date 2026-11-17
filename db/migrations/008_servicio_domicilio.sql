-- Entrega en mostrador o servicio a domicilio, con cargo extra configurable.
-- total = subtotal - descuento + cargo_domicilio

ALTER TABLE ordenes
  ADD COLUMN tipo_entrega ENUM('mostrador','domicilio') NOT NULL DEFAULT 'mostrador' AFTER observaciones,
  ADD COLUMN cargo_domicilio DECIMAL(10,2) NOT NULL DEFAULT 0 AFTER tipo_entrega,
  ADD COLUMN direccion_entrega VARCHAR(255) NULL AFTER cargo_domicilio,
  ADD CONSTRAINT ck_ordenes_domicilio CHECK (cargo_domicilio >= 0);

INSERT INTO configuracion (clave, valor, descripcion) VALUES
  ('cargo_domicilio', '0', 'Cargo extra por servicio a domicilio ($). Se suma al total de la orden');
