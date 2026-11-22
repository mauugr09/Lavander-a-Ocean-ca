-- =====================================================================
-- Oceanica Gestion | Migracion 015: sonidos y animaciones de la interfaz
-- Encendidos por omision; la encargada los apaga en Configuracion.
-- INSERT IGNORE: se puede repetir.
-- =====================================================================

INSERT IGNORE INTO configuracion (clave, valor, descripcion) VALUES
  ('interfaz_sonidos', 'si', 'Sonidos al tocar botones, al terminar un cobro y en los avisos (si/no)'),
  ('interfaz_animaciones', 'si', 'Animaciones: brillo al escribir, cambio de pantalla y avisos (si/no)');
