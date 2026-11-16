-- Ticket con el diseño de la lavandería: logo, datos del cliente, detalle en columnas,
-- condiciones del servicio, almacenaje, firma y página web. Los textos se editan en «Configuración».

ALTER TABLE configuracion MODIFY valor TEXT NOT NULL;

INSERT INTO configuracion (clave, valor, descripcion) VALUES
  ('ticket_logo', 'si', 'Imprimir el logo en la parte de arriba del ticket (si/no)'),
  ('negocio_web', 'lavanderiaoceanica.com', 'Página web que aparece al final del ticket'),
  ('ticket_condiciones',
   'Entrega y pago: el servicio se paga al momento de la entrega o de la recepción, según se acuerde.\nResponsabilidad limitada: el establecimiento no se hace responsable por objetos o dinero olvidados en las prendas.\nGarantía: si el cliente no está satisfecho, el negocio se compromete a reprocesar la prenda sin costo extra en un plazo determinado.\nIndemnización: en caso de pérdida o daño total imputable al negocio, se paga un porcentaje del valor de la prenda (comúnmente entre 3 y 10 veces el costo del servicio).',
   'Condiciones del servicio en el ticket (una por renglón)'),
  ('ticket_almacenaje',
   'Transcurridos 30 días, se podrá cobrar una cuota de almacenaje por día de retraso en el retiro.',
   'Texto de almacenaje en el ticket (vacío = no se imprime)');

UPDATE configuracion SET valor = 'GRACIAS POR SU PREFERENCIA' WHERE clave = 'ticket_pie' AND valor = 'Gracias por su preferencia';
