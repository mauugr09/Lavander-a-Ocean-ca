-- Ajustes según las respuestas del cliente (cuestionario de nómina, entregas y transferencias).

-- Nómina: se paga por día trabajado a salario mínimo; las faltas justificadas no se pagan.
UPDATE configuracion SET valor = 'no' WHERE clave = 'asistencia_paga_justificada';

INSERT INTO configuracion (clave, valor, descripcion) VALUES
  ('nomina_salario_minimo_diario', '315.04', 'Salario mínimo diario vigente (zona general 2026); se usa al fijar el sueldo de los empleados'),
  ('nomina_pago_hora_extra',       '50',     'Pago fijo por hora extra autorizada ($). Si es 0 se usa jornada y factor'),
  ('horas_extra_automaticas',      'no',     'Si = toda salida después del turno cuenta como hora extra; no = solo las que autoriza la encargada');

-- Entrega con transferencia pendiente: el empleado pregunta y autoriza la encargada.
UPDATE configuracion SET valor = 'admin' WHERE clave = 'entrega_transferencia_pendiente';

-- Pago de nómina: efectivo (sale de caja) o transferencia, y control del recibo firmado.
ALTER TABLE nomina_empleado
  ADD COLUMN metodo_pago ENUM('efectivo','transferencia') NULL AFTER pagado_en,
  ADD COLUMN recibo_firmado TINYINT(1) NOT NULL DEFAULT 0 AFTER metodo_pago;
