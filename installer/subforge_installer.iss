; subforge_installer.iss
; Inno Setup installer script for SubForge.
;
; Prerequisites:
;   1. Run PyInstaller first:  python -m PyInstaller subforge.spec
;   2. Confirm dist\SubForge\SubForge.exe exists
;   3. Open this file in Inno Setup Compiler and click Build > Compile
;      (or run: iscc subforge_installer.iss from the repo root)
;
; Output:
;   Output\SubForge-1.1.0-setup.exe
;
; Inno Setup download: https://jrsoftware.org/isinfo.php

#define AppName      "SubForge"
#define AppVersion   "1.1.0"
#define AppPublisher "David R. Babcock"
#define AppURL       "https://github.com/babcockdavidr/SubForge"
#define AppExeName   "SubForge.exe"
#define DistDir      "..\dist\SubForge"

[Setup]
AppId={{A7F3C2D1-4B8E-4F9A-B2C3-D4E5F6A7B8C9}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
; installer output location and filename
OutputDir=Output
OutputBaseFilename=SubForge-{#AppVersion}-setup
; compression
Compression=lzma2/ultra64
SolidCompression=yes
; require 64-bit Windows
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; minimum Windows version: Windows 10
MinVersion=10.0
; appearance
WizardStyle=modern
SetupIconFile=..\subforge.ico
WizardSmallImageFile=..\subforge-white-small.png
SetupMutex=SubForgeSetupMutex
; require admin for Program Files install
PrivilegesRequired=admin
; suppress per-user area warning — AppData cleanup is handled in [Code]
; at runtime using ExpandConstant so it resolves to the correct user
UsedUserAreasWarning=no
; uninstaller
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";     Description: "{cm:CreateDesktopIcon}";                            GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "fileassoc_srt";   Description: "Associate .srt subtitle files with SubForge";       GroupDescription: "File associations:"; Flags: unchecked
Name: "fileassoc_ass";   Description: "Associate .ass subtitle files with SubForge";       GroupDescription: "File associations:"; Flags: unchecked
Name: "fileassoc_ssa";   Description: "Associate .ssa subtitle files with SubForge";       GroupDescription: "File associations:"; Flags: unchecked
Name: "fileassoc_vtt";   Description: "Associate .vtt subtitle files with SubForge";       GroupDescription: "File associations:"; Flags: unchecked
Name: "fileassoc_ttml";  Description: "Associate .ttml subtitle files with SubForge";      GroupDescription: "File associations:"; Flags: unchecked
Name: "fileassoc_sami";  Description: "Associate .sami/.smi subtitle files with SubForge"; GroupDescription: "File associations:"; Flags: unchecked
Name: "fileassoc_sub";   Description: "Associate .sub subtitle files with SubForge";       GroupDescription: "File associations:"; Flags: unchecked

[Files]
; Bundle the entire PyInstaller output folder
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Explicitly install the app icon so shortcuts can reference it directly
Source: "..\subforge.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu shortcut
Name: "{group}\{#AppName}";              Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\subforge.ico"
Name: "{group}\Uninstall {#AppName}";   Filename: "{uninstallexe}"
; Desktop shortcut (only if task selected)
Name: "{autodesktop}\{#AppName}";       Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\subforge.ico"; Tasks: desktopicon

[Registry]
; ── .srt ──────────────────────────────────────────────────────────────────────
; The first association task (srt) also registers the ProgID and open command
; that all other extensions share. The ProgID keys use uninsdeletekey so the
; entire SubForge.subtitle class is removed cleanly on uninstall (only when
; the srt task was selected — other tasks only add the extension pointer).
Root: HKLM; Subkey: "Software\Classes\.srt";                                 ValueType: string; ValueName: ""; ValueData: "SubForge.subtitle"; Flags: uninsdeletevalue; Tasks: fileassoc_srt
Root: HKLM; Subkey: "Software\Classes\SubForge.subtitle";                    ValueType: string; ValueName: ""; ValueData: "Subtitle File";      Flags: uninsdeletekey;   Tasks: fileassoc_srt
Root: HKLM; Subkey: "Software\Classes\SubForge.subtitle\DefaultIcon";        ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExeName},0"; Tasks: fileassoc_srt
Root: HKLM; Subkey: "Software\Classes\SubForge.subtitle\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: fileassoc_srt

; ── .ass ──────────────────────────────────────────────────────────────────────
Root: HKLM; Subkey: "Software\Classes\.ass";                                 ValueType: string; ValueName: ""; ValueData: "SubForge.subtitle"; Flags: uninsdeletevalue; Tasks: fileassoc_ass
Root: HKLM; Subkey: "Software\Classes\SubForge.subtitle\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: fileassoc_ass

; ── .ssa ──────────────────────────────────────────────────────────────────────
Root: HKLM; Subkey: "Software\Classes\.ssa";                                 ValueType: string; ValueName: ""; ValueData: "SubForge.subtitle"; Flags: uninsdeletevalue; Tasks: fileassoc_ssa
Root: HKLM; Subkey: "Software\Classes\SubForge.subtitle\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: fileassoc_ssa

; ── .vtt ──────────────────────────────────────────────────────────────────────
Root: HKLM; Subkey: "Software\Classes\.vtt";                                 ValueType: string; ValueName: ""; ValueData: "SubForge.subtitle"; Flags: uninsdeletevalue; Tasks: fileassoc_vtt
Root: HKLM; Subkey: "Software\Classes\SubForge.subtitle\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: fileassoc_vtt

; ── .ttml ─────────────────────────────────────────────────────────────────────
Root: HKLM; Subkey: "Software\Classes\.ttml";                                ValueType: string; ValueName: ""; ValueData: "SubForge.subtitle"; Flags: uninsdeletevalue; Tasks: fileassoc_ttml
Root: HKLM; Subkey: "Software\Classes\SubForge.subtitle\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: fileassoc_ttml

; ── .sami / .smi ──────────────────────────────────────────────────────────────
Root: HKLM; Subkey: "Software\Classes\.sami";                                ValueType: string; ValueName: ""; ValueData: "SubForge.subtitle"; Flags: uninsdeletevalue; Tasks: fileassoc_sami
Root: HKLM; Subkey: "Software\Classes\.smi";                                 ValueType: string; ValueName: ""; ValueData: "SubForge.subtitle"; Flags: uninsdeletevalue; Tasks: fileassoc_sami
Root: HKLM; Subkey: "Software\Classes\SubForge.subtitle\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: fileassoc_sami

; ── .sub (MicroDVD) ───────────────────────────────────────────────────────────
Root: HKLM; Subkey: "Software\Classes\.sub";                                 ValueType: string; ValueName: ""; ValueData: "SubForge.subtitle"; Flags: uninsdeletevalue; Tasks: fileassoc_sub
Root: HKLM; Subkey: "Software\Classes\SubForge.subtitle\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Tasks: fileassoc_sub

[Run]
; offer to launch SubForge after install
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; clean up settings.json left behind in the install folder on uninstall
Type: files; Name: "{app}\settings.json"

[Code]
// Delete %APPDATA%\SubForge on uninstall.
// Using ExpandConstant at runtime ensures the path resolves to the actual
// logged-in user's AppData, not the administrator account's AppData.
// This covers Whisper model cache and crash logs stored there.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    AppDataDir := ExpandConstant('{userappdata}') + '\SubForge';
    if DirExists(AppDataDir) then
      DelTree(AppDataDir, True, True, True);
  end;
end;
