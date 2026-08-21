# VoxClone

独立语音复刻 + 文本朗读应用（VoxCPM2）。

- 网页选择**已有** speaker，输入文本，生成并播放 wav
- 上传 mp3 / m4a / wav 复刻新音色（自动转成克隆所需 wav）
- 音色以文件保存：`voices/<speaker>/ref.wav` + `ref.txt`

## 依赖

- Python 3.10+
- **ffmpeg**（转码必需）
- **CUDA GPU** + 匹配的 PyTorch（默认 `TTS_DEVICE=cuda`）
- VoxCPM2 模型权重（本地目录）

```bash
# macOS
brew install ffmpeg

# Debian/Ubuntu
sudo apt install -y ffmpeg
```

## 安装与启动

```bash
cd ~/Desktop/self/VoxClone
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
# 先按你的 CUDA 版本安装 torch，再装本项目依赖，例如 CUDA 13：
# pip install --index-url https://download.pytorch.org/whl/cu130 torch torchvision torchaudio
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env：把 TTS_MODEL 改成 VoxCPM2 模型目录

export TTS_MODEL=/path/to/VoxCPM2
export TTS_DEVICE=cuda
uvicorn app.main:app --host 0.0.0.0 --port 16009
```

浏览器打开 **http://localhost:16009**。

## 使用流程

1. **复刻**：复制页面推荐文案 → 口齿清晰朗读并录音 → 填写音色名 → 上传音频
2. **朗读**：在下拉框选择刚复刻的 speaker → 输入文本 →「生成并播放」

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 模型状态与 speakers |
| GET | `/api/speakers` | 列出音色 |
| GET | `/api/clone-script` | 推荐朗读文案 |
| POST | `/api/speakers` | multipart：`name` + `audio` + 可选 `transcript` |
| DELETE | `/api/speakers/{name}` | 删除音色 |
| POST | `/api/tts` | JSON `{ "text", "speaker" }` → `audio/wav` |

示例：

```bash
curl -s http://127.0.0.1:16009/health

curl -s -X POST http://127.0.0.1:16009/api/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"今天想聊点什么？","speaker":"xiaoming"}' \
  --output /tmp/out.wav
```

## 目录

```text
app/           FastAPI + VoxCPM2 引擎 + ffmpeg 转码
static/        单页前端
voices/        运行时音色库（上传后生成，默认不入库）
```

## 说明

- 复刻参考音频建议 **8–30 秒**、单人、无背景音乐；`ref.txt` 须与音频内容一致
- 新增音色目录会被自动扫描，无需改代码
- 本项目不依赖 LiveKit / VoxEMW 对话链路
