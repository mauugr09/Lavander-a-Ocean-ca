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

[Run]
Filename: "{app}\OceanicaAdmin.exe"; Parameters: "migrar"; Description: "Actualizar la base de datos"; Flags: postinstall skipifsilent runascurrentuser
Filename: "{app}\Oceanica.exe"; Description: "Abrir Lavandería Oceánica"; Flags: postinstall nowait skipifsilent
