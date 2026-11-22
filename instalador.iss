; Inno Setup 6: crea dist\Instalar_Oceanica.exe a partir de dist\Oceanica
[Setup]
AppName=Lavandería Oceánica
AppVersion=1.1
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
; MariaDB 10.11 LTS: solo se instala si la computadora no tiene ya MariaDB o MySQL (la del local tiene datos reales).
Source: "dist\mariadb.msi"; Flags: dontcopy

[Icons]
Name: "{group}\Lavandería Oceánica"; Filename: "{app}\Oceanica.exe"
Name: "{autodesktop}\Lavandería Oceánica"; Filename: "{app}\Oceanica.exe"; Tasks: escritorio
Name: "{group}\Respaldo manual"; Filename: "{app}\OceanicaAdmin.exe"; Parameters: "respaldo --manual"
Name: "{group}\Restablecer contraseña de administrador"; Filename: "{app}\OceanicaAdmin.exe"; Parameters: "restablecer-admin"

; La primera vez que se abre, el programa muestra un asistente que crea la base y la cuenta de la encargada.
; La base de datos se pone al día sola cuando se abre el programa (con respaldo previo): no hay paso de «migrar».
; El respaldo programado corre con la cuenta de Windows de quien abrió el instalador (runasoriginaluser), no con la
; cuenta de administrador que pide Windows: la configuración del sistema es de esa cuenta.
[Run]
Filename: "{app}\OceanicaAdmin.exe"; Parameters: "programar-respaldo"; Description: "Programar el respaldo diario"; Flags: postinstall skipifsilent runasoriginaluser
Filename: "{app}\Oceanica.exe"; Description: "Abrir Lavandería Oceánica"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "schtasks.exe"; Parameters: "/Delete /F /TN ""\Oceanica\Respaldo diario"""; Flags: runhidden; RunOnceId: "QuitarRespaldo"

[Code]
var
  TieneBaseDeDatos: Boolean;

{ ¿Ya hay un servicio de MariaDB o MySQL? Entonces no se instala otro: se usaría el mismo puerto y sus datos. }
function HayServicioMariaDBoMySQL(): Boolean;
var
  Nombres: TArrayOfString;
  I: Integer;
  N: String;
begin
  Result := False;
  if RegGetSubkeyNames(HKLM, 'SYSTEM\CurrentControlSet\Services', Nombres) then
    for I := 0 to GetArrayLength(Nombres) - 1 do
    begin
      N := Lowercase(Nombres[I]);
      if (Pos('mariadb', N) = 1) or (Pos('mysql', N) = 1) then
      begin
        Result := True;
        Exit;
      end;
    end;
end;

function InitializeSetup(): Boolean;
begin
  TieneBaseDeDatos := HayServicioMariaDBoMySQL();
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Codigo: Integer;
begin
  if (CurStep = ssPostInstall) and (not TieneBaseDeDatos) then
  begin
    WizardForm.StatusLabel.Caption := 'Instalando la base de datos (MariaDB). Esto tarda uno o dos minutos...';
    ExtractTemporaryFile('mariadb.msi');
    { Sin PASSWORD: root queda sin contraseña solo hasta la primera vez que se abre el programa, cuyo asistente
      le pone la «contraseña de recuperación». MariaDB no acepta root desde la red por omisión. }
    if not Exec('msiexec.exe', '/i "' + ExpandConstant('{tmp}\mariadb.msi') + '" /qn /norestart SERVICENAME=MariaDB PORT=3306 UTF8=1',
                '', SW_HIDE, ewWaitUntilTerminated, Codigo) or ((Codigo <> 0) and (Codigo <> 3010)) then
      MsgBox('No se pudo instalar la base de datos (código ' + IntToStr(Codigo) + ').' + #13#10 +
             'Reinicie la computadora y vuelva a ejecutar este instalador.', mbError, MB_OK);
  end;
end;
