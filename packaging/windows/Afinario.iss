#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define ProjectRoot SourcePath + "..\.."

[Setup]
AppId={{7D512EBC-B0D6-438D-9CF0-E0BDA545CB29}
AppName=Afinário
AppVersion={#AppVersion}
AppPublisher=Afinário
AppPublisherURL=https://github.com/tpklge/Afinario
DefaultDirName={localappdata}\Programs\Afinario
DefaultGroupName=Afinário
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
OutputDir={#ProjectRoot}\dist\installers
OutputBaseFilename=Afinario-{#AppVersion}-windows-x64-setup
UninstallDisplayIcon={app}\Afinario.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
InfoAfterFile={#ProjectRoot}\packaging\windows\LEIA-ME.txt

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; Flags: checkedonce

[Files]
Source: "{#ProjectRoot}\dist\Afinario\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjectRoot}\packaging\windows\LEIA-ME.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Afinário"; Filename: "{app}\Afinario.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Afinário"; Filename: "{app}\Afinario.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\Desinstalar Afinário"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\Afinario.exe"; Description: "Abrir Afinário"; Flags: nowait postinstall skipifsilent
