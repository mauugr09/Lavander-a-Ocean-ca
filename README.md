# Oceánica Gestión

Sistema de escritorio para **Lavandería Oceánica**: mostrador de órdenes, cobros, caja, clientes, inventario,
empleados, asistencia, nómina (control interno), panel del negocio, reportes, factura (sin timbrado), tickets y respaldos.

- Python 3.12+ y PySide6 (solo se usan los módulos básicos de PySide6-Essentials).
- MariaDB 10.11 LTS o MySQL 8 (InnoDB, `utf8mb4_unicode_ci`). MariaDB 10.3+ funciona, pero ya no tiene soporte.
- Se inicia con `python -m oceanica` (o doble clic en `iniciar_oceanica.bat`).
- Reglas para quien siga el desarrollo (incluidos agentes de IA): `AGENTS.md`.

## Para el equipo: actualizar después de `git pull`

Cada quien trabaja con **su propia base de datos**; el repositorio solo lleva el código. Después de descargar cambios:

```
git pull
python -m oceanica             # al abrir, pone SU base al día (con respaldo previo), sin borrar datos
```

Primera vez en una computadora: `pip install -r requirements.txt` y `python -m oceanica.init_db` (ver «Instalación»).
Para tener datos con qué probar: `python -m oceanica.datos_demo` (ver «Datos de ejemplo»).

**Antes de crear una migración nueva, haga `git pull`** y use el siguiente número libre en `db/migrations/`. Si dos
personas crean el mismo número en ramas distintas, el sistema no puede migrar (ya pasó con la 007 y la 008).

## Estructura

| Ruta | Contenido |
|---|---|
| `db/migrations/001..014` | Esquema (27 tablas), vistas de reportes, datos iniciales, reglas del backend, PIN y transferencias por confirmar, respuestas del cliente, categorías del mostrador, servicio a domicilio, textos del ticket, datos fiscales del cliente, banderas de factura en la orden, aviso de orden lista, días de almacenaje y «cobrado» solo con pagos confirmados |
| `oceanica/init_db.py` · `configurar.py` · `migrar.py` | Instalación (crea la base, un usuario MySQL limitado y el primer administrador), conexión a una base existente y actualización (el programa la hace solo al abrir) |
| `oceanica/programar_respaldo.py` · `restablecer_admin.py` | Respaldo diario en el Programador de tareas de Windows y contraseña temporal para un administrador que no puede entrar |
| `oceanica/respaldos.py` | Respaldo `.sql.gz` con mysqldump, copia externa, retención y restauración |
| `oceanica/seguridad.py` | bcrypt, política de contraseñas, PIN, bloqueo tras 5 intentos (15 min) y bitácora |
| `oceanica/datos_demo.py` | Datos de ejemplo para probar (nunca en la lavandería) |
| `oceanica/servicios/` | Reglas de negocio: usuarios, configuración, clientes, catálogo, caja, órdenes, facturación (sin timbrado), inventario, empleados, nómina, reportes, panel, exportación, tickets y carga inicial |
| `oceanica/app/` | Interfaz PySide6: entrada, mostrador, órdenes, caja, asistencia, clientes, inventario y, para el administrador, panel, reportes, nómina, servicios y precios, empleados, transferencias y configuración |
| `oceanica/app/botones.py` · `cobro.py` · `graficas.py` · `iconos.py` · `burbujas.py` · `importacion.py` | Botones grandes y teclado numérico, cobro por pasos, gráficas dibujadas con QPainter, íconos SVG, animación de la entrada y botones de importación desde Excel o CSV |
| `oceanica/app/recursos/` | Logo, ícono e íconos de línea (Tabler Icons, licencia MIT) |
| `tests/` | 223 pruebas (esquema, seguridad, servicios e interfaz contra una base real) |

## Notas de actualización

**No hay que correr nada para actualizar.** Se instala la versión nueva y, al abrir el programa, la base se pone al día
sola: si hay cambios pendientes, **primero hace un respaldo** y luego los aplica. Si el respaldo o un cambio fallan, el
programa no abre (para no trabajar con la base a medias), avisa que se llame a la encargada y deja en `logs/` el
detalle y el comando exacto para regresar a como estaba. Para soporte técnico sigue existiendo
`OceanicaAdmin.exe migrar` (con `--sin-respaldo` solo si el respaldo previo no se puede hacer y ya hay otro de hoy).

- **Migración 014 («cobrado» solo con pagos confirmados).** Regla del cliente: una transferencia está «por confirmar»
  hasta que la encargada la revisa en el banco. Antes, Reportes y el Panel la sumaban como cobrada desde que se
  registraba, y una rechazada inflaba el día en que se cobró. Ahora «cobrado» solo cuenta pagos confirmados; lo
  pendiente aparece aparte («$X en transferencias por confirmar»). Por eso, en periodos ya pasados, «cobrado» puede
  bajar respecto a lo que se veía antes: es la cifra correcta.
- **El programa se actualiza solo al abrir; respaldo diario programado; recuperar la contraseña de la encargada.** El instalador programa el respaldo diario en el Programador de tareas (`OceanicaAdmin.exe
  programar-respaldo`): a la hora de `respaldo_hora` (21:00) y, si la computadora estaba apagada, en cuanto se
  enciende. Nuevo `OceanicaAdmin.exe restablecer-admin` (menú Inicio → «Restablecer contraseña de administrador»): pone
  una contraseña temporal a un administrador que no puede entrar; pide la contraseña de root de MariaDB.

- **Migraciones 012 y 013 (aviso de orden lista, ropa olvidada).** 012 agrega a `ordenes` cuándo y quién avisó al
  cliente que su ropa está lista. 013 agrega el ajuste `almacenaje_dias` (30) que usa el reporte de ropa olvidada.
  Además cambia el cierre de caja: el empleado ya no ve el resumen de dinero (corte a ciegas).
- **Migraciones 007 a 009 (mostrador, domicilio, ticket).** 007 agrega el orden de las categorías del mostrador y
  **renombra categorías existentes** («Lavado por kilo» → «Ropa por kilo», «Edredones y cobijas» → «Colchas y
  edredones», «Tintorería» → «Estilo tintorería»). 008 agrega a `ordenes` el tipo de entrega, el cargo y la dirección
  a domicilio. 009 cambia `configuracion.valor` a `TEXT` y agrega los textos del ticket (condiciones y almacenaje).
- **Migraciones 010 y 011 (factura, sin CFDI).** 010 agrega a `clientes` RFC, razón social, régimen fiscal, uso del
  CFDI y código postal fiscal (todos opcionales; el correo de factura es el `email` que ya existía). 011 agrega a
  `ordenes` «requiere factura», «facturada», folio externo, fecha y quién la marcó. No cambian datos existentes. Cada
  una es una sola sentencia `ALTER TABLE`: si falla, no deja la tabla a medias y se puede volver a correr.
- Todas probadas en MariaDB 10.3.9 y 10.11, incluida la actualización de una base con datos.
- **Instalador (`init_db`)**: el usuario del sistema ahora se crea para `localhost`, `127.0.0.1` y `::1` (nunca para la
  red). Antes solo se creaba para `localhost`, y un servidor con `skip-name-resolve` rechazaba al programa con
  «Access denied» (comprobado en 10.3.9 y 10.11). Si en una computadora ya instalada aparece ese error, vuelva a
  correr `python -m oceanica.init_db`: conserva los datos y solo renueva el usuario y su contraseña.
- Si la base no responde al abrir el programa, el aviso al empleado ya no muestra comandos ni códigos de error.

## Instalación en la PC del local

Guía paso a paso con el instalador (sin Python): [`INSTALAR_EN_MI_PC.md`](INSTALAR_EN_MI_PC.md).

1. Instalar MariaDB 10.11 LTS o MySQL 8 como servicio de Windows y agregar su carpeta `bin` al PATH.
2. `pip install -r requirements.txt`
3. Primera vez: `python -m oceanica.init_db` (pide la contraseña de root una sola vez y no la guarda; el sistema nunca usa root). Si la base y `oceanica_app` ya existen: `python -m oceanica.configurar`. La configuración queda en `%APPDATA%\OceanicaGestion`, fuera de la carpeta del programa.
4. Respaldo diario: con el instalador queda programado solo. Sin instalador: `python -m oceanica.programar_respaldo`
   (o, a mano, una tarea diaria del Programador de tareas con `python -m oceanica.respaldos --auto`).
5. Al recibir una versión nueva: instalarla y abrir el programa. La base se actualiza sola (con respaldo previo).
6. Si la encargada olvida su contraseña y nadie más es administrador: `OceanicaAdmin.exe restablecer-admin` (pide root).
   Mejor aún: que el dueño tenga su propia cuenta de administrador, para no depender de una sola persona.

`config.ini` (en `%APPDATA%\OceanicaGestion`, junto con respaldos, logs y tickets) contiene la contraseña de la base: no se comparte ni se sube al repositorio.

En Windows con procesador ARM el conector de MySQL no tiene su parte en C; el sistema usa entonces la versión en Python automáticamente.

## Generar el programa para Windows (.exe e instalador)

En la PC con Windows (Python 3.12+ con «Add to PATH»): doble clic en `construir_exe.bat`.
- Crea `dist\Oceanica\` con `Oceanica.exe` (el programa) y `OceanicaAdmin.exe` (con consola, para `instalar`, `configurar`, `respaldo --auto`, `programar-respaldo`, `restablecer-admin` y, solo para soporte, `migrar`).
- Con Inno Setup 6 instalado también crea `dist\Instalar_Oceanica.exe`.
- En la PC del cliente no hace falta Python; sí MariaDB/MySQL (y `mysqldump` en el PATH para los respaldos).

## Cómo se usa

### Entrada
- **Entrar al mostrador** (empleados, sin contraseña) o **administrador** (usuario y contraseña; se cierra solo tras 10 minutos sin actividad).
- Cada orden, cobro, entrega, apertura/cierre de caja y llegada/salida se confirma con el **PIN** de quien la hace: el empleado toca su nombre y escribe su PIN en un teclado grande.

### Nueva orden (mostrador)
- **Ropa por kilo** (playeras, ropa interior, sudaderas, pantalones y sábanas): abre un teclado para los kilos de la báscula.
- **Por pieza**: Colchas y edredones, Cobijas, Chamarras y abrigos, Cojines, Cortinas, Calzado, Planchado, Estilo tintorería y Otros. Cada toque en una opción agrega una pieza. Las opciones y precios se registran en «Servicios y precios».
- En la orden: **Quitar 1**, **Agregar 1** y **Eliminar** (pide confirmación con el nombre y la cantidad). En kilos, **Cambiar kilos** abre el teclado.
- **Entrega**: «Recoge aquí» o «A domicilio». A domicilio pide la dirección y suma el cargo `cargo_domicilio` de Configuración (el empleado no lo cambia; el administrador sí, por orden).
- **Cobro por pasos**: ¿Cómo va a pagar? (todo ahora, anticipo o al recoger) → ¿Con qué paga? (efectivo, tarjeta o transferencia) → billetes sugeridos y cambio en grande, o confirmación de la captura del comprobante.
- Atajos: F2 buscar servicio · F3 cliente · F4 cliente nuevo · Alt+F requiere factura · F5 guardar y cobrar · Esc regresar · F6 cobrar lo pendiente · F7 entregar · Ctrl+1…9 cambiar de sección.

### Caja y corte
- Al iniciar el día: contar el efectivo y **Abrir caja** con ese fondo. Sin caja abierta no se puede cobrar.
- Gastos, ingresos y retiros: **Registrar gasto, ingreso o retiro**.
- Al cerrar: **Cerrar caja (corte del día)**, escribir el efectivo contado; si no coincide con lo esperado, se pide la explicación. Sale el ticket del corte. Historial en Reportes → Cortes de caja.
- **Corte a ciegas:** en modo mostrador no se muestra el resumen de dinero ni el efectivo esperado, y si el conteo no cuadra no se dice por cuánto. La encargada sí lo ve. Cada conteo rechazado queda en la bitácora (`caja_conteo_rechazado`), para detectar a quien prueba montos hasta atinar. Límite: un empleado que sume sus propios cobros del día puede estimar lo esperado; esto quita la tentación fácil, no sustituye revisar los cortes.

### Operación diaria
- **Aviso de respaldo:** en modo administrador, la barra superior dice de cuándo es el último respaldo. Naranja si tiene más de un día, nunca se ha hecho o el archivo ya no está; gris si no se copió al disco externo.
- **Avisar por WhatsApp** (Órdenes, orden lista): abre WhatsApp con el mensaje ya escrito para el teléfono del cliente. El sistema no envía nada: lo manda el empleado y confirma que lo envió; queda anotado cuándo y quién. Requiere WhatsApp Web o de escritorio con sesión iniciada en esa PC y teléfonos de 10 dígitos.
- **Etiquetas de bolsa** (Órdenes): una etiqueta de texto por bolsa («BOLSA 1 DE 3», folio, cliente, entrega) en la misma impresora de tickets. Sin código de barras.
- **Reportes → Entregas a domicilio:** la ruta de reparto, con dirección, teléfono y lo que falta cobrar; primero las que ya están listas.
- **Reportes → Ropa olvidada:** órdenes listas que llevan más de `almacenaje_dias` sin recogerse, con el último aviso. El sistema no calcula ni cobra cuota de almacenaje: solo las lista.

### Ticket de la orden
Logo arriba (vista previa, PDF y térmica como imagen ESC/POS), datos del cliente, detalle en columnas (Cant, Servicio, P.U., Ud, Importe), anticipo y por liquidar, condiciones del servicio, almacenaje, líneas de firma, agradecimiento y página web. Los textos se cambian en Configuración: `ticket_condiciones`, `ticket_almacenaje`, `ticket_pie`, `negocio_web`, `ticket_logo`, `ticket_ancho` (42 para 80 mm, 32 para 58 mm) e `impresora_ticket`.

### Panel del negocio (administrador)
Vendido hoy, en la semana y en el mes contra el periodo anterior (las cifras empiezan **borrosas** y se muestran con el ojo de cada recuadro o con «Mostrar cifras»); ventas de los últimos 12 meses con el mejor mes resaltado; avance del mes contra el anterior; clientes más frecuentes, servicios que más venden, formas de pago y datos del periodo. Las gráficas se dibujan con QPainter: no requieren Qt Charts.

### Reportes (administrador)
Ventas por día, por semana y por mes, cobros por método de pago, ventas por servicio, órdenes pendientes, clientes frecuentes, insumos bajo el mínimo, asistencia y cortes de caja. Se exportan a **PDF o Excel** sin gráficas: logo, periodo en palabras, recuadros de resumen, nota de cómo leer el reporte y tabla con total (en Excel con filtros).

### Interfaz
Letra grande, botones amplios con íconos, trato de «usted», textos estándar de Qt en español y colores claros aunque Windows esté en modo oscuro. La entrada tiene burbujas animadas a los lados.

## Reglas del negocio según el cliente

- **Nómina semanal** (lunes a domingo) por **día trabajado** a salario mínimo (`nomina_salario_minimo_diario`, hoy $315.04). Sábado y entre semana pagan igual. Faltas y retardos no se descuentan ni se pagan: solo cuenta el día trabajado. Sin bonos, adelantos ni vacaciones en el sistema.
- **Hora extra**: solo la que autoriza la encargada (Asistencia → «Ajustes de la encargada»), a $50 por hora (`nomina_pago_hora_extra`).
- **Horarios**: matutino 9-15, vespertino 12-18, sábado 9-17; cada empleado tiene su día de descanso. Tolerancia de entrada: 10 min; el retardo solo se registra.
- **Pago de nómina**: en efectivo (sale de la caja) o por transferencia (no mueve la caja), con recibo PDF para firma.
- **Entrega con saldo o con transferencia por confirmar**: el empleado pide autorización a la encargada (usuario y contraseña de administrador). En transferencias basta la captura de pantalla; la encargada confirma después en el banco.
- Impresora de tickets: térmica genérica ESC/POS de 80 mm.

## Factura (alcance mínimo, sin CFDI)

El sistema **no timbra**: la factura se emite en el portal del SAT o en el sistema de facturación del dueño. Aquí solo se controla qué hay que facturar.

- **Cliente**: RFC (formato y fecha validados: 12 caracteres empresa, 13 persona física), razón social, régimen fiscal y uso del CFDI (catálogos del SAT), código postal fiscal (5 dígitos) y correo. Todo opcional: se puede capturar por partes; el sistema avisa qué falta.
- **Orden**: casilla «Requiere factura» al capturar (Alt+F). Exige cliente: las ventas sin cliente no se facturan. Si se olvidó, se marca después en Órdenes → «Factura».
- **Facturada**: solo la encargada la marca (Órdenes → «Factura» → «Ya se facturó»), con folio o UUID opcional. Quitar la marca pide motivo y queda en bitácora.
- **Cancelar** una orden facturada no se permite: primero se cancela la factura en el SAT y la encargada quita la marca (si no, quedaría un CFDI vigente de un servicio no cobrado).
- **Reporte**: Reportes → «Órdenes por facturar» (solo administrador; lleva RFC). Muestra las pendientes del periodo **y las de periodos anteriores que siguen sin facturar** (columna «Periodo»), con los datos fiscales y qué falta. Se exporta a Excel o PDF. También: filtro «Por facturar» en Órdenes.
- No se valida el dígito verificador del RFC ni que el régimen corresponda a persona física o moral: eso lo rechaza el facturador al timbrar.

## Reglas de negocio principales

- Una sola caja abierta a la vez; un pago nunca excede el saldo; el reembolso es solo de administrador y obligatorio antes de cancelar una orden con pagos.
- Entrega solo con saldo cero (el administrador puede forzarla con motivo). Configurable: `entrega_requiere_pago_total`.
- Transferencias: quedan «por confirmar» hasta que el administrador las confirma o rechaza (al rechazar, la orden recupera su saldo). Quién puede entregar con una pendiente: `entrega_transferencia_pendiente` = `no` / `admin` / `todos` (hoy `admin`).
- Descuento máximo del empleado: `descuento_max_pct_empleado` (hoy 0 %). El administrador no tiene límite.
- Los precios se copian a la orden: cambiar el catálogo no altera ventas pasadas. Los servicios por pieza solo admiten cantidades enteras.
- `total = subtotal − descuento + cargo a domicilio`.
- El inventario no puede quedar negativo; los ajustes son solo de administrador y quedan en bitácora.
- El corte de caja exige observación si hay diferencia.

## Nómina (control interno, sin ISR/IMSS/CFDI)

- Esquema `hora`: horas trabajadas × monto. `dia`: días pagados × monto. `semana`/`quincena`: monto fijo del periodo, prorrateado si entró o salió a mitad; cada falta descuenta 1/7 o 1/15.
- Días pagados = presentes + retardos (+ justificadas si `asistencia_paga_justificada` = si).
- Bonos y descuentos manuales sobreviven a un recálculo. Estados: abierto → aprobado → cerrado.

## Carga inicial (CSV o Excel, solo administrador)

`carga_inicial.generar_plantilla(tipo, ruta)` crea el archivo vacío. Columnas:

- servicios: `categoria, nombre, unidad (kilo|pieza), precio`
- insumos: `categoria, nombre, unidad, existencia, minimo, costo_unitario, proveedor`
- empleados: `nombre, apellidos, telefono, puesto, fecha_ingreso`
- clientes: `nombre, apellidos, telefono, email, notas`

Es todo o nada: si una fila falla, no se guarda nada y se indica la fila con el error. Lo ya existente se omite.

En pantalla, con la sesión de la encargada, hay botones «Descargar plantilla» e «Importar desde Excel o CSV» en
**Servicios y precios**, **Clientes** e **Inventario**. Los empleados **no** se importan desde pantalla a propósito:
la importación los crearía sin cuenta ni PIN y no podrían checar ni cobrar; se dan de alta uno por uno en
«Empleados y usuarios», que pide el PIN.

## Datos de ejemplo (solo para probar)

En una base de pruebas: `python -m oceanica.datos_demo`. Crea servicios con precios, 3 empleados con PIN (Rosa 482615, Jorge 739164, Patricia 516273), 20 clientes, insumos y un año de órdenes cobradas, más órdenes abiertas en varios estados. Si la base ya tiene órdenes no hace nada (`--forzar` lo permite). **Nunca se ejecuta en la computadora de la lavandería.**

## Pruebas

`python -m pytest`. Necesitan un servidor MySQL/MariaDB con un usuario de pruebas (variables `OCEANICA_TEST_DB_HOST/PORT/USER/PASSWORD/NAME`; por defecto `oc_test` / `oc_test_pw` / `oceanica_test` en 127.0.0.1:3306). La prueba del instalador necesita además `OCEANICA_TEST_ROOT_PASSWORD` (root de ese servidor desechable); sin ella se omite.
**Borran las tablas de esa base: nunca apuntarlas a la base real.** Sin servidor, se omiten.

## Límites conocidos

- La impresión directa ESC/POS (con el logo) depende de Windows + pywin32 y falta probarla con la impresora real del local.
  En modo RAW, Windows no avisa si la impresora no tiene papel: el ticket puede «imprimirse» sin salir.
- El CI construye en Windows real `Oceanica.exe`, `OceanicaAdmin.exe` y el instalador, comprueba que arrancan y que el respaldo diario se programa. Falta instalarlo en una PC real (cuenta estándar y de administrador) y en la del local.
- No timbra facturas (CFDI): solo controla cuáles hay que hacer. Funciona en una sola computadora.
- Código de barras y lector: pendiente de confirmar con el cliente (issue #1 del repositorio). No está construido; las etiquetas de bolsa son solo texto.
- Nómina no es fiscal: no sustituye CFDI ni obligaciones de IMSS/SAT.
