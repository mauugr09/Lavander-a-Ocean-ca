-- =====================================================================
-- Oceanica Gestion | Migracion 014: folio en codigo de barras (Code128)
-- en el ticket y en las etiquetas de bolsa. Si la impresora termica no
-- lo imprime bien, la encargada lo apaga en Configuracion (codigo_barras = no).
-- INSERT IGNORE: se puede repetir.
-- =====================================================================

INSERT IGNORE INTO configuracion (clave, valor, descripcion) VALUES
  ('codigo_barras', 'si', 'Imprimir el folio en código de barras en el ticket y las etiquetas (si/no). Apáguelo si la impresora imprime símbolos raros');
