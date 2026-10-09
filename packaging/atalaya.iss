; Instalador de Atalaya (Inno Setup 6). Lo compila packaging\build.ps1, que pasa:
;   /DAppVersion=<version de shared\about.py>  /DSourceDir=<build\Atalaya>  /DOutputDir=<dist>
; Instala por usuario (sin administrador) en %LOCALAPPDATA%\Programs\Atalaya. Los datos del usuario viven
; aparte, en %LOCALAPPDATA%\Atalaya, y sobreviven a actualizaciones y reinstalaciones.

#ifndef AppVersion
  #error Compile con packaging\build.ps1 (define AppVersion, SourceDir y OutputDir)
#endif

#define AppName "Atalaya"
#define AppPublisher "LindeCode"
#define AppURL "https://github.com/lindecode/Atalaya"
#define OllamaURL "https://ollama.com/download/windows"

[Setup]
AppId={{8F3C2B71-5E4A-4D1B-9C7E-3A6F1D2B8E45}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppCopyright=© 2026 {#AppPublisher}
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\assets\icon.ico
UninstallDisplayName={#AppName}
OutputDir={#OutputDir}
OutputBaseFilename=Atalaya-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Cierra el panel o el monitor si estan abiertos (archivos de runtime\ en uso) durante una actualizacion
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"
Name: "autostart"; Description: "Iniciar Atalaya en segundo plano al entrar en Windows (icono junto al reloj, con el monitor de archivos)"; GroupDescription: "Inicio automático:"; Flags: unchecked
Name: "cycle"; Description: "Analizar el equipo automáticamente cada 5 minutos (recomendado; se cambia en Sistema > Ajustes)"; GroupDescription: "Análisis periódico:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Una actualizacion no debe dejar modulos de versiones anteriores mezclados con los nuevos
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\application"
Type: filesandordirs; Name: "{app}\domain"
Type: filesandordirs; Name: "{app}\infrastructure"
Type: filesandordirs; Name: "{app}\interfaces"
Type: filesandordirs; Name: "{app}\ports"
Type: filesandordirs; Name: "{app}\shared"

[UninstallDelete]
; Python crea __pycache__ al ejecutarse; el desinstalador no los conoce. Los datos del usuario estan en
; %LOCALAPPDATA%\Atalaya, fuera de {app}, y no se tocan aqui.
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\application"
Type: filesandordirs; Name: "{app}\domain"
Type: filesandordirs; Name: "{app}\infrastructure"
Type: filesandordirs; Name: "{app}\interfaces"
Type: filesandordirs; Name: "{app}\ports"
Type: filesandordirs; Name: "{app}\shared"
Type: dirifempty; Name: "{app}"

[Icons]
; Atalaya vive en la bandeja (junto al reloj): pythonw no abre consola y un segundo clic solo abre el panel
Name: "{autoprograms}\{#AppName}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "main.py tray"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"; Comment: "Abrir Atalaya (sigue en segundo plano junto al reloj)"
Name: "{autoprograms}\{#AppName}\Recolectar y analizar"; Filename: "{app}\start\recolectar.bat"; WorkingDir: "{app}\start"; IconFilename: "{app}\assets\icon.ico"
Name: "{autoprograms}\{#AppName}\Diagnóstico"; Filename: "{app}\start\diagnostico.bat"; WorkingDir: "{app}\start"; IconFilename: "{app}\assets\icon.ico"
Name: "{autoprograms}\{#AppName}\Configurar permisos"; Filename: "{app}\start\configurar-permisos.bat"; WorkingDir: "{app}\start"; IconFilename: "{app}\assets\icon.ico"; Comment: "Una sola vez, pide administrador"
Name: "{autoprograms}\{#AppName}\Detener Atalaya"; Filename: "{app}\start\detener.bat"; WorkingDir: "{app}\start"; IconFilename: "{app}\assets\icon.ico"
Name: "{autoprograms}\{#AppName}\Desinstalar Atalaya"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "main.py tray"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "main.py tray --no-browser --monitor"; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"; Tasks: autostart

[Run]
; Same script as start\automatizacion.bat and the Ajustes switch; desinstalar.ps1 removes the task on uninstall
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\start\lib\automatizacion.ps1"" -Accion activar -Minutos 5"; WorkingDir: "{app}\start"; StatusMsg: "Programando el análisis periódico..."; Flags: runhidden waituntilterminated; Tasks: cycle
Filename: "{app}\runtime\pythonw.exe"; Parameters: "main.py tray"; WorkingDir: "{app}"; Description: "Abrir Atalaya (vaya a Sistema > Primeros pasos)"; Flags: postinstall nowait skipifsilent

; La limpieza al desinstalar esta en [Code] (CurUninstallStepChanged) y no en [UninstallRun]: alli los
; Check se evaluan al INSTALAR, y hace falta saber al desinstalar si es silenciosa o interactiva.

[Code]
var
  OllamaPage: TInputOptionWizardPage;

function OllamaInstalled(): Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'))
    or (FileSearch('ollama.exe', GetEnv('PATH')) <> '');
end;

procedure InitializeWizard();
begin
  OllamaPage := CreateInputOptionPage(wpSelectTasks,
    'LLM local (Ollama)',
    'Atalaya usa Ollama para explicar las alertas y para el chat.',
    'No se encontró Ollama en este equipo. Sin él, Atalaya funciona (reglas, alertas, panel) pero sin ' +
    'explicaciones del LLM ni chat. Los modelos (unos 4 GB) se descargan después desde ' +
    'Sistema > IA local.',
    True, False);
  OllamaPage.Add('Instalar Ollama ahora con winget (recomendado)');
  OllamaPage.Add('Abrir la página de descarga de Ollama al terminar');
  OllamaPage.Add('Continuar sin Ollama');
  OllamaPage.SelectedValueIndex := 0;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = OllamaPage.ID) and OllamaInstalled();
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and not OllamaInstalled() then
  begin
    if OllamaPage.SelectedValueIndex = 0 then
    begin
      WizardForm.StatusLabel.Caption := 'Instalando Ollama con winget...';
      if not Exec('winget.exe', 'install --id Ollama.Ollama -e --accept-package-agreements --accept-source-agreements',
                  '', SW_SHOW, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
        MsgBox('No se pudo instalar Ollama con winget (código ' + IntToStr(ResultCode) + '). ' +
               'Puede descargarlo desde {#OllamaURL}', mbInformation, MB_OK);
    end
    else if OllamaPage.SelectedValueIndex = 1 then
      ShellExec('open', '{#OllamaURL}', '', '', SW_SHOWNORMAL, ewNoWait, ResultCode);
  end;
end;

{ Antes de borrar archivos: detiene la bandeja, el panel y el monitor. En modo interactivo ademas ofrece
  revertir los permisos de administrador y pregunta por los datos; en silencioso conserva ambos. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
  Params: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\start\lib\desinstalar.ps1') +
              '" -DesdeDesinstalador';
    if UninstallSilent() then
      Exec('powershell.exe', Params + ' -Silencioso', ExpandConstant('{app}\start'), SW_HIDE, ewWaitUntilTerminated, ResultCode)
    else
      Exec('powershell.exe', Params, ExpandConstant('{app}\start'), SW_SHOW, ewWaitUntilTerminated, ResultCode);
  end;
end;
