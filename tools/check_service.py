"""Проверка работоспособности сервиса сбора разметки.

Работает на любой ОС (Windows, Linux, macOS) и использует только стандартную библиотеку —
ничего доустанавливать не нужно.

Примеры:
    # локальный сервис, порт по умолчанию
    python tools/check_service.py

    # вместе с проверкой входа гидравлика и админки
    python tools/check_service.py --token gidr01-... --admin admin-...

    # сервис на сервере
    python tools/check_service.py --url https://epanet.example.com --admin <ADMIN_TOKEN>

Код возврата: 0 — всё в порядке, 1 — есть замечания (смотрите строки «✗»).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

OK, BAD, WARN = "✓", "✗", "!"


def _req(url: str, method: str = "GET", headers: dict | None = None,
         payload: dict | None = None, timeout: float = 20.0) -> tuple[int | None, object, str]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw), r.geturl()
            except json.JSONDecodeError:
                return r.status, raw, r.geturl()
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw), url
        except json.JSONDecodeError:
            return e.code, raw, url
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}", url


def main() -> int:
    ap = argparse.ArgumentParser(description="Проверка сервиса сбора разметки")
    ap.add_argument("--url", default="http://localhost:8080", help="адрес сервиса")
    ap.add_argument("--token", default=None, help="токен гидравлика (проверка входа)")
    ap.add_argument("--admin", default=None, help="ADMIN_TOKEN (проверка админки)")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    problems: list[str] = []
    notes: list[str] = []

    def line(sign: str, text: str) -> None:
        print(f"  {sign} {text}")

    print("=" * 78)
    print(f"ПРОВЕРКА СЕРВИСА · {base}")
    print("=" * 78)

    # 1. доступность и /health
    print("\n1. Сервис отвечает")
    status, body, _ = _req(f"{base}/health")
    if status is None:
        line(BAD, f"нет ответа: {body}")
        print("\n  Сервис не запущен или адрес/порт указаны неверно.")
        print("  Запуск:  python tools/run_service.ps1   (Windows)")
        print("           bash tools/run_service.sh      (Linux/macOS)")
        return 1
    if status != 200 or not isinstance(body, dict):
        line(BAD, f"GET /health → HTTP {status}: {str(body)[:120]}")
        problems.append("/health не отвечает 200")
    else:
        line(OK, f"/health → {body.get('status')} (версия {body.get('version')})")
        line(OK if body.get("emc") else WARN,
             f"конвертер .NET/.epanet: {'доступен' if body.get('emc') else 'НЕДОСТУПЕН — принимается только .inp'}")
        line(OK if body.get("simulation") else WARN,
             f"расчёт EPANET: {'включён' if body.get('simulation') else 'ОТКЛЮЧЁН (RUN_SIMULATION=0)'}")
        if not body.get("simulation"):
            notes.append("расчёт выключен: у разметки не будет KPI и фактов")
        st = body.get("stats") or {}
        line(OK, f"данные: моделей {st.get('models', 0)}, разметок {st.get('annotations', 0)} "
                 f"(не в экспорте: {st.get('annotations_unexported', 0)}), экспертов {st.get('experts', 0)}")
        if body.get("auto_export_hours"):
            line(OK, f"автоэкспорт каждые {body.get('auto_export_hours')} ч")
        else:
            line(WARN, "автоэкспорт выключен (AUTO_EXPORT_HOURS=0) — данные придётся сохранять вручную")

    # 2. страницы
    print("\n2. Страницы отдаются")
    status, _, final = _req(f"{base}/")
    line(OK if status == 200 else BAD, f"главная → HTTP {status} ({final.split('?')[0]})")
    if status != 200:
        problems.append("главная страница не открывается")
    status, body, _ = _req(f"{base}/static/index.html")
    size = len(body) if isinstance(body, str) else 0
    line(OK if status == 200 and size > 5000 else BAD,
         f"интерфейс разметки → HTTP {status}, {size} символов")
    status, _, _ = _req(f"{base}/admin")
    line(OK if status == 200 else BAD, f"админка → HTTP {status}")
    if status != 200:
        problems.append("админка недоступна")

    # 3. вход гидравлика
    print("\n3. Вход гидравлика")
    if args.token:
        status, body, _ = _req(f"{base}/api/session", "POST", payload={"token": args.token})
        if status == 200 and isinstance(body, dict):
            line(OK, f"вход выполнен: {body.get('expert_id')} ({body.get('role')}), "
                     f"разметок у него: {body.get('annotations')}")
            status2, _, _ = _req(f"{base}/?token={args.token}")
            line(OK if status2 in (200, 307) else BAD,
                 f"персональная ссылка /?token=… → HTTP {status2} (редирект на интерфейс)")
        else:
            line(BAD, f"вход не выполнен (HTTP {status}): {body}")
            problems.append("токен гидравлика не подходит")
    else:
        line(WARN, "не проверялся: запустите с --token <токен гидравлика>")

    # 4. админка
    print("\n4. Доступ администратора")
    if args.admin:
        status, body, _ = _req(f"{base}/api/admin/overview", headers={"X-Admin-Token": args.admin})
        if status == 200 and isinstance(body, dict):
            st = body.get("stats") or {}
            line(OK, f"сводка: моделей {st.get('models', 0)}, разметок {st.get('annotations', 0)}, "
                     f"экспертов {st.get('experts', 0)}")
            for e in (body.get("experts") or [])[:5]:
                line(OK, f"эксперт {e.get('expert_id')} ({e.get('role')}), разметок {e.get('n_annotations')}"
                         + (f", ссылка {e.get('link')}" if e.get("link") else ""))
            exports = body.get("exports") or []
            line(OK if exports else WARN,
                 f"экспортов готово: {len(exports)}" + (f", последний {exports[0].get('file')}" if exports else
                                                        " (первый появится после автоэкспорта или кнопки в админке)"))
        else:
            line(BAD, f"админка не пускает (HTTP {status}): {body}")
            problems.append("ADMIN_TOKEN не подходит")
    else:
        line(WARN, "не проверялся: запустите с --admin <ADMIN_TOKEN>")

    # 5. итог
    print("\n" + "-" * 78)
    if problems:
        print(f"{BAD} ЕСТЬ ЗАМЕЧАНИЯ:")
        for p in problems:
            print(f"   • {p}")
        code = 1
    else:
        print(f"{OK} Всё в порядке: сервис работает, страницы отдаются, экспорт настроен.")
        code = 0
    for n in notes:
        print(f"   {WARN} {n}")
    if not args.token or not args.admin:
        print("   (для полной проверки передайте --token и --admin)")
    return code


if __name__ == "__main__":
    sys.exit(main())
