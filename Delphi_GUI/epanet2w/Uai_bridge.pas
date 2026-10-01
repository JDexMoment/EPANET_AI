unit Uai_bridge;

{-------------------------------------------------------------------}
{                    Unit:    Uai_bridge.pas                        }
{                    Project: EPANET2W AI Extension                 }
{                    Version: 2.2-AI                                }
{                                                                   }
{   Context Collector & Local HTTP Bridge between EPANET2W (Delphi) }
{   and the Local Python AI & Engineering Analytics Service.        }
{                                                                   }
{   Responsibilities (per Roadmap Section 4 & 5):                   }
{   1. Collects current screen context (Zoom viewport bounds,       }
{      visible nodes/links on screen, selected object, active       }
{      simulation time period, viewed node/link variables).         }
{   2. Exports current in-memory network to a temporary .INP file   }
{      and captures the current Map canvas bitmap.                  }
{   3. Sends compact JSON payload to local FastAPI service          }
{      (http://127.0.0.1:8765/api/v1/analyze) and returns the       }
{      structured interpretation/report to the UI.                  }
{-------------------------------------------------------------------}

interface

uses
  SysUtils, Classes, Windows, Forms, Graphics,
  System.JSON, System.Net.HttpClient, System.Net.URLClient,
  Uglobals, Uutils, Uexport, Uoutput;

type
  TAIMode = (
    aimWhatHappens,      // «Что происходит?»
    aimExplainObject,    // «Объяснить объект»
    aimFindProblems,     // «Найти проблемы»
    aimWhyHappened,      // «Почему это произошло?»
    aimGenerateReport,   // «Составить отчёт»
    aimCompareScenarios, // «Сравнить сценарии»
    aimAskQuestion       // «Ответить на вопрос»
  );

const
  AI_SERVICE_DEFAULT_URL = 'http://127.0.0.1:8765';

  AI_MODE_IDS: array[TAIMode] of string = (
    'what_happens',
    'explain_object',
    'find_problems',
    'why_happened',
    'generate_report',
    'compare_scenarios',
    'ask_question'
  );

  AI_MODE_CAPTIONS: array[TAIMode] of string = (
    'Что происходит на экране?',
    'Объяснить выбранный объект',
    'Найти проблемы в сети',
    'Почему это произошло?',
    'Составить инженерный отчёт',
    'Сравнить сценарии',
    'Задать вопрос AI'
  );

function GetObjectTypeName(const ObjType: Integer): string;
function ExportCurrentNetworkForAI(out InpFilePath, ScreenshotPath: string): Boolean;
function BuildUIContextJSON(const Mode: TAIMode; const UserQuestion: string;
  const CompareInpFile: string = ''): TJSONObject;
function QueryLocalAIService(const Mode: TAIMode; const UserQuestion: string;
  const CompareInpFile: string; out ResponseText: string;
  out ReportPath: string; out ErrorMsg: string): Boolean;
function CheckAIServiceHealth(out StatusMsg: string): Boolean;

implementation

uses
  Fmain, Fmap;

function GetObjectTypeName(const ObjType: Integer): string;
begin
  case ObjType of
    JUNCS:   Result := 'junction';
    RESERVS: Result := 'reservoir';
    TANKS:   Result := 'tank';
    PIPES:   Result := 'pipe';
    PUMPS:   Result := 'pump';
    VALVES:  Result := 'valve';
    LABELS:  Result := 'label';
    PATTERNS:Result := 'pattern';
    CURVES:  Result := 'curve';
    CNTRLS:  Result := 'control';
    OPTS:    Result := 'option';
  else
    Result := 'none';
  end;
end;

function ExportCurrentNetworkForAI(out InpFilePath, ScreenshotPath: string): Boolean;
begin
  Result := False;
  InpFilePath := TempDir + 'epanet_ai_snapshot.inp';
  ScreenshotPath := TempDir + 'epanet_ai_viewport.bmp';
  try
    // Export full network including map coordinates ([COORDINATES])
    Uexport.ExportDataBase(InpFilePath, True);

    // Save current map bitmap if MapForm is available
    if Assigned(MapForm) and Assigned(MapForm.Map) and Assigned(MapForm.Map.Bitmap) then
    begin
      MapForm.Map.Bitmap.SaveToFile(ScreenshotPath);
    end;
    Result := FileExists(InpFilePath);
  except
    on E: Exception do
      Result := False;
  end;
end;

function BuildUIContextJSON(const Mode: TAIMode; const UserQuestion: string;
  const CompareInpFile: string = ''): TJSONObject;
var
  RootObj, ProjObj, SelObj, ViewObj, BBoxObj, SimObj: TJSONObject;
  VisNodesArr, VisLinksArr: TJSONArray;
  InpPath, ScreenPath: string;
  MinX, MaxX, MinY, MaxY, X1, Y1, X2, Y2, TempVal: Extended;
  NType, LType, I, MaxVisibleCount: Integer;
  aNode: TNode;
  aLink: TLink;
  SelID: string;
begin
  ExportCurrentNetworkForAI(InpPath, ScreenPath);

  RootObj := TJSONObject.Create;
  RootObj.AddPair('mode', AI_MODE_IDS[Mode]);
  RootObj.AddPair('question', UserQuestion);
  RootObj.AddPair('inp_file', InpPath);
  RootObj.AddPair('screenshot_file', ScreenPath);
  if CompareInpFile <> '' then
    RootObj.AddPair('compare_inp_file', CompareInpFile);

  // 1. Project info
  ProjObj := TJSONObject.Create;
  ProjObj.AddPair('file_name', InputFileName);
  ProjObj.AddPair('title', Network.Options.Title);
  ProjObj.AddPair('flow_units', FlowUnits);
  if UnitSystem = usSI then
    ProjObj.AddPair('unit_system', 'SI')
  else
    ProjObj.AddPair('unit_system', 'US');
  RootObj.AddPair('project', ProjObj);

  // 2. Simulation / active view state
  SimObj := TJSONObject.Create;
  SimObj.AddPair('run_flag', TJSONBool.Create(RunFlag));
  SimObj.AddPair('current_period', TJSONNumber.Create(CurrentPeriod));
  SimObj.AddPair('total_periods', TJSONNumber.Create(Nperiods));
  SimObj.AddPair('duration_sec', TJSONNumber.Create(Dur));
  SimObj.AddPair('report_step_sec', TJSONNumber.Create(Rstep));
  SimObj.AddPair('current_node_var', TJSONNumber.Create(CurrentNodeVar));
  SimObj.AddPair('current_link_var', TJSONNumber.Create(CurrentLinkVar));
  RootObj.AddPair('simulation_state', SimObj);

  // 3. Currently selected object in Browser / Property Editor / Map
  SelObj := TJSONObject.Create;
  if (CurrentList in [JUNCS..VALVES]) and (CurrentItem[CurrentList] >= 0) and
     (CurrentItem[CurrentList] < Network.Lists[CurrentList].Count) then
  begin
    SelID := GetID(CurrentList, CurrentItem[CurrentList]);
    SelObj.AddPair('type', GetObjectTypeName(CurrentList));
    SelObj.AddPair('id', SelID);
    SelObj.AddPair('index', TJSONNumber.Create(CurrentItem[CurrentList]));
  end
  else
  begin
    SelObj.AddPair('type', 'none');
    SelObj.AddPair('id', '');
  end;
  RootObj.AddPair('selection', SelObj);

  // 4. Current Map Viewport & Visible Objects (what user is looking at on screen)
  ViewObj := TJSONObject.Create;
  VisNodesArr := TJSONArray.Create;
  VisLinksArr := TJSONArray.Create;

  if Assigned(MapForm) and Assigned(MapForm.Map) then
  begin
    with MapForm.Map do
    begin
      MinX := GetX(Window.MapRect.Left);
      MaxX := GetX(Window.MapRect.Right);
      if MinX > MaxX then begin TempVal := MinX; MinX := MaxX; MaxX := TempVal; end;

      MinY := GetY(Window.MapRect.Bottom);
      MaxY := GetY(Window.MapRect.Top);
      if MinY > MaxY then begin TempVal := MinY; MinY := MaxY; MaxY := TempVal; end;

      BBoxObj := TJSONObject.Create;
      BBoxObj.AddPair('min_x', TJSONNumber.Create(MinX));
      BBoxObj.AddPair('min_y', TJSONNumber.Create(MinY));
      BBoxObj.AddPair('max_x', TJSONNumber.Create(MaxX));
      BBoxObj.AddPair('max_y', TJSONNumber.Create(MaxY));
      ViewObj.AddPair('bbox', BBoxObj);
      ViewObj.AddPair('zoom_index', TJSONNumber.Create(Window.ZoomIndex));
      ViewObj.AddPair('zoom_ratio', TJSONNumber.Create(MapZoomRatio));

      // Collect visible nodes inside current zoom window (capped at 200 for compact prompt)
      MaxVisibleCount := 0;
      for NType := JUNCS to TANKS do
      begin
        for I := 0 to Network.Lists[NType].Count - 1 do
        begin
          aNode := Node(NType, I);
          if (aNode <> nil) and (aNode.X <> MISSING) and (aNode.Y <> MISSING) then
          begin
            if (aNode.X >= MinX) and (aNode.X <= MaxX) and
               (aNode.Y >= MinY) and (aNode.Y <= MaxY) then
            begin
              VisNodesArr.Add(GetID(NType, I));
              Inc(MaxVisibleCount);
              if MaxVisibleCount >= 200 then Break;
            end;
          end;
        end;
        if MaxVisibleCount >= 200 then Break;
      end;

      // Collect visible links inside current zoom window (capped at 200)
      MaxVisibleCount := 0;
      for LType := PIPES to VALVES do
      begin
        for I := 0 to Network.Lists[LType].Count - 1 do
        begin
          aLink := Link(LType, I);
          if (aLink <> nil) and (aLink.Node1 <> nil) and (aLink.Node2 <> nil) then
          begin
            X1 := aLink.Node1.X; Y1 := aLink.Node1.Y;
            X2 := aLink.Node2.X; Y2 := aLink.Node2.Y;
            if ((X1 >= MinX) and (X1 <= MaxX) and (Y1 >= MinY) and (Y1 <= MaxY)) or
               ((X2 >= MinX) and (X2 <= MaxX) and (Y2 >= MinY) and (Y2 <= MaxY)) then
            begin
              VisLinksArr.Add(GetID(LType, I));
              Inc(MaxVisibleCount);
              if MaxVisibleCount >= 200 then Break;
            end;
          end;
        end;
        if MaxVisibleCount >= 200 then Break;
      end;
    end;
  end;

  ViewObj.AddPair('visible_nodes', VisNodesArr);
  ViewObj.AddPair('visible_links', VisLinksArr);
  RootObj.AddPair('viewport', ViewObj);

  Result := RootObj;
end;

function QueryLocalAIService(const Mode: TAIMode; const UserQuestion: string;
  const CompareInpFile: string; out ResponseText: string;
  out ReportPath: string; out ErrorMsg: string): Boolean;
var
  HttpClient: THTTPClient;
  HttpResp: IHTTPResponse;
  PayloadJSON, RespJSON: TJSONObject;
  ReqStream: TStringStream;
  Url: string;
begin
  Result := False;
  ResponseText := '';
  ReportPath := '';
  ErrorMsg := '';

  PayloadJSON := BuildUIContextJSON(Mode, UserQuestion, CompareInpFile);
  HttpClient := THTTPClient.Create;
  try
    HttpClient.ConnectionTimeout := 5000;
    HttpClient.ResponseTimeout := 120000; // Local LLM generation timeout (120s)
    HttpClient.CustomHeaders['Content-Type'] := 'application/json; charset=utf-8';

    ReqStream := TStringStream.Create(PayloadJSON.ToJSON, TEncoding.UTF8);
    try
      Url := AI_SERVICE_DEFAULT_URL + '/api/v1/analyze';
      HttpResp := HttpClient.Post(Url, ReqStream);
      if HttpResp.StatusCode = 200 then
      begin
        RespJSON := TJSONObject.ParseJSONValue(HttpResp.ContentAsString(TEncoding.UTF8)) as TJSONObject;
        if Assigned(RespJSON) then
        try
          ResponseText := RespJSON.GetValue<string>('answer', '');
          ReportPath := RespJSON.GetValue<string>('report_path', '');
          Result := True;
        finally
          RespJSON.Free;
        end;
      end
      else
      begin
        ErrorMsg := Format('HTTP %d: %s', [HttpResp.StatusCode, HttpResp.ContentAsString(TEncoding.UTF8)]);
      end;
    finally
      ReqStream.Free;
    end;
  except
    on E: Exception do
    begin
      ErrorMsg := 'Не удалось подключиться к локальному AI-сервису (' +
        AI_SERVICE_DEFAULT_URL + '). Убедитесь, что запущен сервер ai_module: ' +
        'python -m ai_module.api.app' + sLineBreak + 'Детали: ' + E.Message;
    end;
  end;
  HttpClient.Free;
  PayloadJSON.Free;
end;

function CheckAIServiceHealth(out StatusMsg: string): Boolean;
var
  HttpClient: THTTPClient;
  HttpResp: IHTTPResponse;
begin
  Result := False;
  HttpClient := THTTPClient.Create;
  try
    HttpClient.ConnectionTimeout := 2000;
    HttpClient.ResponseTimeout := 3000;
    try
      HttpResp := HttpClient.Get(AI_SERVICE_DEFAULT_URL + '/api/v1/health');
      Result := (HttpResp.StatusCode = 200);
      StatusMsg := HttpResp.ContentAsString(TEncoding.UTF8);
    except
      on E: Exception do
        StatusMsg := E.Message;
    end;
  finally
    HttpClient.Free;
  end;
end;

end.
