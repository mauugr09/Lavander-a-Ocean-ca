-- =====================================================================
-- Oceanica Gestion | Migracion 001: esquema base (MySQL 8, InnoDB, utf8mb4)
-- Dinero: DECIMAL(10,2). Baja logica con columna `activo`. Fechas con
-- marca de creacion. Las llaves foraneas impiden registros huerfanos.
-- =====================================================================

-- ---------- Personal y acceso ----------------------------------------

CREATE TABLE roles (
  id TINYINT UNSIGNED NOT NULL AUTO_INCREMENT,
  nombre VARCHAR(30) NOT NULL,
  descripcion VARCHAR(120) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_roles_nombre (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE empleados (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  nombre VARCHAR(80) NOT NULL,
  apellidos VARCHAR(80) NOT NULL,
  telefono VARCHAR(20) NULL,
  puesto VARCHAR(60) NULL,
  fecha_ingreso DATE NOT NULL,
  fecha_baja DATE NULL,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_empleados_activo (activo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE usuarios (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  rol_id TINYINT UNSIGNED NOT NULL,
  empleado_id INT UNSIGNED NULL,
  usuario VARCHAR(40) NOT NULL,
  password_hash VARCHAR(100) NOT NULL,
  debe_cambiar_password TINYINT(1) NOT NULL DEFAULT 0,
  intentos_fallidos TINYINT UNSIGNED NOT NULL DEFAULT 0,
  bloqueado_hasta DATETIME NULL,
  ultimo_acceso DATETIME NULL,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_usuarios_usuario (usuario),
  CONSTRAINT fk_usuarios_rol FOREIGN KEY (rol_id) REFERENCES roles (id),
  CONSTRAINT fk_usuarios_empleado FOREIGN KEY (empleado_id) REFERENCES empleados (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE turnos (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  empleado_id INT UNSIGNED NOT NULL,
  dia_semana TINYINT UNSIGNED NOT NULL COMMENT '1=lunes ... 7=domingo',
  hora_entrada TIME NOT NULL,
  hora_salida TIME NOT NULL,
  vigente_desde DATE NOT NULL,
  vigente_hasta DATE NULL,
  PRIMARY KEY (id),
  KEY ix_turnos_empleado (empleado_id, dia_semana),
  CONSTRAINT fk_turnos_empleado FOREIGN KEY (empleado_id) REFERENCES empleados (id),
  CONSTRAINT ck_turnos_dia CHECK (dia_semana BETWEEN 1 AND 7)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE asistencias (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  empleado_id INT UNSIGNED NOT NULL,
  fecha DATE NOT NULL,
  hora_entrada DATETIME NULL,
  hora_salida DATETIME NULL,
  estado ENUM('presente','retardo','falta','justificada','descanso') NOT NULL DEFAULT 'presente',
  minutos_retardo SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  horas_extra DECIMAL(5,2) NOT NULL DEFAULT 0,
  observaciones VARCHAR(200) NULL,
  registrado_por INT UNSIGNED NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_asistencia_dia (empleado_id, fecha),
  KEY ix_asistencias_fecha (fecha),
  CONSTRAINT fk_asistencias_empleado FOREIGN KEY (empleado_id) REFERENCES empleados (id),
  CONSTRAINT fk_asistencias_usuario FOREIGN KEY (registrado_por) REFERENCES usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------- Clientes --------------------------------------------------

CREATE TABLE clientes (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  nombre VARCHAR(80) NOT NULL,
  apellidos VARCHAR(80) NULL,
  telefono VARCHAR(20) NULL,
  email VARCHAR(120) NULL,
  notas VARCHAR(300) NULL,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_clientes_nombre (nombre, apellidos),
  KEY ix_clientes_telefono (telefono)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------- Servicios -------------------------------------------------

CREATE TABLE categorias_servicio (
  id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
  nombre VARCHAR(60) NOT NULL,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  UNIQUE KEY uq_cat_servicio_nombre (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE servicios (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  categoria_id SMALLINT UNSIGNED NOT NULL,
  nombre VARCHAR(80) NOT NULL,
  unidad ENUM('kilo','pieza') NOT NULL DEFAULT 'kilo',
  precio DECIMAL(10,2) NOT NULL,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_servicio_nombre (nombre),
  CONSTRAINT fk_servicios_categoria FOREIGN KEY (categoria_id) REFERENCES categorias_servicio (id),
  CONSTRAINT ck_servicios_precio CHECK (precio >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------- Caja: catalogos y cortes (antes que ordenes/pagos) --------

CREATE TABLE metodos_pago (
  id TINYINT UNSIGNED NOT NULL AUTO_INCREMENT,
  nombre VARCHAR(30) NOT NULL,
  es_efectivo TINYINT(1) NOT NULL DEFAULT 0,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  UNIQUE KEY uq_metodos_pago_nombre (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE cortes_caja (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  usuario_apertura_id INT UNSIGNED NOT NULL,
  usuario_cierre_id INT UNSIGNED NULL,
  abierta_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  cerrada_en DATETIME NULL,
  fondo_inicial DECIMAL(10,2) NOT NULL DEFAULT 0,
  efectivo_esperado DECIMAL(10,2) NULL,
  efectivo_contado DECIMAL(10,2) NULL,
  diferencia DECIMAL(10,2) NULL,
  estado ENUM('abierto','cerrado') NOT NULL DEFAULT 'abierto',
  observaciones VARCHAR(200) NULL,
  PRIMARY KEY (id),
  KEY ix_cortes_estado (estado),
  CONSTRAINT fk_cortes_apertura FOREIGN KEY (usuario_apertura_id) REFERENCES usuarios (id),
  CONSTRAINT fk_cortes_cierre FOREIGN KEY (usuario_cierre_id) REFERENCES usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------- Ordenes ---------------------------------------------------

CREATE TABLE ordenes (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  folio VARCHAR(20) NOT NULL,
  cliente_id INT UNSIGNED NULL COMMENT 'NULL = cliente de mostrador',
  usuario_id INT UNSIGNED NOT NULL,
  estado ENUM('recibida','en_proceso','lista','entregada','cancelada') NOT NULL DEFAULT 'recibida',
  fecha_recepcion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  fecha_promesa DATETIME NULL,
  fecha_entrega DATETIME NULL,
  subtotal DECIMAL(10,2) NOT NULL DEFAULT 0,
  descuento DECIMAL(10,2) NOT NULL DEFAULT 0,
  total DECIMAL(10,2) NOT NULL DEFAULT 0,
  observaciones VARCHAR(300) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_ordenes_folio (folio),
  KEY ix_ordenes_estado (estado),
  KEY ix_ordenes_fecha (fecha_recepcion),
  KEY ix_ordenes_cliente (cliente_id),
  CONSTRAINT fk_ordenes_cliente FOREIGN KEY (cliente_id) REFERENCES clientes (id),
  CONSTRAINT fk_ordenes_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
  CONSTRAINT ck_ordenes_montos CHECK (subtotal >= 0 AND descuento >= 0 AND total >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE orden_detalle (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  orden_id INT UNSIGNED NOT NULL,
  servicio_id INT UNSIGNED NOT NULL,
  descripcion VARCHAR(120) NULL,
  cantidad DECIMAL(8,2) NOT NULL,
  precio_unitario DECIMAL(10,2) NOT NULL COMMENT 'precio al momento de la venta',
  importe DECIMAL(10,2) NOT NULL,
  PRIMARY KEY (id),
  KEY ix_detalle_orden (orden_id),
  KEY ix_detalle_servicio (servicio_id),
  CONSTRAINT fk_detalle_orden FOREIGN KEY (orden_id) REFERENCES ordenes (id),
  CONSTRAINT fk_detalle_servicio FOREIGN KEY (servicio_id) REFERENCES servicios (id),
  CONSTRAINT ck_detalle_cantidad CHECK (cantidad > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE orden_historial_estado (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  orden_id INT UNSIGNED NOT NULL,
  estado_anterior VARCHAR(20) NULL,
  estado_nuevo VARCHAR(20) NOT NULL,
  usuario_id INT UNSIGNED NOT NULL,
  cambiado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  nota VARCHAR(200) NULL,
  PRIMARY KEY (id),
  KEY ix_hist_orden (orden_id),
  CONSTRAINT fk_hist_orden FOREIGN KEY (orden_id) REFERENCES ordenes (id),
  CONSTRAINT fk_hist_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------- Pagos y movimientos de caja -------------------------------

CREATE TABLE pagos (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  orden_id INT UNSIGNED NOT NULL,
  metodo_pago_id TINYINT UNSIGNED NOT NULL,
  corte_id INT UNSIGNED NOT NULL,
  usuario_id INT UNSIGNED NOT NULL,
  monto DECIMAL(10,2) NOT NULL,
  tipo ENUM('anticipo','pago','reembolso') NOT NULL DEFAULT 'pago',
  referencia VARCHAR(60) NULL,
  pagado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_pagos_orden (orden_id),
  KEY ix_pagos_corte (corte_id),
  KEY ix_pagos_fecha (pagado_en),
  CONSTRAINT fk_pagos_orden FOREIGN KEY (orden_id) REFERENCES ordenes (id),
  CONSTRAINT fk_pagos_metodo FOREIGN KEY (metodo_pago_id) REFERENCES metodos_pago (id),
  CONSTRAINT fk_pagos_corte FOREIGN KEY (corte_id) REFERENCES cortes_caja (id),
  CONSTRAINT fk_pagos_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
  CONSTRAINT ck_pagos_monto CHECK (monto > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE movimientos_caja (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  corte_id INT UNSIGNED NOT NULL,
  usuario_id INT UNSIGNED NOT NULL,
  tipo ENUM('gasto','retiro','ingreso') NOT NULL,
  concepto VARCHAR(120) NOT NULL,
  monto DECIMAL(10,2) NOT NULL,
  creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_movcaja_corte (corte_id),
  CONSTRAINT fk_movcaja_corte FOREIGN KEY (corte_id) REFERENCES cortes_caja (id),
  CONSTRAINT fk_movcaja_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
  CONSTRAINT ck_movcaja_monto CHECK (monto > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------- Inventario de insumos -------------------------------------

CREATE TABLE categorias_insumo (
  id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
  nombre VARCHAR(60) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_cat_insumo_nombre (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE proveedores (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  nombre VARCHAR(100) NOT NULL,
  contacto VARCHAR(80) NULL,
  telefono VARCHAR(20) NULL,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  UNIQUE KEY uq_proveedores_nombre (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE insumos (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  categoria_id SMALLINT UNSIGNED NOT NULL,
  proveedor_id INT UNSIGNED NULL,
  nombre VARCHAR(80) NOT NULL,
  unidad VARCHAR(15) NOT NULL DEFAULT 'pieza',
  existencia DECIMAL(10,2) NOT NULL DEFAULT 0,
  minimo DECIMAL(10,2) NOT NULL DEFAULT 0,
  costo_unitario DECIMAL(10,2) NOT NULL DEFAULT 0,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  UNIQUE KEY uq_insumos_nombre (nombre),
  CONSTRAINT fk_insumos_categoria FOREIGN KEY (categoria_id) REFERENCES categorias_insumo (id),
  CONSTRAINT fk_insumos_proveedor FOREIGN KEY (proveedor_id) REFERENCES proveedores (id),
  CONSTRAINT ck_insumos_existencia CHECK (existencia >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE movimientos_inventario (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  insumo_id INT UNSIGNED NOT NULL,
  usuario_id INT UNSIGNED NOT NULL,
  tipo ENUM('entrada','salida','ajuste') NOT NULL,
  cantidad DECIMAL(10,2) NOT NULL COMMENT 'siempre positiva; el tipo define el signo',
  costo_unitario DECIMAL(10,2) NULL,
  motivo VARCHAR(120) NULL,
  creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_movinv_insumo (insumo_id, creado_en),
  CONSTRAINT fk_movinv_insumo FOREIGN KEY (insumo_id) REFERENCES insumos (id),
  CONSTRAINT fk_movinv_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios (id),
  CONSTRAINT ck_movinv_cantidad CHECK (cantidad > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------- Nomina (control interno, sin calculo fiscal) --------------

CREATE TABLE conceptos_nomina (
  id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
  clave VARCHAR(20) NOT NULL,
  nombre VARCHAR(60) NOT NULL,
  tipo ENUM('percepcion','deduccion') NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_conceptos_clave (clave)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE historial_salarios (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  empleado_id INT UNSIGNED NOT NULL,
  esquema ENUM('hora','dia','semana','quincena') NOT NULL,
  monto DECIMAL(10,2) NOT NULL,
  vigente_desde DATE NOT NULL,
  vigente_hasta DATE NULL,
  registrado_por INT UNSIGNED NOT NULL,
  creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_hsal_empleado (empleado_id, vigente_desde),
  CONSTRAINT fk_hsal_empleado FOREIGN KEY (empleado_id) REFERENCES empleados (id),
  CONSTRAINT fk_hsal_usuario FOREIGN KEY (registrado_por) REFERENCES usuarios (id),
  CONSTRAINT ck_hsal_monto CHECK (monto >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE periodos_nomina (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  periodicidad ENUM('semanal','quincenal') NOT NULL,
  fecha_inicio DATE NOT NULL,
  fecha_fin DATE NOT NULL,
  estado ENUM('abierto','aprobado','cerrado') NOT NULL DEFAULT 'abierto',
  aprobado_por INT UNSIGNED NULL,
  cerrado_en DATETIME NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_periodo (periodicidad, fecha_inicio, fecha_fin),
  CONSTRAINT fk_periodos_usuario FOREIGN KEY (aprobado_por) REFERENCES usuarios (id),
  CONSTRAINT ck_periodos_fechas CHECK (fecha_fin >= fecha_inicio)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE nomina_empleado (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  periodo_id INT UNSIGNED NOT NULL,
  empleado_id INT UNSIGNED NOT NULL,
  dias_trabajados DECIMAL(5,2) NOT NULL DEFAULT 0,
  horas_trabajadas DECIMAL(7,2) NOT NULL DEFAULT 0,
  total_percepciones DECIMAL(10,2) NOT NULL DEFAULT 0,
  total_deducciones DECIMAL(10,2) NOT NULL DEFAULT 0,
  neto DECIMAL(10,2) NOT NULL DEFAULT 0,
  pagado_en DATETIME NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_nomina_emp (periodo_id, empleado_id),
  CONSTRAINT fk_nomemp_periodo FOREIGN KEY (periodo_id) REFERENCES periodos_nomina (id),
  CONSTRAINT fk_nomemp_empleado FOREIGN KEY (empleado_id) REFERENCES empleados (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE nomina_detalle (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  nomina_empleado_id INT UNSIGNED NOT NULL,
  concepto_id SMALLINT UNSIGNED NOT NULL,
  descripcion VARCHAR(120) NULL,
  monto DECIMAL(10,2) NOT NULL,
  PRIMARY KEY (id),
  KEY ix_nomdet_nomina (nomina_empleado_id),
  CONSTRAINT fk_nomdet_nomina FOREIGN KEY (nomina_empleado_id) REFERENCES nomina_empleado (id),
  CONSTRAINT fk_nomdet_concepto FOREIGN KEY (concepto_id) REFERENCES conceptos_nomina (id),
  CONSTRAINT ck_nomdet_monto CHECK (monto >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------- Sistema ---------------------------------------------------

CREATE TABLE configuracion (
  clave VARCHAR(60) NOT NULL,
  valor VARCHAR(255) NOT NULL,
  descripcion VARCHAR(150) NULL,
  PRIMARY KEY (clave)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE auditoria (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  usuario_id INT UNSIGNED NULL,
  accion VARCHAR(40) NOT NULL,
  tabla VARCHAR(40) NULL,
  registro_id INT UNSIGNED NULL,
  detalle VARCHAR(500) NULL,
  creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_auditoria_fecha (creado_en),
  KEY ix_auditoria_usuario (usuario_id),
  CONSTRAINT fk_auditoria_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE respaldos (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  archivo VARCHAR(255) NOT NULL,
  tamano_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0,
  tipo ENUM('automatico','manual') NOT NULL,
  usuario_id INT UNSIGNED NULL,
  copiado_a_externo TINYINT(1) NOT NULL DEFAULT 0,
  creado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT fk_respaldos_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
