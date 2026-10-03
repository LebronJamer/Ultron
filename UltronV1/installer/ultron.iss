; =====================================================================
; Ultron — Inno Setup script (professional setup.exe)
; Build:  ISCC.exe /DMyAppVersion=1.0.0 installer\ultron.iss
; Output: installer\Output\UltronSetup-<version>-x64.exe
; =====================================================================

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "Ultron"
#define MyAppPublisher "UltronV1 Project"
#define MyAppURL "https://github.com/LebronJamer/Ultron"
#define MyAppExeName "Ultron.exe"
#define MyAppId "{{FA8AF853-69F8-49C7-BA08-C44CA05EE5FF}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE.txt
OutputDir=Output
OutputBaseFilename=UltronSetup-{#MyAppVersion}-x64
SetupIconFile=..\app\assets\icons\icon.ico
WizardImageFile=..\app\assets\icons\banner.bmp
WizardSmallImageFile=..\app\assets\icons\small.bmp
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=This will install [name/ver] — a local, offline voice assistant for Windows with an attitude to match.%n%nIt is recommended that you close all other applications before continuing.

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"
Name: "launchatstart"; Description: "Start Ultron when Windows starts"; GroupDescription: "Additional tasks:"; Flags: unchecked

[Files]
Source: "..\dist\Ultron\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; optional autostart (task-driven)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Ultron"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: launchatstart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

; NOTE: per-user data in %APPDATA%\Ultron (config, logs, models) is kept on
; uninstall so a future reinstall restores your settings.
