-- =====================================================================
-- Oceanica Gestion | Migracion 007: datos fiscales del cliente (sin timbrado)
-- Una sola sentencia: en InnoDB un ALTER TABLE se aplica completo o no se
-- aplica, asi que si falla se puede reintentar sin dejar la tabla a medias.
-- El correo de facturacion es la columna `email` que ya existia.
-- =====================================================================

ALTER TABLE clientes
  ADD COLUMN rfc VARCHAR(13) NULL AFTER notas,
  ADD COLUMN razon_social VARCHAR(254) NULL AFTER rfc,
  ADD COLUMN regimen_fiscal CHAR(3) NULL COMMENT 'clave del catalogo c_RegimenFiscal del SAT' AFTER razon_social,
  ADD COLUMN uso_cfdi VARCHAR(4) NULL COMMENT 'clave del catalogo c_UsoCFDI del SAT' AFTER regimen_fiscal,
  ADD COLUMN codigo_postal_fiscal CHAR(5) NULL AFTER uso_cfdi,
  ADD KEY ix_clientes_rfc (rfc);
