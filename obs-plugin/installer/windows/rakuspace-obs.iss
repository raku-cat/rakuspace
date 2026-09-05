; Inno Setup script for the RakuSpace OBS plugin (Windows).
;
; Installs to the non-legacy, per-machine OBS plugin location
; (%ProgramData%\obs-studio\plugins\<name>), matching this repo's
; CMAKE_INSTALL_PREFIX default in cmake/windows/defaults.cmake.
;
; Build with (from a Windows build/release directory laid out as
; rakuspace-obs/bin/64bit/rakuspace-obs.dll and rakuspace-obs/data/...):
;   ISCC installer\windows\rakuspace-obs.iss /DSourceDir=path\to\release\dir
;
; SourceDir defaults to a sibling "payload" directory for local testing.

#ifndef SourceDir
  #define SourceDir "payload"
#endif

#define MyAppName "RakuSpace"
#define MyAppId "rakuspace-obs"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "RakuSpace"
#define MyAppURL "https://rakuspace.site"

[Setup]
; Fixed GUID, do not change between releases: identifies this app for
; upgrades/uninstalls in Add/Remove Programs.
AppId={{01E940EA-4F9B-4554-99BE-AA67D7FA5F6E}
AppName={#MyAppName} OBS Plugin
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
VersionInfoVersion={#MyAppVersion}
DefaultDirName={commonappdata}\obs-studio\plugins\{#MyAppId}
; Fixed, machine-wide install location: not user-choosable, so skip the
; directory selection page.
DisableDirPage=yes
DisableProgramGroupPage=yes
; %ProgramData%\obs-studio is created by OBS itself with write access for
; regular users, so this installer doesn't need to force elevation; still
; allow a user or the command line to request admin if that ACL isn't
; there (e.g. OBS not yet installed).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
LicenseFile=..\..\LICENSE
OutputBaseFilename=rakuspace-obs-{#MyAppVersion}-windows-x64-Setup
OutputDir=..\..\release
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayName={#MyAppName} OBS Plugin
; No code signing certificate for this build; expect an unsigned-binary
; SmartScreen prompt on first run.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#SourceDir}\bin\64bit\{#MyAppId}.dll"; DestDir: "{app}\bin\64bit"; Flags: ignoreversion
Source: "{#SourceDir}\data\locale\*"; DestDir: "{app}\data\locale"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
