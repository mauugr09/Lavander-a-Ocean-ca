-- =====================================================================
-- Oceanica Gestion | Migracion 013: dias para considerar una orden olvidada
-- Lo usa el reporte de ropa olvidada. INSERT IGNORE: se puede repetir.
-- =====================================================================

INSERT IGNORE INTO configuracion (clave, valor, descripcion) VALUES
  ('almacenaje_dias', '30', 'Días que una orden lista puede esperar antes de aparecer como ropa olvidada');
