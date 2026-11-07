-- =====================================================================
-- Oceanica Gestion | Migracion 002: vistas para reportes y metricas
-- =====================================================================

-- Saldo de cada orden: total menos pagos netos (reembolsos restan).
CREATE VIEW v_saldo_ordenes AS
SELECT
  o.id AS orden_id,
  o.folio,
  o.cliente_id,
  o.estado,
  o.fecha_recepcion,
  o.fecha_promesa,
  o.total,
  COALESCE(SUM(CASE WHEN p.tipo = 'reembolso' THEN -p.monto ELSE p.monto END), 0) AS pagado,
  o.total - COALESCE(SUM(CASE WHEN p.tipo = 'reembolso' THEN -p.monto ELSE p.monto END), 0) AS saldo
FROM ordenes o
LEFT JOIN pagos p ON p.orden_id = o.id
WHERE o.estado <> 'cancelada'
GROUP BY o.id, o.folio, o.cliente_id, o.estado, o.fecha_recepcion, o.fecha_promesa, o.total;

-- Ingresos cobrados por dia y metodo de pago.
CREATE VIEW v_ventas_diarias AS
SELECT
  DATE(p.pagado_en) AS fecha,
  mp.nombre AS metodo_pago,
  COUNT(*) AS num_pagos,
  SUM(CASE WHEN p.tipo = 'reembolso' THEN -p.monto ELSE p.monto END) AS total_cobrado
FROM pagos p
JOIN metodos_pago mp ON mp.id = p.metodo_pago_id
GROUP BY DATE(p.pagado_en), mp.nombre;

-- Ordenes que siguen abiertas, con dias de atraso respecto a la fecha promesa.
CREATE VIEW v_ordenes_pendientes AS
SELECT
  o.id AS orden_id,
  o.folio,
  CONCAT_WS(' ', c.nombre, c.apellidos) AS cliente,
  c.telefono,
  o.estado,
  o.fecha_recepcion,
  o.fecha_promesa,
  CASE WHEN o.fecha_promesa IS NOT NULL AND o.fecha_promesa < NOW()
       THEN DATEDIFF(NOW(), o.fecha_promesa) ELSE 0 END AS dias_retraso,
  o.total
FROM ordenes o
LEFT JOIN clientes c ON c.id = o.cliente_id
WHERE o.estado IN ('recibida', 'en_proceso', 'lista');

-- Ventas por servicio (ordenes no canceladas).
CREATE VIEW v_ventas_por_servicio AS
SELECT
  s.id AS servicio_id,
  s.nombre AS servicio,
  cs.nombre AS categoria,
  s.unidad,
  SUM(d.cantidad) AS cantidad_total,
  SUM(d.importe) AS importe_total,
  DATE(o.fecha_recepcion) AS fecha
FROM orden_detalle d
JOIN ordenes o ON o.id = d.orden_id AND o.estado <> 'cancelada'
JOIN servicios s ON s.id = d.servicio_id
JOIN categorias_servicio cs ON cs.id = s.categoria_id
GROUP BY s.id, s.nombre, cs.nombre, s.unidad, DATE(o.fecha_recepcion);

-- Clientes frecuentes: numero de ordenes y gasto acumulado.
CREATE VIEW v_clientes_frecuentes AS
SELECT
  c.id AS cliente_id,
  CONCAT_WS(' ', c.nombre, c.apellidos) AS cliente,
  c.telefono,
  COUNT(o.id) AS num_ordenes,
  COALESCE(SUM(o.total), 0) AS total_gastado,
  MAX(o.fecha_recepcion) AS ultima_visita
FROM clientes c
JOIN ordenes o ON o.cliente_id = c.id AND o.estado <> 'cancelada'
GROUP BY c.id, c.nombre, c.apellidos, c.telefono;

-- Insumos en o por debajo de su minimo.
CREATE VIEW v_insumos_bajos AS
SELECT
  i.id AS insumo_id,
  i.nombre,
  ci.nombre AS categoria,
  i.unidad,
  i.existencia,
  i.minimo,
  pr.nombre AS proveedor
FROM insumos i
JOIN categorias_insumo ci ON ci.id = i.categoria_id
LEFT JOIN proveedores pr ON pr.id = i.proveedor_id
WHERE i.activo = 1 AND i.existencia <= i.minimo;

-- Resumen de asistencia por empleado y fecha.
CREATE VIEW v_asistencia_resumen AS
SELECT
  e.id AS empleado_id,
  CONCAT_WS(' ', e.nombre, e.apellidos) AS empleado,
  a.fecha,
  a.estado,
  a.minutos_retardo,
  a.horas_extra,
  ROUND(TIMESTAMPDIFF(MINUTE, a.hora_entrada, a.hora_salida) / 60, 2) AS horas_trabajadas
FROM asistencias a
JOIN empleados e ON e.id = a.empleado_id;
