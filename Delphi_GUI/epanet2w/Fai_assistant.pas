unit Fai_assistant;

{-------------------------------------------------------------------}
{                    Unit:    Fai_assistant.pas                     }
{                    Project: EPANET2W AI Extension                 }
{                    Version: 2.2-AI                                }
{                                                                   }
{   Stay-on-top AI Assistant window and context menu handler        }
{   implementing the 7 engineering modes from the Roadmap:          }
{   1. Что происходит? (aimWhatHappens)                             }
{   2. Объяснить объект (aimExplainObject)                          }
{   3. Найти проблемы (aimFindProblems)                             }
{   4. Почему это произошло? (aimWhyHappened)                       }
{   5. Составить отчёт (aimGenerateReport)                          }
{   6. Сравнить сценарии (aimCompareScenarios)                      }
{   7. Ответить на вопрос (aimAskQuestion)                          }
{-------------------------------------------------------------------}

interface

uses
  Windows, Messages, SysUtils, Classes, Graphics, Controls, Forms, Dialogs,
  StdCtrls, ExtCtrls, Buttons, ComCtrls, Menus, ShellAPI,
  Uglobals, Uai_bridge;

type
  TAIAssistantForm = class(TForm)
    procedure FormCreate(Sender: TObject);
    procedure FormShow(Sender: TObject);
  private
    TopPanel: TPanel;
    ModePanel: TPanel;
    BottomPanel: TPanel;
    StatusHeaderLabel: TLabel;
    MemoResponse: TMemo;
    EditQuestion: TEdit;
    BtnSendQuestion: TButton;
    BtnOpenReport: TButton;
    CompareOpenDialog: TOpenDialog;
    LastReportPath: string;
    procedure BuildDynamicControls;
    procedure OnModeButtonClick(Sender: TObject);
    procedure OnSendQuestionClick(Sender: TObject);
    procedure OnOpenReportClick(Sender: TObject);
    procedure UpdateContextSummary;
  public
    procedure ExecuteAIMode(const Mode: TAIMode; const CustomQuestion: string = '');
  end;

var
  AIAssistantForm: TAIAssistantForm;

procedure ShowAIAssistant(const InitialMode: TAIMode; const CustomQuestion: string = '');

implementation

{$R *.DFM}

procedure ShowAIAssistant(const InitialMode: TAIMode; const CustomQuestion: string = '');
begin
  if not Assigned(AIAssistantForm) then
    Application.CreateForm(TAIAssistantForm, AIAssistantForm);
  AIAssistantForm.Show;
  AIAssistantForm.BringToFront;
  AIAssistantForm.ExecuteAIMode(InitialMode, CustomQuestion);
end;

procedure TAIAssistantForm.FormCreate(Sender: TObject);
begin
  LastReportPath := '';
  BuildDynamicControls;
end;

procedure TAIAssistantForm.FormShow(Sender: TObject);
begin
  UpdateContextSummary;
end;

procedure TAIAssistantForm.BuildDynamicControls;
var
  M: TAIMode;
  Btn: TButton;
  Col, Row: Integer;
begin
  // Top status bar showing selected object & current viewport status
  TopPanel := TPanel.Create(Self);
  TopPanel.Parent := Self;
  TopPanel.Align := alTop;
  TopPanel.Height := 36;
  TopPanel.BevelOuter := bvNone;
  TopPanel.Color := clWindow;

  StatusHeaderLabel := TLabel.Create(Self);
  StatusHeaderLabel.Parent := TopPanel;
  StatusHeaderLabel.Left := 12;
  StatusHeaderLabel.Top := 10;
  StatusHeaderLabel.Font.Style := [fsBold];
  StatusHeaderLabel.Caption := 'Контекст экрана EPANET: готов к анализу';

  // Panel with the 6 quick-action buttons + scenario comparison
  ModePanel := TPanel.Create(Self);
  ModePanel.Parent := Self;
  ModePanel.Align := alTop;
  ModePanel.Height := 76;
  ModePanel.BevelOuter := bvLowered;

  Col := 0;
  Row := 0;
  for M := Low(TAIMode) to High(TAIMode) do
  begin
    if M = aimAskQuestion then Continue; // Handled by bottom input bar
    Btn := TButton.Create(Self);
    Btn.Parent := ModePanel;
    Btn.Width := 238;
    Btn.Height := 30;
    Btn.Left := 10 + Col * 246;
    Btn.Top := 6 + Row * 34;
    Btn.Caption := AI_MODE_CAPTIONS[M];
    Btn.Tag := Ord(M);
    Btn.OnClick := OnModeButtonClick;
    Inc(Col);
    if Col >= 3 then
    begin
      Col := 0;
      Inc(Row);
    end;
  end;

  // Bottom question bar
  BottomPanel := TPanel.Create(Self);
  BottomPanel.Parent := Self;
  BottomPanel.Align := alBottom;
  BottomPanel.Height := 46;
  BottomPanel.BevelOuter := bvNone;

  EditQuestion := TEdit.Create(Self);
  EditQuestion.Parent := BottomPanel;
  EditQuestion.Left := 10;
  EditQuestion.Top := 10;
  EditQuestion.Width := 460;
  EditQuestion.TextHint := 'Введите вопрос на естественном языке по текущей модели...';

  BtnSendQuestion := TButton.Create(Self);
  BtnSendQuestion.Parent := BottomPanel;
  BtnSendQuestion.Left := 478;
  BtnSendQuestion.Top := 8;
  BtnSendQuestion.Width := 130;
  BtnSendQuestion.Height := 28;
  BtnSendQuestion.Caption := 'Спросить AI';
  BtnSendQuestion.Default := True;
  BtnSendQuestion.OnClick := OnSendQuestionClick;

  BtnOpenReport := TButton.Create(Self);
  BtnOpenReport.Parent := BottomPanel;
  BtnOpenReport.Left := 616;
  BtnOpenReport.Top := 8;
  BtnOpenReport.Width := 130;
  BtnOpenReport.Height := 28;
  BtnOpenReport.Caption := 'Открыть отчёт';
  BtnOpenReport.Enabled := False;
  BtnOpenReport.OnClick := OnOpenReportClick;

  // Main output memo
  MemoResponse := TMemo.Create(Self);
  MemoResponse.Parent := Self;
  MemoResponse.Align := alClient;
  MemoResponse.ScrollBars := ssVertical;
  MemoResponse.ReadOnly := True;
  MemoResponse.WordWrap := True;
  MemoResponse.Font.Name := 'Consolas';
  MemoResponse.Font.Size := 10;

  CompareOpenDialog := TOpenDialog.Create(Self);
  CompareOpenDialog.Title := 'Выберите второй файл сети (.INP) для сравнения сценариев';
  CompareOpenDialog.Filter := 'EPANET Input Files (*.inp)|*.inp|All Files (*.*)|*.*';
end;

procedure TAIAssistantForm.UpdateContextSummary;
var
  SelID, SelType: string;
begin
  if (CurrentList in [JUNCS..VALVES]) and (CurrentItem[CurrentList] >= 0) and
     (CurrentItem[CurrentList] < Network.Lists[CurrentList].Count) then
  begin
    SelType := GetObjectTypeName(CurrentList);
    SelID := GetID(CurrentList, CurrentItem[CurrentList]);
    StatusHeaderLabel.Caption := Format(
      'Выбранный объект: %s [%s] | Расчёт выполнен: %s | Шаг времени: %d',
      [SelID, SelType, BoolToStr(RunFlag, True), CurrentPeriod]
    );
  end
  else
  begin
    StatusHeaderLabel.Caption := Format(
      'Объект не выбран (анализ видимого участка карты) | Расчёт выполнен: %s',
      [BoolToStr(RunFlag, True)]
    );
  end;
end;

procedure TAIAssistantForm.OnModeButtonClick(Sender: TObject);
var
  Mode: TAIMode;
begin
  if Sender is TButton then
  begin
    Mode := TAIMode(TButton(Sender).Tag);
    ExecuteAIMode(Mode, '');
  end;
end;

procedure TAIAssistantForm.OnSendQuestionClick(Sender: TObject);
begin
  if Trim(EditQuestion.Text) = '' then Exit;
  ExecuteAIMode(aimAskQuestion, Trim(EditQuestion.Text));
end;

procedure TAIAssistantForm.OnOpenReportClick(Sender: TObject);
begin
  if (LastReportPath <> '') and FileExists(LastReportPath) then
    ShellExecute(Handle, 'open', PChar(LastReportPath), nil, nil, SW_SHOWNORMAL);
end;

procedure TAIAssistantForm.ExecuteAIMode(const Mode: TAIMode; const CustomQuestion: string = '');
var
  CompareFile, RespText, ReportFile, ErrMsg: string;
begin
  UpdateContextSummary;
  CompareFile := '';

  if Mode = aimCompareScenarios then
  begin
    if not CompareOpenDialog.Execute then Exit;
    CompareFile := CompareOpenDialog.FileName;
  end;

  MemoResponse.Lines.Clear;
  MemoResponse.Lines.Add('⏳ Сбор контекста текущего экрана EPANET и выполнение инженерной аналитики...');
  MemoResponse.Lines.Add('Режим: ' + AI_MODE_CAPTIONS[Mode]);
  if CustomQuestion <> '' then
    MemoResponse.Lines.Add('Вопрос: ' + CustomQuestion);
  Application.ProcessMessages;

  Screen.Cursor := crHourGlass;
  try
    if QueryLocalAIService(Mode, CustomQuestion, CompareFile, RespText, ReportFile, ErrMsg) then
    begin
      MemoResponse.Lines.Text := RespText;
      if ReportFile <> '' then
      begin
        LastReportPath := ReportFile;
        BtnOpenReport.Enabled := True;
      end;
    end
    else
    begin
      MemoResponse.Lines.Clear;
      MemoResponse.Lines.Add('ОШИБКА ОБРАЩЕНИЯ К ЛОКАЛЬНОМУ AI-МОДУЛЮ:');
      MemoResponse.Lines.Add('------------------------------------------------------------');
      MemoResponse.Lines.Add(ErrMsg);
    end;
  finally
    Screen.Cursor := crDefault;
  end;
end;

end.
