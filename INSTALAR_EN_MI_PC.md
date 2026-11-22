# Instalar Oceánica Gestión en una PC con Windows

Versión: `main`, commit `0f747e5` (22 de noviembre de 2026). Guía para probar el sistema en **tu propia
computadora** antes de llevarlo al local.

> **Importante:** en tu PC usa una base de prueba (`oceanica`, recién creada), nunca una copia sin respaldo de la base
> del cliente. Lo que hagas aquí no afecta al local.

---

## 1. Conseguir el instalador (`Instalar_Oceanica.exe`)

El zip **no trae el `.exe`**: se construye en Windows y este paquete se preparó en Linux. Hay dos caminos:

### Opción A: descargarlo ya construido (recomendada, 1 minuto)

El CI de GitHub lo construyó y probó en Windows real para este mismo commit.

1. Con tu sesión de GitHub abierta, entra a:
   <https://github.com/mauugr09/Lavander-a-Ocean-ca/actions/runs/44989215829>
2. Abajo, en **Artifacts**, descarga **`Instalar_Oceanica`** (≈ 44 MB).
3. Descomprime el zip: dentro está `Instalar_Oceanica.exe`.

Los artefactos caducan: el instalador a los 30 días (hacia el 21 de diciembre de 2026). Después, usa la opción B o
vuelve a correr el CI («Actions» → «CI» → «Run workflow»).

### Opción B: construirlo tú

1. Instala **Python 3.12 o superior** desde python.org, marcando **«Add python.exe to PATH»**.
2. (Opcional, para el instalador) instala **Inno Setup 6** desde jrsoftware.org.
3. Descomprime este zip y da doble clic en **`construir_exe.bat`**. Tarda unos minutos.
4. Resultado:
   - con Inno Setup: `dist\Instalar_Oceanica.exe`;
   - sin Inno Setup: la carpeta `dist\Oceanica\` con `Oceanica.exe` y `OceanicaAdmin.exe` (funciona igual, solo que sin
     accesos directos ni respaldo programado automáticamente).

---

## 2. Instalar MariaDB (una sola vez)

1. Descarga **MariaDB 10.11 LTS** para Windows (instalador `.msi`) desde mariadb.org.
2. Durante la instalación:
   - pon una **contraseña de root** y **anótala en un lugar seguro**: el sistema la pide una vez al instalar y
     también para «Restablecer contraseña de administrador»;
   - deja marcado **«Install as service»**.
3. Agrega la carpeta `bin` de MariaDB al PATH (normalmente `C:\Program Files\MariaDB 10.11\bin`):
   Inicio → «variables de entorno» → Variables del sistema → `Path` → Editar → Nuevo.
4. Comprueba en una consola nueva (`cmd`):

   ```
   mysqldump --version
   ```

   Si dice «no se reconoce como un comando», el PATH no quedó bien y **los respaldos no van a funcionar**.

---

## 3. Instalar el programa

1. Ejecuta **`Instalar_Oceanica.exe`** (pide permisos de administrador). Se instala en `C:\Program Files\Oceanica`.
2. Al final deja marcada **«Programar el respaldo diario»**: crea una tarea de Windows a las 21:00 (o al encender la PC
   si estaba apagada).
3. Abre una consola **en la carpeta del programa** y crea la base:

   ```
   cd "C:\Program Files\Oceanica"
   OceanicaAdmin.exe instalar
   ```

   Te pregunta (Enter acepta lo que está entre corchetes):
   - Servidor `[127.0.0.1]`, base `[oceanica]`, usuario del sistema `[oceanica_app]`;
   - la contraseña de root de MariaDB (no se guarda);
   - el usuario y la contraseña de la **encargada** (la administradora).

4. Abre **«Lavandería Oceánica»** desde el escritorio o el menú Inicio y entra con la cuenta de la encargada.

---

## 4. Primer uso

1. **Configuración**: nombre del negocio, logo, datos del ticket y, si tienes, la ruta de un USB o disco externo para
   copiar los respaldos.
2. **Servicios y precios**: «Descargar plantilla» → llénala en Excel → «Importar desde Excel o CSV». O captúralos a mano.
3. **Clientes** e **Inventario**: igual, con plantilla o a mano.
4. **Empleados y usuarios**: da de alta a cada empleado **uno por uno** con su PIN (no se importan a propósito).
5. Abre caja, haz una orden de prueba, cóbrala, entrégala y haz el corte. Imprime el ticket como PDF si no tienes
   la térmica conectada.

---

## 5. Si algo falla

| Síntoma | Qué revisar |
|---|---|
| «No se pudo conectar a la base» | Que el servicio **MariaDB** esté iniciado (Inicio → «Servicios»). |
| El respaldo no se crea | `mysqldump --version` en una consola nueva (paso 2.4). |
| El programa no abre después de actualizar | `%APPDATA%\OceanicaGestion\logs\oceanica.log`: ahí está el detalle y cómo regresar. |
| Olvidaste la contraseña de la encargada | Menú Inicio → «Restablecer contraseña de administrador» (pide root). |

Todo lo del programa (configuración, logs, respaldos y tickets) está en `%APPDATA%\OceanicaGestion`.
`config.ini` contiene la contraseña de la base: **no lo compartas**.

## 6. Quitarlo de tu PC cuando termines de probar

- Panel de control → Desinstalar «Lavandería Oceánica» (también borra la tarea del respaldo diario).
- La base queda en MariaDB; para borrarla:
  `mysql -u root -p -e "DROP DATABASE oceanica; DROP USER 'oceanica_app'@'localhost', 'oceanica_app'@'127.0.0.1', 'oceanica_app'@'::1';"`
- Los datos de `%APPDATA%\OceanicaGestion` se quedan; bórralos a mano si ya no los quieres.

---

## Qué **no** prueba tu PC (hay que hacerlo en el local)

- La impresora térmica de 80 mm del local (en impresión directa, Windows no avisa si falta papel).
- La base real del cliente (MariaDB 10.3.9): pruébala sobre una **copia**, nunca sobre la original.
- Una semana en paralelo con la libreta.
