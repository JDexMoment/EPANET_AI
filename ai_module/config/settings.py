import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
SRC_ENGINES_DIR = REPO_ROOT / "SRC_engines"
DATA_DIR = BASE_DIR / "data"
REPORTS_OUTPUT_DIR = BASE_DIR / "reports" / "generated"

# Ensure directories exist
for d in [
    DATA_DIR / "raw_networks",
    DATA_DIR / "scenarios",
    DATA_DIR / "sft_datasets",
    DATA_DIR / "benchmarks",
    REPORTS_OUTPUT_DIR,
]:
    d.mkdir(parents=True, exist_ok=True)

# LLM Settings (Roadmap Section 6 & 15)
# Supports:
#   - "ollama" (local Ollama server, e.g. qwen3:4b or qwen3:8b)
#   - "openai_compat" (vLLM / llama.cpp server / LM Studio)
#   - "hf_local" (HuggingFace Transformers + optional PEFT LoRA adapter)
#   - "deterministic_pilot" (Rule-based + template synthesizer when LLM runtime is offline)
LLM_BACKEND = os.getenv("EPANET_AI_BACKEND", "auto")
LLM_MODEL_NAME = os.getenv("EPANET_AI_MODEL", "Qwen/Qwen3-4B")
OLLAMA_MODEL_NAME = os.getenv("EPANET_AI_OLLAMA_MODEL", "qwen3:4b")
LOCAL_LLM_API_URL = os.getenv("EPANET_AI_LLM_URL", "http://127.0.0.1:11434/v1")
LORA_ADAPTER_PATH = os.getenv("EPANET_AI_LORA_PATH", str(BASE_DIR / "training" / "checkpoints" / "qwen3-epanet-lora"))

# Engineering Analytics Thresholds (SI units: meters, m/s, m/km, L/s)
DEFAULT_THRESHOLDS = {
    "min_pressure_warning_m": 15.0,     # Нижний порог свободного напора (предупреждение)
    "min_pressure_critical_m": 10.0,    # Критически низкое давление (авария / подсос)
    "negative_pressure_m": 0.0,         # Отрицательное давление (вакуумирование / кавитация)
    "max_pressure_warning_m": 60.0,     # Высокое давление (повышенный износ и утечки)
    "max_pressure_critical_m": 75.0,    # Превышение допустимого рабочего давления сети
    "max_velocity_warning_mps": 2.5,    # Повышенная скорость потока в трубе (м/с)
    "max_velocity_critical_mps": 3.5,   # Критическая скорость (гидроудар, кавитация, эрозия)
    "min_velocity_stagnation_mps": 0.05,# Застой воды (при ненулевом расходе или тупиковой линии)
    "max_headloss_m_per_km": 15.0,      # Высокий гидравлический уклон (м/км) — узкое место
    "top_n_alerts": 10,                 # Количество Top-N проблем, передаваемых в промпт (п.10, 13 Roadmap)
}
