# Oceánica Gestión

Sistema de escritorio para **Lavandería Oceánica**: mostrador de órdenes, cobros, caja, clientes, inventario,
empleados, asistencia, nómina (control interno), panel del negocio, reportes, tickets y respaldos.

- Python 3.12+ y PySide6 (solo se usan los módulos básicos de PySide6-Essentials).
- MariaDB 10.11 LTS o MySQL 8 (InnoDB, `utf8mb4_unicode_ci`). MariaDB 10.3+ funciona, pero ya no tiene soporte.
- Se inicia con `python -m oceanica` (o doble clic en `iniciar_oceanica.bat`).

## Para el equipo: actualizar después de `git pull`

Cada quien trabaja con **su propia base de datos**; el repositorio solo lleva el código. Después de descargar cambios:

```
git pull
python -m oceanica.migrar      # aplica a SU base los cambios de estructura, sin borrar datos
python -m oceanica
```

Primera vez en una computadora: `pip install -r requirements.txt` y `python -m oceanica.init_db` (ver «Instalación»).
Para tener datos con qué probar: `python -m oceanica.datos_demo` (ver «Datos de ejemplo»).

## Estructura

| Ruta | Contenido |
|---|---|
| `db/migrations/001..009` | Esquema (27 tablas), vistas de reportes, datos iniciales, reglas del backend, PIN y transferencias por confirmar, respuestas del cliente, categorías del mostrador, servicio a domicilio y textos del ticket |
| `oceanica/init_db.py` · `configurar.py` · `migrar.py` | Instalación (crea la base, un usuario MySQL limitado y el primer administrador), conexión a una base existente y actualización |
| `oceanica/respaldos.py` | Respaldo `.sql.gz` con mysqldump, copia externa, retención y restauración |
| `oceanica/seguridad.py` | bcrypt, política de contraseñas, PIN, bloqueo tras 5 intentos (15 min) y bitácora |
| `oceanica/datos_demo.py` | Datos de ejemplo para probar (nunca en la lavandería) |
| `oceanica/servicios/` | Reglas de negocio: usuarios, configuración, clientes, catálogo, caja, órdenes, inventario, empleados, nómina, reportes, panel, exportación, tickets y carga inicial |
| `oceanica/app/` | Interfaz PySide6: entrada, mostrador, órdenes, caja, asistencia, clientes, inventario y, para el administrador, panel, reportes, nómina, servicios y precios, empleados, transferencias y configuración |
| `oceanica/app/botones.py` · `cobro.py` · `graficas.py` · `iconos.py` · `burbujas.py` | Botones grandes y teclado numérico, cobro por pasos, gráficas dibujadas con QPainter, íconos SVG y animación de la entrada |
| `oceanica/app/recursos/` | Logo, ícono e íconos de línea (Tabler Icons, licencia MIT) |
| `tests/` | 128 pruebas (esquema, seguridad, servicios e interfaz contra una base real) |

## Instalación en la PC del local

1. Instalar MariaDB 10.11 LTS o MySQL 8 como servicio de Windows y agregar su carpeta `bin` al PATH.
2. `pip install -r requirements.txt`
3. Primera vez: `python -m oceanica.init_db` (pide la contraseña de root una sola vez y no la guarda; el sistema nunca usa root). Si la base y `oceanica_app` ya existen: `python -m oceanica.configurar`. La configuración queda en `%APPDATA%\OceanicaGestion`, fuera de la carpeta del programa.
4. Programador de tareas de Windows, diario: `python -m oceanica.respaldos --auto`.
5. Al recibir una versión nueva: respaldo manual y `python -m oceanica.migrar`.

`config.ini` (en `%APPDATA%\OceanicaGestion`, junto con respaldos, logs y tickets) contiene la contraseña de la base: no se comparte ni se sube al repositorio.

En Windows con procesador ARM el conector de MySQL no tiene su parte en C; el sistema usa entonces la versión en Python automáticamente.

## Generar el programa para Windows (.exe e instalador)

En la PC con Windows (Python 3.12+ con «Add to PATH»): doble clic en `construir_exe.bat`.
- Crea `dist\Oceanica\` con `Oceanica.exe` (el programa) y `OceanicaAdmin.exe` (con consola, para `migrar`, `configurar`, `instalar` y `respaldo --auto`).
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
- Atajos: F2 buscar servicio · F3 cliente · F4 cliente nuevo · F5 guardar y cobrar · Esc regresar · F6 cobrar lo pendiente · F7 entregar · Ctrl+1…9 cambiar de sección.

### Caja y corte
- Al iniciar el día: contar el efectivo y **Abrir caja** con ese fondo. Sin caja abierta no se puede cobrar.
- Gastos, ingresos y retiros: **Registrar gasto, ingreso o retiro**.
- Al cerrar: **Cerrar caja (corte del día)**, escribir el efectivo contado; si no coincide con lo esperado, se pide la explicación. Sale el ticket del corte. Historial en Reportes → Cortes de caja.

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

## Datos de ejemplo (solo para probar)

En una base de pruebas: `python -m oceanica.datos_demo`. Crea servicios con precios, 3 empleados con PIN (Rosa 482615, Jorge 739164, Patricia 516273), 20 clientes, insumos y un año de órdenes cobradas, más órdenes abiertas en varios estados. Si la base ya tiene órdenes no hace nada (`--forzar` lo permite). **Nunca se ejecuta en la computadora de la lavandería.**

## Pruebas

`python -m pytest`. Necesitan un servidor MySQL/MariaDB con un usuario de pruebas (variables `OCEANICA_TEST_DB_HOST/PORT/USER/PASSWORD/NAME`; por defecto `oc_test` / `oc_test_pw` / `oceanica_test` en 127.0.0.1:3306).
**Borran las tablas de esa base: nunca apuntarlas a la base real.** Sin servidor, se omiten.

## Límites conocidos

- La impresión directa ESC/POS (con el logo) depende de Windows + pywin32 y falta probarla con la impresora real del local.
- No emite facturas (CFDI) y funciona en una sola computadora.
- Nómina no es fiscal: no sustituye CFDI ni obligaciones de IMSS/SAT.
