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
3. 调用 `POST /api/v1/jobs` 创建任务，HTTP 状态码为 `202`。
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

## 接口清单

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查，无需 API Key |
| `GET` | `/api/v1/system` | 查看集成工具与 GPU 推理环境 |
| `GET` | `/api/v1/models` | 模型列表和默认模型 |
| `GET` | `/api/v1/models/{model_id}` | 单个模型信息 |
| `POST` | `/api/v1/uploads` | 流式上传源音频或参考音频，不限制文件大小 |
| `DELETE` | `/api/v1/uploads/{upload_id}` | 删除不再使用的上传文件 |
| `GET` | `/api/v1/jobs` | 最近任务列表，`limit` 最大 200 |
| `GET` | `/api/v1/jobs/queue` | 当前推理队列 |
| `POST` | `/api/v1/jobs` | 创建单模型翻唱任务 |
| `GET` | `/api/v1/jobs/{job_id}` | 查询任务状态和进度 |
| `POST` | `/api/v1/jobs/{job_id}/retry` | 重试任务 |
| `GET` | `/api/v1/jobs/{job_id}/audio` | 下载成品；`stem` 可选 output、instrumental、vocals |

## 常见状态码

| 状态码 | 含义 |
| --- | --- |
| `200` | 请求成功 |
| `201` | 音频上传成功 |
| `202` | 任务已加入推理队列 |
| `401` | API Key 缺失或错误 |
| `404` | 模型、任务、文件或 upload_id 不存在 |
| `409` | 结果尚未生成，或当前状态不允许操作 |
| `415` | 文件格式不受支持 |
| `422` | 请求字段或参数组合无效 |

## 文件与清理

API 不设置上传大小上限，接收内容时以固定小块流式写盘，不会把整份音频一次载入内存；实际容量只受数据目录所在磁盘的可用空间限制。上传文件保存在 XB-SVCB 当前数据目录的 `api/uploads` 下，并会随数据目录迁移。任务创建后请等推理结束再删除对应上传文件；不再使用时可调用删除接口清理。生成作品仍由 XB-SVCB 的“我的作品”统一管理。
