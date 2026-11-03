# Директория для реальных фикстур AquaBit (`tests/fixtures/`)

Поместите сюда реальные выгрузки AquaBit (`.zip` или папки с `.csv`, например экспорт модели «Тенино»):
- `tests/fixtures/real/` — реальные выгрузки для инспекции заголовков и сквозных интеграционных тестов.

После загрузки файлов выполните:
```bash
aquabit-ai inspect-headers tests/fixtures/real/
```
Несопоставленные заголовки добавляются в `src/aquabit_ai/config/field_aliases.yaml` перед запуском Этапа 3 (Preprocessing).
