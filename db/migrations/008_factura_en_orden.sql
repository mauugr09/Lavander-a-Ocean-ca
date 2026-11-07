-- =====================================================================
-- Oceanica Gestion | Migracion 008: banderas de factura en la orden
-- La factura se timbra fuera del sistema; aqui solo se controla que se
-- pidio y que ya se hizo (con el folio externo, opcional).
-- Una sola sentencia, por la misma razon que la 007.
-- =====================================================================

ALTER TABLE ordenes
  ADD COLUMN requiere_factura TINYINT(1) NOT NULL DEFAULT 0 AFTER observaciones,
  ADD COLUMN facturada TINYINT(1) NOT NULL DEFAULT 0 AFTER requiere_factura,
  ADD COLUMN factura_folio VARCHAR(40) NULL COMMENT 'folio o UUID de la factura emitida fuera del sistema' AFTER facturada,
  ADD COLUMN facturada_en DATETIME NULL AFTER factura_folio,
  ADD COLUMN facturada_por INT UNSIGNED NULL AFTER facturada_en,
  ADD KEY ix_ordenes_factura (requiere_factura, facturada),
  ADD CONSTRAINT fk_ordenes_facturo FOREIGN KEY (facturada_por) REFERENCES usuarios (id);
