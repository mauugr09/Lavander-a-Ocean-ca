# Oceánica Gestión — backend

Sistema de gestión para Lavandería Oceánica: órdenes, caja, clientes, inventario, empleados, asistencia,
nómina (control interno), reportes, tickets y respaldos. MySQL 8 o MariaDB 10.3+ (recomendado MariaDB 10.11 LTS o superior; InnoDB, `utf8mb4_unicode_ci`) y Python 3.12+.
La aplicación de escritorio (PySide6) se inicia con `python -m oceanica`. Reglas para quien siga el desarrollo: `AGENTS.md`.

## Estructura

| Ruta | Contenido |
|---|---|
| `db/migrations/001..008` | Esquema (27 tablas), vistas de reportes, datos iniciales, reglas del backend, PIN y transferencias por confirmar, respuestas del cliente (nómina), datos fiscales del cliente y banderas de factura en la orden |
| `oceanica/init_db.py` | Instalador: crea la base, un usuario MySQL limitado y el primer administrador |
| `oceanica/migrar.py` | Aplica migraciones pendientes al actualizar el sistema |
| `oceanica/respaldos.py` | Respaldo `.sql.gz` con mysqldump, copia externa, retención y restauración |
| `oceanica/seguridad.py` | bcrypt, política de contraseñas, bloqueo tras 5 intentos (15 min), bitácora |
| `oceanica/app/` | Aplicación de escritorio PySide6: login, mostrador, órdenes, caja, asistencia, clientes y, para el administrador, inventario (también en mostrador), reportes con exportación a Excel/PDF, servicios y precios, empleados y PIN, transferencias y configuración |
| `oceanica/servicios/` | Reglas de negocio: usuarios, configuración, clientes, catálogo, caja, órdenes, facturación (sin timbrado), inventario, empleados, nómina, reportes, exportación, tickets, carga inicial |
| `tests/` | 155 pruebas (esquema, seguridad, servicios contra base real y pantallas con Qt `offscreen`) |

## Notas de actualización

Antes de cada actualización: respaldo manual (`python -m oceanica.respaldos --manual`, o Configuración → Respaldo).
Después: `python -m oceanica.migrar` (o `OceanicaAdmin.exe migrar`). Solo aplica lo pendiente; volver a correrlo no hace nada.

- **Migraciones 007 y 008 (factura, sin CFDI).** 007 agrega a `clientes` RFC, razón social, régimen fiscal, uso del
  CFDI y código postal fiscal (todos opcionales; el correo de factura es el `email` que ya existía). 008 agrega a
  `ordenes` «requiere factura», «facturada», folio externo, fecha y quién la marcó. No cambian datos existentes: los
  clientes quedan sin datos fiscales y las órdenes anteriores como «no requiere factura». Cada migración es una sola
  sentencia `ALTER TABLE`: si falla, no deja la tabla a medias y se puede volver a correr. Probadas en MariaDB 10.3.9 y 10.11.
- Cambios de uso: Esc en «Nueva orden» pregunta antes de borrar si ya hay servicios capturados; los errores de base de
  datos y de impresión ya no muestran texto técnico (el detalle queda en `logs/oceanica.log`).

## Instalación en la PC del local

1. Instalar MariaDB 10.11 LTS o MySQL 8 (10.3 funciona pero ya no tiene soporte del fabricante) como servicio de Windows y agregar su carpeta `bin` al PATH.
2. `pip install -r requirements.txt`
3. Primera vez en la PC: `python -m oceanica.init_db` (pide la contraseña de root una sola vez; no la guarda; el sistema nunca usa root). Si la base y `oceanica_app` ya existen: `python -m oceanica.configurar` (sin root). La configuración se guarda en `%APPDATA%\OceanicaGestion`, fuera de la carpeta del programa: al descomprimir una versión nueva no hay que repetir este paso, solo `python -m oceanica.migrar`.
4. Programador de tareas de Windows, diario: `python -m oceanica.respaldos --auto`.
5. Al recibir una versión nueva: respaldo manual y `python -m oceanica.migrar`.
6. Para abrir el programa: doble clic en `iniciar_oceanica.bat` (o `python -m oceanica`).

`config.ini` (en `%APPDATA%\OceanicaGestion`, junto con respaldos, logs y tickets) contiene la contraseña de la base: no se comparte ni se sube a ningún repositorio.

## Generar el programa para Windows (.exe e instalador)

En la PC con Windows (Python 3.12+ con «Add to PATH»): doble clic en `construir_exe.bat`.
- Crea `dist\\Oceanica\\` con `Oceanica.exe` (el programa, sin ventana negra) y `OceanicaAdmin.exe` (misma aplicación con consola para `migrar`, `configurar`, `instalar` y `respaldo --auto`).
- Si está instalado Inno Setup 6, también crea `dist\\Instalar_Oceanica.exe` (acceso directo, menú Inicio y migración final).
- En la PC del cliente no hace falta Python. Sí hace falta MariaDB/MySQL (y `mysqldump` en el PATH para los respaldos).
- Primera vez en esa PC: `OceanicaAdmin.exe instalar` (pide root una sola vez) o, si la base ya existe, `OceanicaAdmin.exe configurar`.

## Reglas del negocio según el cliente

- **Nómina semanal** (lunes a domingo): se paga por **día trabajado** a salario mínimo (configuración `nomina_salario_minimo_diario`, hoy $315.04, zona general). Sábado y entre semana pagan igual. Faltas, justificadas y retardos no se descuentan ni se pagan: solo cuenta el día trabajado. Sin bonos, adelantos ni vacaciones en el sistema.
- **Hora extra**: solo la que autoriza la encargada (Asistencia → «Ajustes de la encargada»), a $50 por hora (`nomina_pago_hora_extra`).
- **Horarios**: matutino 9-15, vespertino 12-18, sábado 9-17; cada empleado tiene su día de descanso (Empleados y usuarios → «Horario…»). Los días de descanso no generan avisos. Tolerancia de entrada: 10 min, el retardo solo se registra.
- **Pago**: en efectivo (sale de la caja) o por transferencia (no mueve la caja), con recibo PDF para firma.
- **Entrega**: con saldo o con transferencia por confirmar, el empleado pide autorización a la encargada (usuario y contraseña de administrador). Transferencias: basta la captura de pantalla; la encargada confirma después en el banco.
- Impresora de tickets: térmica genérica ESC/POS de 80 mm.

## Uso de la aplicación

- Entrada: **mostrador** (sin contraseña) o **administrador** (usuario y contraseña; se cierra solo tras 10 minutos sin actividad).
- En el mostrador, cada orden, cobro, entrega, apertura/cierre de caja y llegada/salida pide el **PIN** de quien la hace. Consultar y editar clientes reutiliza la identidad 2 minutos.
- Atajos: F2 buscar servicio · F3 cliente (en Órdenes: buscar) · F4 cliente nuevo · Alt+F requiere factura · F5 guardar y cobrar · Esc limpiar (pregunta si ya hay servicios) · F6 cobrar saldo · F7 entregar · Ctrl+1…9 cambiar de sección.
- Captura rápida: escribe parte del nombre del servicio, Enter, cantidad, Enter. La búsqueda ignora acentos y mayúsculas.
- Los tickets se muestran en pantalla; se imprimen en la térmica (Windows + pywin32, nombre en la configuración `impresora_ticket`) o se abren como PDF (carpeta `tickets/`).
- Registro de errores: `logs/oceanica.log`.

## Identificación en el mostrador (PIN)

- Cada empleado tiene su PIN de 4 a 6 dígitos (sin repeticiones ni secuencias). Lo asigna el administrador (`usuarios.asignar_pin`) y el empleado puede cambiarlo (`cambiar_pin`).
- Flujo: elegir el nombre en la lista (`usuarios.listar_para_pin`, los presentes primero) + PIN (`seguridad.autenticar_pin`). Esa sesión firma órdenes, cobros y entregas.
- Mismo bloqueo que la contraseña: 5 fallos, 15 minutos. El administrador usa contraseña, no PIN.

## Transferencias por confirmar

- Una transferencia exige clave de rastreo y queda "por confirmar". Cubre el saldo, pero el administrador debe confirmarla (`caja.confirmar_transferencia`) o rechazarla (`rechazar_transferencia`, requiere caja abierta); al rechazar, la orden recupera su saldo.
- Quién puede entregar con transferencia sin confirmar: configuración `entrega_transferencia_pendiente` = `no` / `admin` / `todos` (hoy `todos`; queda en bitácora).
- El corte de caja y el ticket muestran cuánto está por confirmar. Reporte: `reportes.transferencias_pendientes`.

## Factura (alcance mínimo, sin CFDI)

El sistema **no timbra**: la factura se emite en el portal del SAT o en el sistema de facturación del dueño. Aquí solo se controla qué hay que facturar.

- **Cliente**: RFC (formato y fecha validados: 12 caracteres empresa, 13 persona física), razón social, régimen fiscal y uso del CFDI (catálogos del SAT), código postal fiscal (5 dígitos) y correo. Todo opcional: se puede capturar por partes; el sistema avisa qué falta.
- **Orden**: casilla «Requiere factura» al capturar (Alt+F). Exige cliente: las ventas de mostrador no se facturan. Si se olvidó, se marca después en Órdenes → «Factura».
- **Facturada**: solo la encargada la marca (Órdenes → «Factura» → «Ya se facturó»), con folio o UUID opcional. Quitar la marca pide motivo y queda en bitácora.
- **Cancelar** una orden facturada no se permite: primero se cancela la factura en el SAT y la encargada quita la marca (si no, quedaría un CFDI vigente de un servicio no cobrado).
- **Reporte**: Reportes → «Órdenes por facturar» (solo administrador; lleva RFC). Muestra las pendientes del periodo **y las de periodos anteriores que siguen sin facturar** (columna «Periodo»), con los datos fiscales y qué falta. Se exporta a Excel o PDF. También: filtro «Por facturar» en Órdenes.
- No se valida el dígito verificador del RFC ni que el régimen corresponda a persona física o moral: eso lo rechaza el facturador al timbrar.

## Reglas de negocio principales

- Una sola caja abierta a la vez; un pago nunca excede el saldo; el reembolso es solo de administrador y obligatorio antes de cancelar una orden con pagos.
- Entrega solo con saldo cero (el administrador puede forzarla con motivo). Configurable: `entrega_requiere_pago_total`.
- Descuento máximo del empleado: `descuento_max_pct_empleado` (hoy 0 %: el negocio no da descuentos). El administrador no tiene límite.
- Los precios se copian a la orden: cambiar el catálogo no altera ventas pasadas. Servicios por pieza solo admiten cantidades enteras.
- El inventario no puede quedar negativo; los ajustes son solo de administrador y quedan en bitácora.
- El corte de caja exige observación si hay diferencia.

## Nómina (control interno, sin ISR/IMSS/CFDI)

- Esquema `hora`: horas trabajadas × monto. `dia`: días pagados × monto. `semana`/`quincena`: monto fijo del periodo, prorrateado si entró o salió a mitad; cada falta descuenta 1/7 o 1/15.
- Días pagados = presentes + retardos (+ justificadas si `asistencia_paga_justificada` = si).
- Hora extra = horas extra × valor de la hora × `nomina_factor_hora_extra` (2). Jornada: `nomina_jornada_horas` (8).
- Bonos y descuentos manuales sobreviven a un recálculo. Estados: abierto → aprobado → cerrado. El pago puede registrarse como gasto de caja.

## Carga inicial (CSV o Excel, solo administrador)

`carga_inicial.generar_plantilla(tipo, ruta)` crea el CSV vacío. Columnas:

- servicios: `categoria, nombre, unidad (kilo|pieza), precio`
- insumos: `categoria, nombre, unidad, existencia, minimo, costo_unitario, proveedor`
- empleados: `nombre, apellidos, telefono, puesto, fecha_ingreso`
- clientes: `nombre, apellidos, telefono, email, notas`

Es todo o nada: si una fila falla, no se guarda nada y se devuelve el número de fila con el error. Lo ya existente se omite.

## Pruebas

`pip install -r requirements.txt` y `python -m pytest`. Las pruebas de servicios necesitan un servidor MySQL/MariaDB con un usuario
de pruebas (variables `OCEANICA_TEST_DB_HOST/PORT/USER/PASSWORD/NAME`; por defecto `oc_test` / `oc_test_pw` / `oceanica_test` en 127.0.0.1:3306).
**Borran las tablas de esa base de pruebas: nunca apuntarlas a la base real.** Sin servidor, se omiten.

## Límites conocidos

- La impresión directa ESC/POS (`tickets.imprimir_texto`) depende de Windows + pywin32 y no se ha probado con una impresora real.
  En modo RAW, Windows no avisa si la impresora no tiene papel: el ticket puede «imprimirse» sin salir.
- `construir_exe.bat`, `Oceanica.exe`, `OceanicaAdmin.exe` y el instalador no se han verificado en Windows en esta versión (no hubo acceso a Windows).
- Etiquetas y código de barras: pendiente de confirmar con el cliente (ver issue en el repositorio). No está construido.
- Nómina no es fiscal: no sustituye CFDI ni obligaciones de IMSS/SAT.
