@echo off
chcp 65001 >nul
echo ======================================================================
echo Установка PyTorch CUDA (cu126) + QLoRA для NVIDIA GeForce RTX 3060 Laptop GPU
echo Целевой Python ноутбука: "e:\Code\EPANET_AI\.venv\Scripts\python.exe"
echo ВАЖНО: Сначала ЗАКРОЙТЕ окно Jupyter / VS Code, чтобы разблокировать DLL!
echo ======================================================================
pause
"e:\Code\EPANET_AI\.venv\Scripts\python.exe" -m pip uninstall -y torch torchvision torchaudio
"e:\Code\EPANET_AI\.venv\Scripts\python.exe" -m pip install torch --index-url https://download.pytorch.org/whl/cu126
"e:\Code\EPANET_AI\.venv\Scripts\python.exe" -m pip install -U "transformers>=4.57.0" "peft>=0.15.0" "trl>=0.16.0" "datasets>=3.2.0" "accelerate>=1.4.0" "bitsandbytes>=0.45.0"
echo.
echo === ПРОВЕРКА ПОДКЛЮЧЕНИЯ ВИДЕОКАРТЫ ===
"e:\Code\EPANET_AI\.venv\Scripts\python.exe" -c "import torch; print('CUDA OK:', torch.cuda.is_available(), '| GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO')"
pause
