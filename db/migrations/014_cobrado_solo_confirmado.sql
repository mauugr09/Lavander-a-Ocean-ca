-- =====================================================================
-- Oceanica Gestion | Migracion 014: «cobrado» cuenta solo pagos confirmados
-- Regla del cliente: una transferencia queda «por confirmar» hasta que la
-- encargada la revisa en el banco. Antes esta vista la sumaba como cobrada
-- desde que se registraba, y una rechazada inflaba el dia en que se cobro.
-- Ahora no cuentan las pendientes ni las rechazadas (el pago rechazado y su
-- contraasiento quedan los dos marcados como 'rechazado'). Lo pendiente se
-- muestra aparte en Reportes y en el Panel.
-- Una sola sentencia y CREATE OR REPLACE: se puede repetir.
-- =====================================================================

CREATE OR REPLACE VIEW v_ventas_diarias AS
SELECT
  DATE(p.pagado_en) AS fecha,
  mp.nombre AS metodo_pago,
  COUNT(*) AS num_pagos,
  SUM(CASE WHEN p.tipo = 'reembolso' THEN -p.monto ELSE p.monto END) AS total_cobrado
FROM pagos p
JOIN metodos_pago mp ON mp.id = p.metodo_pago_id
WHERE p.estado_confirmacion = 'confirmado'
GROUP BY DATE(p.pagado_en), mp.nombre;
