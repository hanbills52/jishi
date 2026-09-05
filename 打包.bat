@echo off
rem 基石 · 打包脚本（文件夹版 onedir，NER 模型不内置）
rem 产物：dist\基石\ 整个文件夹即发行包；如需 NER，把 app\resources\models\ner 拷到 dist\基石\models\ner
rem 排除项：onnxruntime 自带的转换工具链（transformers/torch 等）会拖进 400MB 垃圾，应用运行用不到
cd /d "%~dp0"
.venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --name "基石" ^
  --add-data "app\resources\lexicons;app\resources\lexicons" ^
  --collect-all rapidocr_onnxruntime ^
  --exclude-module torch --exclude-module transformers --exclude-module tokenizers ^
  --exclude-module huggingface_hub --exclude-module safetensors --exclude-module rich ^
  --exclude-module pytest --exclude-module onnx --exclude-module onnxscript ^
  --exclude-module onnxruntime.transformers --exclude-module onnxruntime.quantization ^
  --distpath dist --workpath build app\main.py
echo.
echo 打包完成：dist\基石\基石.exe
pause
