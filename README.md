# 基石 · 本地化批量文档脱敏工具

> 纯本地离线运行的中文文档脱敏工具，面向法律文书、合同、判决书的批量脱敏与回溯还原。运行时不发起任何网络请求，模型与词典随程序分发，文档不出本机。

## 功能特性

- **三层识别 + 仲裁器**
  - 规则层：正则 + 校验位验证（身份证 GB11643、银行卡 Luhn、统一社会信用代码），从源头防假阳性
  - 词典层：姓氏 / 民族 / 提示词 / 司法停用词，上下文模式识别人名 / 公司 / 地址
  - NER 层：基于 [uer/roberta-base-finetuned-cluener2020-chinese](https://huggingface.co/uer/roberta-base-finetuned-cluener2020-chinese) 转 ONNX，BMES 标注，自实现简化 WordPiece 分词器，运行时仅依赖 `onnxruntime`（不打包 torch/transformers）。默认关闭，按需启用
  - 仲裁器：层优先级 + 置信度分桶（≥0.90 直接生效 / 0.60~0.90 待确认），并合并相邻实体碎片
- **多文档格式**
  - Word（.docx）：run 级替换，保留加粗 / 字体等样式，覆盖正文、表格、页眉页脚、文本框
  - 文字型 PDF：基于 PyMuPDF 的 redaction + 字号自适应
  - 扫描件 PDF：RapidOCR 识别，结果缓存避免二次 OCR，多文件并行时自适应线程预算
- **代称体系**：天干 → 地支 → 天干+序号，类别后缀（人名"某"、公司"公司"、单位"单位"、地址"地址"），跨文档一致
- **加密映射与回溯**：导出脱敏文档时同步生成 `AES-256-GCM + scrypt` 加密的映射文件；回溯模式凭"处理后文档 + 映射 + 密码"还原，并产出"未还原项"报告
- **人工干预**：映射面板支持启停、删除、自定义新增、同名拆分；待确认项默认不生效，导出前弹确认

## 技术栈

| 层 | 选型 |
|---|---|
| 语言 | Python 3.11+ |
| 界面 | PySide6（QThread 异步） |
| Word 解析 | python-docx |
| PDF 解析 | PyMuPDF (fitz) |
| OCR | rapidocr-onnxruntime |
| NER 推理 | onnxruntime（CPU） |
| 加密 | cryptography |

## 快速开始

```bash
# 1. 克隆
git clone git@github.com:hanbills52/jishi.git
cd jishi

# 2. 建虚拟环境并装依赖
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
# 若需 NER 层（可选，默认关闭）：
pip install onnxruntime numpy

# 3. 运行
python app/main.py
```

NER 模型默认随仓库排除（体积约 800MB，见 `.gitignore`）。如需启用 NER 层，从 [uer/roberta-base-finetuned-cluener2020-chinese](https://huggingface.co/uer/roberta-base-finetuned-cluener2020-chinese) 下载并转换为 ONNX 后，放置到 `app/resources/models/ner/`（目录结构见 `app/core/recognize/ner.py` 的 `_model_dir()`）。

## 项目结构

```
app/
├── main.py                 # 入口
├── ui/                     # 三栏界面 + 回溯面板
├── core/
│   ├── pipeline.py         # 批次队列与文件状态机
│   ├── parser/             # docx / 文字PDF / 扫描件PDF 解析
│   ├── recognize/          # 规则 / 词典 / NER + 仲裁器
│   ├── mapping/            # 全局映射表 / 代称生成 / 加密 / 回溯
│   └── redact/             # docx / PDF / 扫描件 替换器
└── resources/
    ├── lexicons/           # 姓氏、民族、提示词、司法停用词等
    └── models/ner/         # NER ONNX 模型（按需，仓库排除）
```

完整设计依据见 [实施方案.md](./实施方案.md)。

## 打包构建

可执行版本基于 PyInstaller（onedir 模式）打包，配置见 [`基石.spec`](./基石.spec)：

```bash
pip install pyinstaller
pyinstaller 基石.spec                # 产物输出到 dist/基石/
```

NER 模型（约 800MB）不随仓库分发，如需 NER 层，按"快速开始"的说明自行放置到 `app/resources/models/ner/`，或在打包后将其放到 `dist/基石/models/ner/`（exe 同级外置目录）。

## 下载

预编译可执行包见 [Releases](https://github.com/hanbills52/jishi/releases)。解压后双击 `基石.exe` 即可使用，无需安装 Python。

## 许可证

本项目源代码采用 [MIT License](./LICENSE) 开源。

### 二进制分发须知

**预编译可执行包（`基石.exe` 及其 `_internal` 目录）包含 AGPL-3.0 许可的组件（PyMuPDF）。** 按 AGPL 条款，通过网络或介质向他人分发该二进制时，必须对应公开完整对应源代码——相应源代码见本仓库。商业分发（闭源场景）请改用 [PyMuPDF 商业授权](https://mupdf.com/licensing/) 或替换为 MIT/ Apache 等许可的 PDF 引擎。

主要运行时依赖许可一览：

| 依赖 | 许可 |
|---|---|
| PyMuPDF (fitz) | **AGPL-3.0**（影响二进制分发） |
| PySide6 (Qt) | LGPL-3.0 / GPL / 商业（动态链接，LGPL 合规可用） |
| rapidocr-onnxruntime | Apache-2.0 |
| onnxruntime | MIT |
| cryptography | Apache-2.0 / BSD-3-Clause |
| python-docx | MIT |

> 即：源码层面 MIT 开源无障碍；二进制层面因 PyMuPDF 的 AGPL，分发时须遵守上述公开源代码义务。
