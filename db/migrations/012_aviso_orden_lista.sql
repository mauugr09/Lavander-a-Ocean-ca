-- =====================================================================
-- Oceanica Gestion | Migracion 012: aviso al cliente de que su ropa esta lista
-- Guarda cuando se le aviso (por WhatsApp) y quien lo hizo, para no avisar
-- dos veces y para saber a quien falta avisar.
-- Una sola sentencia: se aplica completa o no se aplica.
-- =====================================================================

ALTER TABLE ordenes
  ADD COLUMN avisado_en DATETIME NULL AFTER facturada_por,
  ADD COLUMN avisado_por INT UNSIGNED NULL AFTER avisado_en,
  ADD CONSTRAINT fk_ordenes_aviso FOREIGN KEY (avisado_por) REFERENCES usuarios (id);
