# XB-SVCB FastAPI 接入文档

适用版本：XB-SVCB 0.0.23

## 启动与安全

FastAPI 服务默认关闭，不会随 XB-SVCB 自动启动。打开软件的“资料库 -> API 接入”，配置监听范围和端口，然后手动点击“启动服务”。关闭软件或点击“停止服务”会释放监听端口。

- 仅本机：监听 `127.0.0.1`，适合同一台电脑上的自动化程序。
- 局域网：监听 `0.0.0.0`，同一网络的设备可通过软件页面显示的局域网地址调用。
- 默认端口：`8765`，可改为 `1024` 到 `65535` 之间的空闲端口。
- 鉴权：除 `GET /health`、`/docs`、`/redoc` 和 `/openapi.json` 外，请求必须携带 `X-API-Key`。
- API Key：在“API 接入”页查看、复制或重新生成。服务运行时不能更换密钥。

局域网模式只应在可信网络使用。Windows 防火墙首次拦截时，需要允许 XB-SVCB 在专用网络通信；不要把端口直接映射到公网。

## 在线接口文档

服务启动后可访问：

- Swagger UI：`http://127.0.0.1:8765/docs`
- ReDoc：`http://127.0.0.1:8765/redoc`
- OpenAPI JSON：`http://127.0.0.1:8765/openapi.json`

端口修改后请同步替换上述地址。软件内“连通性测试”会使用当前 API Key 实际请求模型接口，并返回延迟与模型数量。

## 标准调用流程

1. 调用 `POST /api/v1/uploads` 上传源音频，取得 `upload_id`。
2. 调用 `GET /api/v1/models` 读取模型及 `default_id`。
3. 调用 `POST /api/v1/jobs` 创建单模型或多模型任务，HTTP 状态码为 `202`；批量任务可使用 `POST /api/v1/jobs/batch`。
4. 轮询 `GET /api/v1/jobs/{job_id}`，直到 `status` 为 `done` 或 `failed`。
5. 成功后请求返回的 `result_url` 下载成品。

任务进入 XB-SVCB 的同一条串行推理队列。软件界面和外部 API 创建的任务会相互可见，并共享当前的 CUDA、DirectML 或 CPU 推理环境。

## Python 示例

需要安装 `requests`：

```bash
pip install requests
```

```python
import time
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8765"
HEADERS = {"X-API-Key": "替换为软件中显示的 API Key"}

with open("song.wav", "rb") as audio:
    response = requests.post(
        f"{BASE_URL}/api/v1/uploads",
        headers=HEADERS,
        files={"file": ("song.wav", audio, "audio/wav")},
        timeout=None,
    )
    response.raise_for_status()
    upload = response.json()

models = requests.get(f"{BASE_URL}/api/v1/models", headers=HEADERS, timeout=30)
models.raise_for_status()
model_data = models.json()
model_id = model_data["default_id"] or model_data["items"][0]["id"]

response = requests.post(
    f"{BASE_URL}/api/v1/jobs",
    headers=HEADERS,
    json={
        "source_upload_id": upload["upload_id"],
        "model_id": model_id,
        "params": {"pitch": 0, "f0_method": "rmvpe", "device": "auto"},
    },
    timeout=30,
)
response.raise_for_status()
job = response.json()

while True:
    response = requests.get(
        f"{BASE_URL}/api/v1/jobs/{job['id']}", headers=HEADERS, timeout=30
    )
    response.raise_for_status()
    current = response.json()
    if current["status"] in {"done", "failed"}:
        break
    time.sleep(2)

if current["status"] != "done":
    raise RuntimeError(current.get("error") or "任务失败")

response = requests.get(f"{BASE_URL}{current['result_url']}", headers=HEADERS, timeout=None)
response.raise_for_status()
Path("cover.wav").write_bytes(response.content)
```

## SeedVC 任务

SeedVC 需要额外的目标音色参考音频。先通过上传接口分别上传源音频和参考音频，再把参考音频 ID 放入 `reference_upload_id`：

```json
{
  "source_upload_id": "源音频 upload_id",
  "reference_upload_id": "参考音频 upload_id",
  "model_id": "SeedVC 模型 ID",
  "params": {
    "pitch": 0,
    "device": "auto"
  }
}
```

## 多模型混唱

`mode` 设为 `multi` 后，在 `models` 中为每个模型设置独立参数，再用 `segments` 分配演唱区间。同一段的 `model_ids` 包含多个模型时会生成人声合唱：

```json
{
  "source_upload_id": "源音频 upload_id",
  "mode": "multi",
  "workflow": "auto_vocal_merge",
  "models": [
    {"model_id": "model_svc", "params": {"pitch": 0, "device": "auto"}},
    {
      "model_id": "model_seedvc",
      "reference_upload_id": "SeedVC 参考音频 upload_id",
      "params": {"pitch": 0, "device": "auto"}
    }
  ],
  "segments": [
    {"start": 0, "end": 12.5, "model_ids": ["model_svc"]},
    {"start": 12.5, "end": 24, "model_ids": ["model_svc", "model_seedvc"]}
  ]
}
```

多模型工作流可使用 `auto_mix`、`auto_vocal_merge`、`manual_vocal_merge`、`auto_then_editor` 和 `full_manual_editor`。`auto_vocal_merge`、`manual_vocal_merge` 不适用于单模型模式。

### 完整 Python 示例

下面的示例使用两个非 SeedVC 模型完成一首多模型翻唱：前 `20` 秒由模型 A 演唱，`20-40` 秒由模型 B 演唱，`40-60` 秒由两个模型合唱。运行前请在 `GET /api/v1/models` 的响应或软件模型页中找到模型 ID，并修改歌曲路径、API Key、模型 ID 和时间段。

```python
import time
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8765"
API_KEY = "替换为软件中显示的 API Key"
SOURCE_AUDIO = Path("song.wav")
OUTPUT_AUDIO = Path("multi_model_cover.wav")

# 从 GET /api/v1/models 返回的 items[].id 中选择两个模型。
MODEL_A_ID = "替换为模型 A 的 ID"
MODEL_B_ID = "替换为模型 B 的 ID"

session = requests.Session()
session.headers.update({"X-API-Key": API_KEY})

# 1. 检查所选模型。这个示例不使用 SeedVC，因而不需要参考音频。
response = session.get(f"{BASE_URL}/api/v1/models", timeout=30)
response.raise_for_status()
available_models = {item["id"]: item for item in response.json()["items"]}

for model_id in (MODEL_A_ID, MODEL_B_ID):
    if model_id not in available_models:
        choices = ", ".join(
            f"{item['name']}={item['id']}" for item in available_models.values()
        )
        raise RuntimeError(f"模型 ID 不存在：{model_id}\n可用模型：{choices}")
    if available_models[model_id].get("framework") == "seed-vc":
        raise RuntimeError("此示例请选择非 SeedVC 模型；SeedVC 还需要上传参考音频")

print("模型 A：", available_models[MODEL_A_ID]["name"])
print("模型 B：", available_models[MODEL_B_ID]["name"])

# 2. 上传源歌曲。
with SOURCE_AUDIO.open("rb") as audio:
    response = session.post(
        f"{BASE_URL}/api/v1/uploads",
        files={"file": (SOURCE_AUDIO.name, audio, "application/octet-stream")},
        timeout=None,
    )
response.raise_for_status()
source_upload_id = response.json()["upload_id"]

# 3. 创建多模型任务。model_ids 中有多个 ID 的片段会生成合唱。
response = session.post(
    f"{BASE_URL}/api/v1/jobs",
    json={
        "source_upload_id": source_upload_id,
        "title": "多模型翻唱示例",
        "mode": "multi",
        "workflow": "auto_mix",
        "models": [
            {
                "model_id": MODEL_A_ID,
                "params": {"pitch": 0, "f0_method": "rmvpe", "device": "auto"},
            },
            {
                "model_id": MODEL_B_ID,
                "params": {"pitch": 0, "f0_method": "rmvpe", "device": "auto"},
            },
        ],
        "segments": [
            {"start": 0.0, "end": 20.0, "model_ids": [MODEL_A_ID]},
            {"start": 20.0, "end": 40.0, "model_ids": [MODEL_B_ID]},
            {
                "start": 40.0,
                "end": 60.0,
                "model_ids": [MODEL_A_ID, MODEL_B_ID],
            },
        ],
    },
    timeout=30,
)
response.raise_for_status()
job = response.json()
print("任务已创建：", job["id"])

# 4. 等待串行推理完成。
while True:
    response = session.get(f"{BASE_URL}/api/v1/jobs/{job['id']}", timeout=30)
    response.raise_for_status()
    current = response.json()
    print(f"状态：{current['status']}，进度：{current.get('progress', 0)}%")
    if current["status"] in {"done", "failed"}:
        break
    time.sleep(2)

if current["status"] != "done":
    raise RuntimeError(current.get("error") or "多模型翻唱失败")

# 5. 流式下载最终混音成品。
with session.get(
    f"{BASE_URL}{current['result_url']}", stream=True, timeout=None
) as response:
    response.raise_for_status()
    with OUTPUT_AUDIO.open("wb") as output:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                output.write(chunk)

# 任务结束后再清理源文件；任务和成品仍保留在“我的作品”中。
response = session.delete(
    f"{BASE_URL}/api/v1/uploads/{source_upload_id}", timeout=30
)
response.raise_for_status()
print("成品已保存：", OUTPUT_AUDIO.resolve())
```

`segments` 的时间单位为秒，应按歌曲实际时长覆盖需要演唱的区间；每个 `model_ids` 必须来自同一请求的 `models`。要使用 SeedVC，请先上传参考音频，并在对应的 `models` 项中增加 `reference_upload_id`。

## 音频编辑器调用流程

1. 上传本地音频后调用 `POST /api/v1/editor/projects`，或直接通过 `work_id` 从翻唱作品创建工程。
2. 调用 `GET /api/v1/editor/projects/{project_id}` 读取时间轴。片段不返回本机 `file` 路径，而是提供 `audio_url` 和 `waveform_url`。
3. 可直接修改音量、淡化、声道、包络、角色和效果链，再通过 `PUT /api/v1/editor/projects/{project_id}` 保存；新素材必须先调用片段导入、切分、人声分离或局部重推理接口创建。
4. 调用工程、音轨或片段的 `/audio` 接口渲染下载 WAV、MP3 或 FLAC。

客户端可以把读取到的工程原样修改后提交。`audio_url`、`waveform_url` 和 `render_url` 会在保存时自动丢弃，片段真实文件引用由服务端恢复，外部请求不能覆盖为任意本机路径。

## 接口清单

| 方法               | 路径                                                                                     | 说明                                                 |
| ------------------ | ---------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| `GET`            | `/health`                                                                              | 健康检查，无需 API Key                               |
| `GET`            | `/api/v1/system`                                                                       | 查看集成工具与 GPU 推理环境                          |
| `GET`            | `/api/v1/models`                                                                       | 模型列表和默认模型                                   |
| `POST`           | `/api/v1/models/default`                                                               | 设置默认模型                                         |
| `GET`            | `/api/v1/models/{model_id}`                                                            | 单个模型信息                                         |
| `POST`           | `/api/v1/models/{model_id}/favorite`                                                   | 切换收藏状态                                         |
| `POST`           | `/api/v1/models/{model_id}/inspect`                                                    | 检查模型，可选自动修复                               |
| `DELETE`         | `/api/v1/models/{model_id}`                                                            | 删除模型及托管文件                                   |
| `POST`           | `/api/v1/uploads`                                                                      | 流式上传源音频或参考音频，不限制文件大小             |
| `DELETE`         | `/api/v1/uploads/{upload_id}`                                                          | 删除不再使用的上传文件                               |
| `GET`            | `/api/v1/jobs`                                                                         | 最近任务列表，`limit` 最大 200                     |
| `GET`            | `/api/v1/jobs/queue`                                                                   | 当前推理队列                                         |
| `GET`            | `/api/v1/jobs/history`                                                                 | 推理历史                                             |
| `GET/POST`       | `/api/v1/jobs/presets`                                                                 | 列出或保存推理参数预设                               |
| `DELETE`         | `/api/v1/jobs/presets/{preset_id}`                                                     | 删除参数预设                                         |
| `POST`           | `/api/v1/jobs`                                                                         | 创建单模型或多模型翻唱任务                           |
| `POST`           | `/api/v1/jobs/batch`                                                                   | 批量创建任务，最多 50 项                             |
| `GET`            | `/api/v1/jobs/{job_id}`                                                                | 查询任务状态和进度                                   |
| `PATCH`          | `/api/v1/jobs/{job_id}`                                                                | 重命名任务                                           |
| `DELETE`         | `/api/v1/jobs/{job_id}`                                                                | 删除任务及生成文件                                   |
| `POST`           | `/api/v1/jobs/{job_id}/retry`                                                          | 重试任务                                             |
| `GET`            | `/api/v1/jobs/{job_id}/audio`                                                          | 下载成品；`stem` 可选 output、instrumental、vocals |
| `GET/POST`       | `/api/v1/editor/projects`                                                              | 列出或创建编辑工程                                   |
| `GET/PUT/DELETE` | `/api/v1/editor/projects/{project_id}`                                                 | 读取、保存或删除工程                                 |
| `POST`           | `/api/v1/editor/projects/{project_id}/undo`                                            | 撤销                                                 |
| `POST`           | `/api/v1/editor/projects/{project_id}/redo`                                            | 重做                                                 |
| `POST`           | `/api/v1/editor/projects/{project_id}/tracks`                                          | 添加音轨                                             |
| `DELETE`         | `/api/v1/editor/projects/{project_id}/tracks/{track_id}`                               | 删除音轨                                             |
| `POST`           | `/api/v1/editor/projects/{project_id}/tracks/{track_id}/clips`                         | 从 upload_id 导入片段                                |
| `GET`            | `/api/v1/editor/projects/{project_id}/audio`                                           | 渲染下载工程混音                                     |
| `GET`            | `/api/v1/editor/projects/{project_id}/tracks/{track_id}/audio`                         | 渲染下载音轨                                         |
| `GET`            | `/api/v1/editor/projects/{project_id}/clips/{clip_id}/audio`                           | 渲染下载片段                                         |
| `GET`            | `/api/v1/editor/projects/{project_id}/clips/{clip_id}/waveform`                        | 读取片段波形                                         |
| `POST`           | `/api/v1/editor/projects/{project_id}/tracks/{track_id}/clips/{clip_id}/split/silence` | 静音检测切句                                         |
| `POST`           | `/api/v1/editor/projects/{project_id}/tracks/{track_id}/clips/{clip_id}/split/lyrics`  | TXT/LRC 歌词切分                                     |
| `POST`           | `/api/v1/editor/projects/{project_id}/tracks/{track_id}/clips/{clip_id}/separate`      | UVR 人声/伴奏分离                                    |
| `POST`           | `/api/v1/editor/projects/{project_id}/tracks/{track_id}/clips/{clip_id}/rerun`         | 用声音模型局部重推理                                 |
| `POST`           | `/api/v1/editor/projects/{project_id}/tracks/{track_id}/clips/merge`                   | 渲染合并多个片段                                     |

## 常见状态码

| 状态码  | 含义                                |
| ------- | ----------------------------------- |
| `200` | 请求成功                            |
| `201` | 音频上传成功                        |
| `202` | 任务已加入推理队列                  |
| `401` | API Key 缺失或错误                  |
| `404` | 模型、任务、文件或 upload_id 不存在 |
| `409` | 结果尚未生成，或当前状态不允许操作  |
| `415` | 文件格式不受支持                    |
| `422` | 请求字段或参数组合无效              |

## 文件与清理

API 不设置上传大小上限，接收内容时以固定小块流式写盘，不会把整份音频一次载入内存；实际容量只受数据目录所在磁盘的可用空间限制。上传文件保存在 XB-SVCB 当前数据目录的 `api/uploads` 下，并会随数据目录迁移。任务创建后请等推理结束再删除对应上传文件；不再使用时可调用删除接口清理。生成作品仍由 XB-SVCB 的“我的作品”统一管理。
