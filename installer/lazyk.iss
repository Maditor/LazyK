; LazyK installer (Inno Setup 6). Build it with build_installer.bat.
; Everything LazyK needs (Python, OpenCV, numpy...) is already inside dist\LazyK,
; so users do NOT need Python: the installer just copies that folder.

#define AppName "LazyK"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6E0B7C1A-3F5D-4C2B-9A77-1B2C4D5E6F70}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Maditor
AppPublisherURL=https://github.com/Maditor/LazyK
AppSupportURL=https://github.com/Maditor/LazyK/issues
; Per-user install: no admin prompt, and LazyK can write settings.json / logs next to the exe
; (Program Files would be read-only for it).
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\Output
OutputBaseFilename=LazyK-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\LazyK.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
; settings.json (your API keys) and logs stay out of the installer
Source: "..\dist\LazyK\*"; DestDir: "{app}"; Excludes: "settings.json*,\logs\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\LazyK.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\LazyK.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LazyK.exe"; Description: "Start LazyK now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; logs and settings (with the API keys) are created at runtime, remove them too
Type: filesandordirs; Name: "{app}\logs"
Type: files; Name: "{app}\settings.json*"
