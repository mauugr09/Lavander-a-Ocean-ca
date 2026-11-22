# Instalar Oceánica Gestión en una PC con Windows

Sin consola, sin comandos y sin instalar nada más.

1. Doble clic en **`Instalar_Oceanica.exe`**.
   - Si Windows muestra «Windows protegió su PC»: **Más información → Ejecutar de todos modos** (el programa no
     está firmado; es normal).
2. **Siguiente → Instalar.** Si la computadora no tiene base de datos, el instalador también instala MariaDB
   (tarda uno o dos minutos). Si ya tiene una, la usa y no la toca.
3. Deje marcada **«Abrir Lavandería Oceánica»** y presione **Finalizar**.
4. La primera vez aparece un asistente. Escriba:
   - el **usuario y la contraseña de la encargada** (con eso se entra al sistema);
   - una **contraseña de recuperación**: solo sirve si la encargada olvida la suya. **Anótela en papel** y guárdela
     fuera de la computadora.

   Si la computadora ya tenía MariaDB, en lugar de la de recuperación le pide la contraseña de root que ya tenía.
5. Presione **Instalar**. Al terminar, entre con el usuario de la encargada.

Desde la segunda vez, basta con abrir **«Lavandería Oceánica»** desde el escritorio.

## Primer uso

1. **Configuración**: nombre del negocio, logo, datos del ticket y, si tiene, la ruta de un USB o disco externo para
   copiar los respaldos.
2. **Servicios y precios**, **Clientes** e **Inventario**: a mano o con «Descargar plantilla» → llenarla en Excel →
   «Importar desde Excel o CSV».
3. **Empleados y usuarios**: cada empleado uno por uno, con su PIN.

## Si algo falla

| Qué pasa | Qué hacer |
|---|---|
| El asistente dice «No se encontró la base de datos» | Espere un momento y presione «Reintentar». Si sigue, reinicie la PC y vuelva a ejecutar el instalador. |
| El programa dice que la base de datos no responde | Reinicie la computadora. |
| La encargada olvidó su contraseña | Menú Inicio → «Restablecer contraseña de administrador» (pide la contraseña de recuperación). |

El detalle de cualquier error queda en `%APPDATA%\OceanicaGestion\logs\oceanica.log`.

## Qué no se prueba en una laptop

- La impresora térmica del local (en impresión directa, Windows no avisa si falta papel).
- La base real del cliente (MariaDB 10.3.9): pruebe primero con una **copia**.
