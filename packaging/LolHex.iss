; 海克斯大乱斗助手（游戏机）安装包。先运行 packaging/build.ps1。
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6C7B2E0B-3F5B-4B7E-9C8A-1D6E4F2A9B31}
AppName=海克斯大乱斗助手
AppVersion={#AppVersion}
AppPublisher=LolHex
DefaultDirName={localappdata}\Programs\LolHex
DefaultGroupName=海克斯大乱斗助手
; 装到用户目录，不需要管理员权限
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\build\installer
OutputBaseFilename=LolHex-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=海克斯大乱斗助手
UninstallDisplayIcon={app}\LolHex.exe
CloseApplications=force
SetupIconFile=lolhex.ico

[Languages]
Name: "chs"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："

[Files]
Source: "..\build\dist\LolHex\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\海克斯大乱斗助手"; Filename: "{app}\LolHex.exe"
Name: "{group}\卸载海克斯大乱斗助手"; Filename: "{uninstallexe}"
Name: "{userdesktop}\海克斯大乱斗助手"; Filename: "{app}\LolHex.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LolHex.exe"; Description: "立即启动"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/c taskkill /im LolHex.exe /f"; Flags: runhidden; RunOnceId: "KillLolHex"
