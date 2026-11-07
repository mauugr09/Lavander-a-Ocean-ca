# Reglas permanentes para quien desarrolle Oceánica Gestión

Sistema de escritorio de Lavandería Oceánica (Tultepec, Edo. de México). Lee `README.md` antes de cambiar nada.
Interfaz, mensajes, código de dominio y documentación en español de México.

## Arquitectura (no cambiarla)

- `oceanica/servicios/*`: reglas de negocio. Funciones `(conn, sesion, ...)`; toda escritura dentro de
  `transaccion(conn)`; errores para el usuario con `ErrorNegocio` / `ErrorAcceso`; bitácora con `auditar`.
- `oceanica/app/*`: pantallas PySide6. **No llevan reglas de negocio**: pueden adelantar una validación llamando a la
  misma función del servicio (para no perder lo capturado), pero la regla vive en el servicio.
- Base de datos con migraciones versionadas en `db/migrations/NNN_nombre.sql` y checksum.
- Configuración, logs, respaldos y tickets en `%APPDATA%\OceanicaGestion` (`OCEANICA_HOME` para cambiarlo).
- El sistema usa el usuario `oceanica_app` de MySQL/MariaDB, **nunca root** (root solo una vez, en `init_db`).

## Reglas

- **Compatibilidad**: todo SQL debe funcionar en MariaDB 10.3.9 (el servidor del dueño). Si una migración falla a la
  mitad, el DDL ya aplicado no se revierte: haz migraciones pequeñas e idempotentes. Preferencia: **una sola sentencia
  `ALTER TABLE` por migración** (en InnoDB se aplica completa o no se aplica) en lugar de `ADD COLUMN IF NOT EXISTS`,
  que es solo de MariaDB y rompería la compatibilidad con MySQL 8 que promete el README.
- **Nunca edites una migración ya aplicada**: crea la siguiente. El sistema se niega a migrar si cambió el checksum.
- **Pruebas obligatorias**: cada regla nueva lleva pruebas de servicio con base real (no mocks de la base) y, si toca
  una pantalla, una prueba de flujo con Qt en `QT_QPA_PLATFORM=offscreen`. Los diálogos modales se parchean; una prueba
  que se cuelga por un diálogo sin parchar es un error de la prueba. Corre toda la suite antes de dar algo por terminado,
  idealmente contra 10.3.9 y 10.11 (`OCEANICA_TEST_DB_PORT`). Nunca apuntes las pruebas a la base real: la borran.
- **Honestidad**: informa qué verificaste de verdad y qué no (Windows, impresora, MariaDB 10.3.9, `.exe`). No marques
  como hecho lo que no corriste.
- **Cuestiona las decisiones**: si una petición abre un riesgo (dinero, permisos, pérdida de datos, legal), dilo con
  claridad y propón una alternativa antes de implementarla. No complazcas por defecto.
- **Seguridad**: nunca guardes contraseñas ni PIN en claro; no registres secretos en logs; sin consultas con valores
  concatenados (siempre parámetros; solo nombres de columna de listas fijas del código pueden ir en el texto); los roles
  se validan en la capa de servicios, no solo en la pantalla.
- **Mensajes**: ningún mensaje al empleado muestra texto técnico (códigos de MySQL, SQL, trazas, nombres de paquetes).
  El detalle va a `logs/oceanica.log`.
- **Archivos limpios**: nada de `config.ini_prueba`, `prueba2.py` ni temporales en el repositorio.
- **Compatibilidad hacia atrás**: la base del cliente ya tiene datos. Cambios de esquema solo con migración nueva y
  notas de actualización en el README.
- **Cambios acotados**: no refactorices por gusto ni cambies la arquitectura. Si ves un problema de diseño, repórtalo
  con una propuesta.

## Reglas de negocio acordadas con el cliente (no cambiarlas sin avisar)

Ver «Reglas del negocio según el cliente», «Factura» y «Reglas de negocio principales» en `README.md`. Resumen: una
sola caja abierta; pagos ≤ saldo; reembolsos solo del administrador; precios copiados a la orden; inventario nunca
negativo; sin descuentos para empleados; entrega solo pagada (excepciones autorizadas por la encargada con usuario y
contraseña, con quién autorizó, quién entregó y motivo); transferencias «por confirmar»; nómina semanal por día
trabajado a salario mínimo, hora extra solo autorizada ($50), sin ISR/IMSS/CFDI; factura sin timbrado.

## Fuera de alcance salvo petición expresa

- «Nómina avanzada» (cotizada aparte).
- Etiquetas y código de barras: pendiente de confirmar con el cliente. No inventarlo.
- Timbrado de CFDI.
