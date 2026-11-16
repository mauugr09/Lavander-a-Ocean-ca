-- Categorías del mostrador con botones: ropa por kilo y prendas que se cobran por pieza.
-- La ropa del diario (playeras, ropa interior, sudaderas, pantalones y sábanas) va por kilo;
-- todo lo demás se cobra por pieza. Los precios los registra el administrador en «Servicios y precios».

ALTER TABLE categorias_servicio
  ADD COLUMN orden SMALLINT UNSIGNED NOT NULL DEFAULT 100 AFTER nombre;

UPDATE categorias_servicio SET nombre = 'Ropa por kilo' WHERE nombre = 'Lavado por kilo'
  AND NOT EXISTS (SELECT 1 FROM (SELECT nombre FROM categorias_servicio) t WHERE t.nombre = 'Ropa por kilo');
UPDATE categorias_servicio SET nombre = 'Colchas y edredones' WHERE nombre = 'Edredones y cobijas'
  AND NOT EXISTS (SELECT 1 FROM (SELECT nombre FROM categorias_servicio) t WHERE t.nombre = 'Colchas y edredones');
UPDATE categorias_servicio SET nombre = 'Estilo tintorería' WHERE nombre = 'Tintorería'
  AND NOT EXISTS (SELECT 1 FROM (SELECT nombre FROM categorias_servicio) t WHERE t.nombre = 'Estilo tintorería');

INSERT IGNORE INTO categorias_servicio (nombre) VALUES
  ('Ropa por kilo'),
  ('Colchas y edredones'),
  ('Cobijas'),
  ('Chamarras y abrigos'),
  ('Cojines'),
  ('Cortinas'),
  ('Calzado'),
  ('Planchado'),
  ('Estilo tintorería'),
  ('Otros');

UPDATE categorias_servicio SET orden = CASE nombre
  WHEN 'Ropa por kilo'       THEN 1
  WHEN 'Colchas y edredones' THEN 10
  WHEN 'Cobijas'             THEN 20
  WHEN 'Chamarras y abrigos' THEN 30
  WHEN 'Cojines'             THEN 40
  WHEN 'Cortinas'            THEN 50
  WHEN 'Calzado'             THEN 60
  WHEN 'Planchado'           THEN 70
  WHEN 'Estilo tintorería'   THEN 80
  WHEN 'Otros'               THEN 999
  ELSE orden END;
