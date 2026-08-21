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
# Debian/Ubuntu
sudo apt update
sudo apt install -y ffmpeg python3-venv python3-pip git

# macOS
brew install ffmpeg
```

## Linux 部署与启动

适合 H20 / 其它带 CUDA 的 Linux 服务器：

```bash
# 1) 拉代码
git clone https://github.com/yjangout/VoxClone.git
cd VoxClone

# 2) 虚拟环境
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip

# 3) 先装 CUDA 版 torch（按机器 CUDA 选 index；示例 CUDA 13）
pip install --index-url https://download.pytorch.org/whl/cu130 \
  torch torchvision torchaudio

# 若是 CUDA 12.x，可改用：
# pip install --index-url https://download.pytorch.org/whl/cu124 \
#   torch torchvision torchaudio

# 4) 再装项目依赖
pip install -r requirements.txt

# 5) 配置
cp .env.example .env
# 编辑 .env，至少设置：
#   TTS_MODEL=/你的路径/VoxCPM2
#   TTS_DEVICE=cuda

set -a; source .env; set +a

# 6) 启动（默认端口 16009）
uvicorn app.main:app --host 0.0.0.0 --port 16009
```

浏览器访问：`http://<服务器IP>:16009`。

### 后台常驻（可选）

```bash
# nohup
nohup uvicorn app.main:app --host 0.0.0.0 --port 16009 \
  > /tmp/voxclone.log 2>&1 &

# 或 systemd 用户服务示例 /etc/systemd/system/voxclone.service：
# [Unit]
# Description=VoxClone TTS
# After=network.target
#
# [Service]
# WorkingDirectory=/path/to/VoxClone
# EnvironmentFile=/path/to/VoxClone/.env
# ExecStart=/path/to/VoxClone/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 16009
# Restart=on-failure
#
# [Install]
# WantedBy=multi-user.target
#
# sudo systemctl daemon-reload && sudo systemctl enable --now voxclone
```

健康检查：

```bash
curl -s http://127.0.0.1:16009/health
# 若配置了 BASE_PATH=/beta/voxclone：
curl -s http://127.0.0.1:16009/beta/voxclone/health
```

### 反代子路径：用 `BASE_PATH`（代码已适配）

页面/API/静态资源会自动带前缀，无需再拆多条 nginx location。

```bash
# .env
BASE_PATH=/beta/voxclone
```

nginx **保留完整路径**（`proxy_pass` 不要加会剥前缀的尾斜杠）：

```nginx
location /beta/voxclone/ {
    proxy_pass http://127.0.0.1:16009;   # 无尾斜杠：URI 原样转发
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
}
```

然后打开 `https://host/beta/voxclone/`。`/health` 里会返回 `"base_path": "/beta/voxclone"`。

本地直连 `http://IP:16009` 时把 `BASE_PATH` 留空即可。

## 本机快速启动（开发）

```bash
cd VoxClone
source .venv/bin/activate
set -a; source .env; set +a
uvicorn app.main:app --host 0.0.0.0 --port 16009
```

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
