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
```

### Nginx / 反代注意事项（静态资源加载失败）

页面里的 CSS/JS 使用**站点根路径**：`/static/style.css`、`/static/app.js`，API 也是 `/api/...`、`/health`。

如果只把某个子路径反代到 16009（例如 `https://host/beta/voxclone/` → `127.0.0.1:16009`），浏览器仍会去请求 **`https://host/static/...`**（丢掉前缀），导致样式和脚本 404、页面“空白/半残”。

建议任选其一：

**1）推荐：整站根路径反代（或独立域名/端口）**

```nginx
# 例如 https://tts.example.com/ 或 https://host:16009/
location / {
    proxy_pass http://127.0.0.1:16009;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    # TTS 合成可能较久
    proxy_read_timeout 300s;
}
```

**2）必须挂在子路径时：把前缀剥掉，并保证 `/static`、`/api`、`/` 都进同一 upstream**

```nginx
# 访问 https://host/beta/voxclone/  →  后端看到 /
location /beta/voxclone/ {
    proxy_pass http://127.0.0.1:16009/;   # 注意末尾斜杠：剥掉 /beta/voxclone
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
}
```

但即便剥掉前缀，HTML 里写的仍是 `/static/...`（相对**域名根**），浏览器不会自动加 `/beta/voxclone`。子路径部署下仍会缺静态资源，除非：

- 改成独立域名/根路径反代（方案 1），或
- 额外为静态资源单独反代，例如：

```nginx
location /static/ {
    proxy_pass http://127.0.0.1:16009/static/;
}
location /api/ {
    proxy_pass http://127.0.0.1:16009/api/;
    proxy_read_timeout 300s;
}
location = /health {
    proxy_pass http://127.0.0.1:16009/health;
}
location = / {
    proxy_pass http://127.0.0.1:16009/;
}
```

自查：打开浏览器开发者工具 → Network，确认 `/static/style.css`、`/static/app.js` 是否 200；若是 404，就是反代路径没配对。

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
