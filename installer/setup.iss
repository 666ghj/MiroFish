; MiroFish 安装程序脚本
; 使用 Inno Setup 6.x 编译
; 中文界面，包含 API 配置页面

#define MyAppName "MiroFish"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "MiroFish Team"
#define MyAppURL "https://github.com/666ghj/MiroFish"
#define MyAppExeName "MiroFish.exe"

[Setup]
; 基本信息
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; 安装目录
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; 输出设置
OutputDir=output
OutputBaseFilename=MiroFish_Setup_{#MyAppVersion}
SetupIconFile=MiroFish.ico
UninstallDisplayIcon={app}\MiroFish.ico

; 压缩设置
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; 权限设置
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

; 向导设置
WizardStyle=modern
WizardSizePercent=100

; 语言设置 - 使用中文
[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[CustomMessages]
chinesesimplified.ConfigTitle=API 配置
chinesesimplified.ConfigSubtitle=请填写必要的 API 密钥
chinesesimplified.ConfigInfo=提示: LLM 推荐使用阿里百炼平台 qwen-plus 模型，ZEP 每月免费额度即可支撑简单使用。
chinesesimplified.LLMApiKeyLabel=LLM API Key (必填):
chinesesimplified.LLMBaseURLLabel=LLM Base URL (可保持默认):
chinesesimplified.LLMModelNameLabel=LLM 模型名称 (可保持默认):
chinesesimplified.ZEPApiKeyLabel=ZEP API Key (必填):
chinesesimplified.LLMApiKeyRequired=请输入 LLM API Key！
chinesesimplified.ZEPApiKeyRequired=请输入 ZEP API Key！

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项:"
Name: "quicklaunchicon"; Description: "创建快速启动栏快捷方式"; GroupDescription: "附加选项:"; Flags: unchecked

[Files]
; 主程序文件（包含 MiroFish.exe、backend、frontend、python 目录）
Source: "..\dist\MiroFish\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 图标文件
Source: "MiroFish.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\MiroFish.ico"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\MiroFish.ico"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  ConfigPage: TInputQueryWizardPage;
  LLMApiKeyEdit: TNewEdit;
  LLMBaseURLEdit: TNewEdit;
  LLMModelNameEdit: TNewEdit;
  ZEPApiKeyEdit: TNewEdit;

procedure InitializeWizard;
var
  LabelHeight: Integer;
  EditHeight: Integer;
  VerticalSpacing: Integer;
  TopPos: Integer;
  LabelLLMApiKey, LabelLLMBaseURL, LabelLLMModelName, LabelZEPApiKey: TLabel;
  InfoLabel: TNewStaticText;
begin
  LabelHeight := 16;
  EditHeight := 23;
  VerticalSpacing := 8;
  // 增加初始 TopPos，避免与页面顶部说明重叠
  TopPos := 10;

  // 创建自定义配置页面
  ConfigPage := CreateInputQueryPage(wpSelectDir,
    CustomMessage('ConfigTitle'), 
    CustomMessage('ConfigSubtitle'),
    '');  // 移除这一行的长文本，改用 InfoLabel 显示，以便更好地控制布局

  // 添加说明信息 (灰色斜体)
  InfoLabel := TNewStaticText.Create(ConfigPage);
  InfoLabel.Parent := ConfigPage.Surface;
  InfoLabel.Caption := CustomMessage('ConfigInfo');
  InfoLabel.Left := 0;
  InfoLabel.Top := TopPos;
  InfoLabel.AutoSize := False;
  InfoLabel.Width := ConfigPage.SurfaceWidth;
  InfoLabel.WordWrap := True;  // 允许自动换行
  InfoLabel.Font.Style := [fsItalic];
  InfoLabel.Font.Color := clGray;
  WizardForm.AdjustLabelHeight(InfoLabel);
  
  // 重新计算 TopPos，根据文本实际高度 + 额外间距
  TopPos := TopPos + InfoLabel.Height + 20;

  // 1. LLM API Key
  LabelLLMApiKey := TLabel.Create(ConfigPage);
  LabelLLMApiKey.Parent := ConfigPage.Surface;
  LabelLLMApiKey.Caption := CustomMessage('LLMApiKeyLabel');
  LabelLLMApiKey.Left := 0;
  LabelLLMApiKey.Top := TopPos;
  TopPos := TopPos + LabelHeight + VerticalSpacing;

  LLMApiKeyEdit := TNewEdit.Create(ConfigPage);
  LLMApiKeyEdit.Parent := ConfigPage.Surface;
  LLMApiKeyEdit.Left := 0;
  LLMApiKeyEdit.Top := TopPos;
  LLMApiKeyEdit.Width := ConfigPage.SurfaceWidth;
  LLMApiKeyEdit.Height := EditHeight;
  LLMApiKeyEdit.Text := '';
  
  TopPos := TopPos + EditHeight + 12; // 组间距加大

  // 2. LLM Base URL
  LabelLLMBaseURL := TLabel.Create(ConfigPage);
  LabelLLMBaseURL.Parent := ConfigPage.Surface;
  LabelLLMBaseURL.Caption := CustomMessage('LLMBaseURLLabel');
  LabelLLMBaseURL.Left := 0;
  LabelLLMBaseURL.Top := TopPos;
  TopPos := TopPos + LabelHeight + VerticalSpacing;

  LLMBaseURLEdit := TNewEdit.Create(ConfigPage);
  LLMBaseURLEdit.Parent := ConfigPage.Surface;
  LLMBaseURLEdit.Left := 0;
  LLMBaseURLEdit.Top := TopPos;
  LLMBaseURLEdit.Width := ConfigPage.SurfaceWidth;
  LLMBaseURLEdit.Height := EditHeight;
  LLMBaseURLEdit.Text := 'https://dashscope.aliyuncs.com/compatible-mode/v1';
  
  TopPos := TopPos + EditHeight + 12;

  // 3. LLM Model Name
  LabelLLMModelName := TLabel.Create(ConfigPage);
  LabelLLMModelName.Parent := ConfigPage.Surface;
  LabelLLMModelName.Caption := CustomMessage('LLMModelNameLabel');
  LabelLLMModelName.Left := 0;
  LabelLLMModelName.Top := TopPos;
  TopPos := TopPos + LabelHeight + VerticalSpacing;

  LLMModelNameEdit := TNewEdit.Create(ConfigPage);
  LLMModelNameEdit.Parent := ConfigPage.Surface;
  LLMModelNameEdit.Left := 0;
  LLMModelNameEdit.Top := TopPos;
  LLMModelNameEdit.Width := ConfigPage.SurfaceWidth;
  LLMModelNameEdit.Height := EditHeight;
  LLMModelNameEdit.Text := 'qwen-plus';
  
  TopPos := TopPos + EditHeight + 12;

  // 4. ZEP API Key
  LabelZEPApiKey := TLabel.Create(ConfigPage);
  LabelZEPApiKey.Parent := ConfigPage.Surface;
  LabelZEPApiKey.Caption := CustomMessage('ZEPApiKeyLabel');
  LabelZEPApiKey.Left := 0;
  LabelZEPApiKey.Top := TopPos;
  TopPos := TopPos + LabelHeight + VerticalSpacing;

  ZEPApiKeyEdit := TNewEdit.Create(ConfigPage);
  ZEPApiKeyEdit.Parent := ConfigPage.Surface;
  ZEPApiKeyEdit.Left := 0;
  ZEPApiKeyEdit.Top := TopPos;
  ZEPApiKeyEdit.Width := ConfigPage.SurfaceWidth;
  ZEPApiKeyEdit.Height := EditHeight;
  ZEPApiKeyEdit.Text := '';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  
  // 在配置页面验证必填项
  if CurPageID = ConfigPage.ID then
  begin
    if Trim(LLMApiKeyEdit.Text) = '' then
    begin
      MsgBox('请输入 LLM API Key！', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    
    if Trim(ZEPApiKeyEdit.Text) = '' then
    begin
      MsgBox('请输入 ZEP API Key！', mbError, MB_OK);
      Result := False;
      Exit;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  EnvContent: String;
  EnvFilePath: String;
begin
  if CurStep = ssPostInstall then
  begin
    // 创建 .env 文件
    EnvFilePath := ExpandConstant('{app}\backend\.env');
    
    EnvContent := '# MiroFish configuration file' + #13#10;
    EnvContent := EnvContent + '# Generated by installer' + #13#10;
    EnvContent := EnvContent + #13#10;
    EnvContent := EnvContent + '# LLM API configuration (OpenAI-compatible)' + #13#10;
    EnvContent := EnvContent + 'LLM_API_KEY=' + LLMApiKeyEdit.Text + #13#10;
    EnvContent := EnvContent + 'LLM_BASE_URL=' + LLMBaseURLEdit.Text + #13#10;
    EnvContent := EnvContent + 'LLM_MODEL_NAME=' + LLMModelNameEdit.Text + #13#10;
    EnvContent := EnvContent + #13#10;
    EnvContent := EnvContent + '# ZEP configuration' + #13#10;
    EnvContent := EnvContent + 'ZEP_API_KEY=' + ZEPApiKeyEdit.Text + #13#10;
    
    EnvContent := #239#187#191 + EnvContent;
    if not SaveStringToFile(EnvFilePath, EnvContent, False) then
    begin
      MsgBox('无法写入配置文件：' + #13#10 + EnvFilePath + #13#10 + #13#10 +
        '请检查安装目录权限，或以管理员身份重新安装。', mbError, MB_OK);
    end;
  end;
end;
