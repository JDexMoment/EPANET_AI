"""HTTP-сервис сбора данных от инженеров-гидравликов.

Запуск локально:
    uvicorn service.app:app --host 0.0.0.0 --port 8080
На сервере — см. deploy/ (Docker + автозапуск + TLS).

Что делает сервис:
  * принимает модель EPANET в любом формате (.inp, .NET, .epanet, zip);
  * конвертирует и чистит её (EPANET-Model-Cleaner), считает расчёт суток;
  * показывает инженеру KPI, алерты, объекты и факты E-xxx;
  * принимает разметку: проблема в элементе, эталонный отчёт, вопрос-ответ;
  * сам проверяет качество ответа (числа и ссылки) прямо в форме;
  * автономно выгружает данные в архив (по расписанию) и отдаёт админу.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
import zipfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config, conversion, export, modeling, quality, storage

STATIC = Path(__file__).resolve().parent / "static"
VERSION = "1.0"

app = FastAPI(title="EPANET-AI · сбор данных от инженеров", version=VERSION,
              docs_url="/api/docs", openapi_url="/api/openapi.json")

_starts: deque[float] = deque(maxlen=5000)
_buckets: dict[str, list[float]] = {}


# ─────────────────────────────  служебное
@app.on_event("startup")
async def _startup() -> None:
    storage.init()
    storage.log_event("service_start", actor="system", version=VERSION)
    if config.AUTO_EXPORT_HOURS > 0:
        asyncio.create_task(_auto_export_loop())

    # подсказка в консоль: как войти
    if config.EXPERT_TOKENS:
        for token, rec in config.EXPERT_TOKENS.items():
            print(f"[service] эксперт {rec['expert_id']} ({rec['role']}): токен {token}")
    else:
        print("[service] EXPERT_TOKENS не задан — экспертов можно создать в админке "
              f"(ADMIN_TOKEN={config.ADMIN_TOKEN})")


async def _auto_export_loop() -> None:
    """Автономная работа: раз в N часов собираем архив, пишем в exports/ и (опц.) копируем."""
    interval = max(600.0, config.AUTO_EXPORT_HOURS * 3600)
    while True:
        await asyncio.sleep(interval)
        try:
            res = await asyncio.to_thread(export.build_export, False, "auto")
            print(f"[service] автоэкспорт: {res['file']} ({res['cases']} кейсов, {res['bytes']} байт)")
        except Exception as e:  # noqa: BLE001
            storage.log_event("auto_export_failed", actor="system", error=str(e))
            print(f"[service] ошибка автоэкспорта: {e}")


def expert(authorization: str | None = Header(default=None),
           x_expert_token: str | None = Header(default=None),
           token: str | None = Query(default=None)) -> dict:
    raw = x_expert_token or token or (authorization or "").removeprefix("Bearer ").strip()
    rec = storage.expert_by_token(raw) if raw else None
    if not rec:
        raise HTTPException(401, "нужен действующий токен эксперта")
    return rec


def admin(x_admin_token: str | None = Header(default=None), token: str | None = Query(default=None)) -> str:
    if (x_admin_token or token) != config.ADMIN_TOKEN:
        raise HTTPException(403, "нужен токен администратора")
    return "admin"


def rate_limit(actor: str, limit_per_hour: int, kind: str) -> None:
    now = time.time()
    key = f"{kind}:{actor}"
    arr = [t for t in _buckets.get(key, []) if now - t < 3600]
    if len(arr) >= limit_per_hour:
        raise HTTPException(429, f"слишком много операций «{kind}» за час — попробуйте позже")
    arr.append(now)
    _buckets[key] = arr


# ─────────────────────────────  интерфейс
@app.get("/", include_in_schema=False)
async def root(request: Request) -> RedirectResponse:
    """Редирект на интерфейс с сохранением параметров (?token=… для персональной ссылки)."""
    q = request.url.query
    return RedirectResponse("/static/index.html" + (f"?{q}" if q else ""))


app.mount("/static", StaticFiles(directory=str(STATIC), html=True), name="static")


@app.get("/health")
async def health() -> dict:
    st = storage.stats()
    return {"status": "ok", "version": VERSION,
            "emc": conversion.EMC_AVAILABLE,
            "simulation": config.RUN_SIMULATION,
            "auto_export_hours": config.AUTO_EXPORT_HOURS,
            "stats": st}


@app.get("/api/meta")
async def meta() -> dict:
    """Справочники для формы: единый источник — configs/labels.yaml."""
    lab = {}
    try:
        from src import common
        lab = common.load_yaml("configs/labels.yaml")
    except Exception:  # noqa: BLE001
        pass
    return {
        "categories": [{"id": c["id"], "ru": c.get("ru", c["id"])} for c in lab.get("categories", [])],
        "severity": [{"id": s["id"], "ru": s.get("ru", s["id"])} for s in lab.get("severity", [])],
        "confidence": [{"id": c["id"], "ru": c.get("ru", c["id"])} for c in lab.get("confidence", [])],
        "check_actions": [{"id": a["id"], "ru": a.get("ru", a["id"])} for a in lab.get("verification_actions", [])],
        "kinds": [
            {"id": "element_problem", "ru": "Проблема в элементе", "mode": "explain_object"},
            {"id": "report", "ru": "Эталонный отчёт", "mode": "make_report"},
            {"id": "qa", "ru": "Вопрос — эталонный ответ", "mode": "ask"},
        ],
        "modes": ["whats_happening", "explain_object", "find_problems", "why_happened",
                  "make_report", "compare_scenarios", "ask"],
        "max_upload_mb": config.MAX_UPLOAD_MB,
        "allowed_ext": sorted(config.ALLOWED_EXT),
        "emc": conversion.EMC_AVAILABLE,
    }


# ─────────────────────────────  вход эксперта
@app.post("/api/session")
async def session(payload: dict) -> dict:
    token = (payload or {}).get("token", "").strip()
    rec = storage.expert_by_token(token)
    if not rec:
        raise HTTPException(401, "токен не найден")
    n = len(storage.list_annotations(expert_id=rec["expert_id"], limit=10000))
    storage.log_event("login", actor=rec["expert_id"])
    return {"expert_id": rec["expert_id"], "role": rec["role"], "annotations": n}


# ─────────────────────────────  модели
@app.post("/api/models")
async def upload_model(file: UploadFile = File(...), note: str = Form(default=""),
                       who: dict = Depends(expert)) -> dict:
    rate_limit(who["expert_id"], config.MAX_UPLOADS_PER_DAY, "upload")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in config.ALLOWED_EXT:
        raise HTTPException(400, f"формат {ext or '?'} не поддерживается. "
                                 f"Допустимо: {', '.join(sorted(config.ALLOWED_EXT))}")

    model_id = secrets.token_hex(6)
    updir = config.UPLOADS / model_id
    updir.mkdir(parents=True, exist_ok=True)
    orig = updir / f"original{ext}"

    size = 0
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    with orig.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                fh.close()
                orig.unlink(missing_ok=True)
                raise HTTPException(413, f"файл больше {config.MAX_UPLOAD_MB} МБ")
            fh.write(chunk)

    sha = hashlib.sha256(orig.read_bytes()).hexdigest()
    dup = storage.find_model_by_sha(sha)
    if dup and dup.get("status") == "ok":
        storage.log_event("upload_duplicate", actor=who["expert_id"], model_id=dup["id"])
        return {"model_id": dup["id"], "duplicate": True,
                "summary": json.loads(dup["kpi_json"]) if dup.get("kpi_json") else None,
                "detail": _model_detail(dup["id"])}

    storage.create_model({"id": model_id, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "uploaded_by": who["expert_id"], "filename": file.filename,
                          "orig_format": ext.lstrip("."), "sha256": sha, "size_bytes": size,
                          "status": "processing"})

    clean_inp = config.MODELS / model_id / "network_clean.inp"
    try:
        conv = conversion.convert_to_clean_inp(orig, clean_inp)
    except conversion.ConversionError as e:
        storage.update_model(model_id, status="failed", error=str(e))
        storage.log_event("convert_failed", actor=who["expert_id"], model_id=model_id, error=str(e))
        raise HTTPException(422, f"не удалось прочитать модель: {e}") from e

    summary = await asyncio.to_thread(modeling.prepare, model_id, clean_inp)
    if summary.get("error"):
        storage.update_model(model_id, status="no_analysis", error=summary["error"],
                             conversion_json=json.dumps(conv, ensure_ascii=False),
                             clean_inp=str(clean_inp), meta_json=json.dumps({"note": note}))
        return {"model_id": model_id, "conversion": conv, "analysis_error": summary["error"],
                "network": summary.get("network")}

    storage.update_model(
        model_id, status="ok", clean_inp=str(clean_inp),
        n_nodes=summary["network"]["nodes"], n_links=summary["network"]["links"],
        kpi_json=json.dumps(summary["kpi"], ensure_ascii=False),
        alerts_json=json.dumps(summary["alerts"], ensure_ascii=False),
        objects_json=json.dumps(summary["objects"], ensure_ascii=False),
        warnings_json=json.dumps(summary["warnings"], ensure_ascii=False),
        conversion_json=json.dumps(conv, ensure_ascii=False),
        meta_json=json.dumps({"note": note, "contexts": summary.get("contexts"),
                              "observability": summary.get("observability")}, ensure_ascii=False))
    storage.log_event("upload_ok", actor=who["expert_id"], model_id=model_id,
                      nodes=summary["network"]["nodes"], links=summary["network"]["links"])
    return {"model_id": model_id, "conversion": conv, "detail": _model_detail(model_id)}


def _model_detail(model_id: str) -> dict:
    m = storage.get_model(model_id)
    if not m:
        raise HTTPException(404, "модель не найдена")
    j = lambda key: json.loads(m[key]) if m.get(key) else None  # noqa: E731
    return {
        "model_id": m["id"], "filename": m["filename"], "status": m["status"],
        "created_at": m["created_at"], "uploaded_by": m["uploaded_by"],
        "network": {"nodes": m["n_nodes"], "links": m["n_links"]},
        "kpi": j("kpi_json"), "alerts": j("alerts_json"), "objects": j("objects_json"),
        "warnings": j("warnings_json"), "conversion": j("conversion_json"), "meta": j("meta_json"),
        "error": m.get("error"),
        "annotations": len(storage.list_annotations(model_id=model_id, limit=10000)),
    }


@app.get("/api/models")
async def models(who: dict = Depends(expert), limit: int = 100) -> dict:
    rows = storage.list_models(limit=limit)
    return {"models": [{k: r[k] for k in ("id", "created_at", "uploaded_by", "filename", "status",
                                          "n_nodes", "n_links", "n_annotations")} for r in rows]}


@app.get("/api/models/{model_id}")
async def model_detail(model_id: str, who: dict = Depends(expert)) -> dict:
    return _model_detail(model_id)


@app.get("/api/models/{model_id}/context")
async def model_context(model_id: str, mode: str = "whats_happening",
                        who: dict = Depends(expert)) -> dict:
    ctx = modeling.read_context(model_id, mode)
    if not ctx:
        raise HTTPException(404, "контекст не найден (модель не считалась?)")
    return ctx


@app.get("/api/models/{model_id}/evidence")
async def model_evidence(model_id: str, who: dict = Depends(expert)) -> dict:
    p = modeling.model_dir(model_id) / "derived" / "evidence.json"
    if not p.exists():
        raise HTTPException(404, "факты не найдены")
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/api/models/{model_id}/file")
async def model_file(model_id: str, kind: str = "clean", who: dict = Depends(expert)) -> FileResponse:
    m = storage.get_model(model_id)
    if not m:
        raise HTTPException(404, "модель не найдена")
    if kind == "clean" and m.get("clean_inp"):
        return FileResponse(m["clean_inp"], filename=f"{model_id}_clean.inp")
    if kind == "original":
        for f in (config.UPLOADS / model_id).glob("original*"):
            return FileResponse(f, filename=f"{model_id}{f.suffix}")
    raise HTTPException(404, "файл не найден")


# ─────────────────────────────  разметка
@app.post("/api/annotations")
async def create_annotation(payload: dict, who: dict = Depends(expert)) -> dict:
    rate_limit(who["expert_id"], config.MAX_ANNOTATIONS_PER_HOUR, "annotation")
    model_id = (payload or {}).get("model_id")
    model = storage.get_model(model_id or "")
    if not model:
        raise HTTPException(404, "модель не найдена")

    kind = payload.get("kind") or "element_problem"
    if kind not in ("element_problem", "report", "qa"):
        raise HTTPException(400, "kind должен быть element_problem | report | qa")
    mode = payload.get("mode") or {"element_problem": "explain_object", "report": "make_report",
                                   "qa": "ask"}[kind]

    evidence_path = modeling.model_dir(model_id) / "derived" / "evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.exists() else {}
    ctx_text = modeling.context_text_for(model_id, mode)
    answer = payload.get("answer") or payload.get("report_markdown") or ""
    check = quality.check_answer(answer, evidence, ctx_text)

    ann_id = secrets.token_hex(8)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rec = {
        "id": ann_id, "created_at": now, "updated_at": now, "model_id": model_id,
        "expert_id": who["expert_id"], "kind": kind, "mode": mode,
        "object_id": ",".join(payload.get("objects") or ([payload["object_id"]]
                                                         if payload.get("object_id") else [])),
        "question": payload.get("question"), "answer": payload.get("answer") or "",
        "observations": payload.get("observations"), "causes": payload.get("causes"),
        "checks": payload.get("checks"), "recommendations": payload.get("recommendations"),
        "limitations": payload.get("limitations"), "report_markdown": payload.get("report_markdown"),
        "category": payload.get("category"), "severity": payload.get("severity"),
        "confidence": payload.get("confidence"),
        "evidence_refs": ",".join(payload.get("evidence_refs") or []),
        "time_spent_min": payload.get("time_spent_min"),
        "number_check_json": json.dumps(check, ensure_ascii=False),
    }
    storage.save_annotation(rec)
    storage.log_event("annotation", actor=who["expert_id"], model_id=model_id,
                      kind=kind, mode=mode, ok=check["ok"])
    total = len(storage.list_annotations(expert_id=who["expert_id"], limit=10000))
    return {"annotation_id": ann_id, "check": check, "your_total": total}


@app.get("/api/annotations")
async def annotations(model_id: str | None = None, mine: int = 1,
                      who: dict = Depends(expert)) -> dict:
    rows = storage.list_annotations(model_id=model_id,
                                    expert_id=who["expert_id"] if mine else None, limit=200)
    for r in rows:
        r["number_check"] = json.loads(r["number_check_json"]) if r.get("number_check_json") else None
        r.pop("number_check_json", None)
    return {"annotations": rows}


@app.get("/api/my")
async def my(who: dict = Depends(expert)) -> dict:
    rows = storage.list_annotations(expert_id=who["expert_id"], limit=10000)
    by_kind: dict[str, int] = {}
    by_model: dict[str, int] = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        by_model[r["model_id"]] = by_model.get(r["model_id"], 0) + 1
    return {"expert_id": who["expert_id"], "total": len(rows), "by_kind": by_kind, "by_model": by_model}


# ─────────────────────────────  админ
@app.get("/admin", include_in_schema=False)
async def admin_page() -> HTMLResponse:
    return HTMLResponse((STATIC / "admin.html").read_text(encoding="utf-8"))


def _expert_link(token: str) -> str:
    """Персональная ссылка для гидравлика: открыл — и он уже внутри."""
    base = config.PUBLIC_URL
    return f"{base}/?token={token}" if base else f"/?token={token}"


@app.get("/api/admin/overview")
async def admin_overview(_: str = Depends(admin)) -> dict:
    experts = [{**e, "link": _expert_link(e["token"])} for e in storage.list_experts()]
    return {"stats": storage.stats(), "experts": experts,
            "models": storage.list_models(limit=100), "exports": export.list_exports(),
            "events": storage.list_events(limit=50)}


@app.post("/api/admin/experts")
async def admin_add_expert(payload: dict, _: str = Depends(admin)) -> dict:
    name = (payload or {}).get("expert_id", "").strip()
    if not name:
        raise HTTPException(400, "нужно имя эксперта")
    token = (payload or {}).get("token") or secrets.token_urlsafe(16)
    rec = storage.add_expert(token, name, (payload or {}).get("role", "expert"))
    storage.log_event("expert_added", actor="admin", expert_id=name)
    return {**rec, "link": _expert_link(rec["token"]),
            "invite": (f"Здравствуйте, {name}!\n\n"
                       f"Откройте, пожалуйста, ссылку и работайте в ней — ничего устанавливать не нужно:\n"
                       f"{_expert_link(rec['token'])}\n\n"
                       f"Что делать: загрузить модель (.inp / .NET / .epanet) → посмотреть расчёт → "
                       f"разметить проблему, написать эталонный отчёт или задать вопрос с эталонным ответом.\n"
                       f"Инструкция на странице. Вход сохраняется в браузере, повторно токен вводить не нужно.")}


@app.post("/api/admin/export")
async def admin_export(only_unexported: bool = True, _: str = Depends(admin)) -> dict:
    res = await asyncio.to_thread(export.build_export, only_unexported, None)
    return {k: res[k] for k in ("file", "cases", "bytes", "manifest")}


@app.get("/api/admin/export")
async def admin_export_download(name: str | None = None, _: str = Depends(admin)) -> FileResponse:
    path = config.EXPORTS / (name or "latest.zip")
    if not path.exists():
        raise HTTPException(404, "экспорт не найден — сначала POST /api/admin/export")
    return FileResponse(path, filename=path.name, media_type="application/zip")


@app.get("/api/admin/annotations.jsonl")
async def admin_annotations(_: str = Depends(admin)) -> JSONResponse:
    rows = storage.list_annotations(limit=100000)
    return JSONResponse(content=rows)


@app.get("/api/admin/backup.zip")
async def admin_backup(_: str = Depends(admin)) -> FileResponse:
    """Полный снимок: база + все загруженные и очищенные модели."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = config.EXPORTS / f"backup_{ts}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        if config.DB_PATH.exists():
            z.write(config.DB_PATH, "service.sqlite3")
        for base in (config.UPLOADS, config.MODELS):
            for f in base.rglob("*"):
                if f.is_file() and "__pycache__" not in str(f):
                    try:
                        arc = str(f.resolve().relative_to(config.DATA.resolve()))
                    except ValueError:
                        arc = f"external/{f.name}"
                    z.write(f, arc)
    storage.log_event("backup_full", actor="admin", file=path.name, bytes=path.stat().st_size)
    return FileResponse(path, filename=path.name, media_type="application/zip")


if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    uvicorn.run("service.app:app", host=config.HOST, port=config.PORT, log_level="info")
