; Inno Setup 6: crea dist\Instalar_Oceanica.exe a partir de dist\Oceanica
[Setup]
AppName=Lavandería Oceánica
AppVersion=1.0
AppPublisher=NullSpace Studio
DefaultDirName={autopf}\Oceanica
DefaultGroupName=Lavandería Oceánica
OutputDir=dist
OutputBaseFilename=Instalar_Oceanica
SetupIconFile=oceanica\app\recursos\oceanica.ico
UninstallDisplayIcon={app}\Oceanica.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear acceso directo en el escritorio"; Flags: checkedonce

[Files]
Source: "dist\Oceanica\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Lavandería Oceánica"; Filename: "{app}\Oceanica.exe"
Name: "{autodesktop}\Lavandería Oceánica"; Filename: "{app}\Oceanica.exe"; Tasks: escritorio
Name: "{group}\Actualizar base de datos (migrar)"; Filename: "{app}\OceanicaAdmin.exe"; Parameters: "migrar"
Name: "{group}\Respaldo manual"; Filename: "{app}\OceanicaAdmin.exe"; Parameters: "respaldo --manual"
Name: "{group}\Restablecer contraseña de administrador"; Filename: "{app}\OceanicaAdmin.exe"; Parameters: "restablecer-admin"

; Los pasos corren con la cuenta de Windows de quien abrió el instalador (runasoriginaluser), no con la cuenta de
; administrador que pide Windows: la configuración del sistema y el respaldo programado son de esa cuenta.
[Run]
Filename: "{app}\OceanicaAdmin.exe"; Parameters: "migrar"; Description: "Actualizar la base de datos (hace un respaldo antes)"; Flags: postinstall skipifsilent runasoriginaluser
Filename: "{app}\OceanicaAdmin.exe"; Parameters: "programar-respaldo"; Description: "Programar el respaldo diario"; Flags: postinstall skipifsilent runasoriginaluser
Filename: "{app}\Oceanica.exe"; Description: "Abrir Lavandería Oceánica"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "schtasks.exe"; Parameters: "/Delete /F /TN ""\Oceanica\Respaldo diario"""; Flags: runhidden; RunOnceId: "QuitarRespaldo"
