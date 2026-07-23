"""可由桌面端手动启停的 FastAPI 外部接入服务。"""

from __future__ import annotations

import secrets
import socket
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Literal, TYPE_CHECKING

import httpx
import uvicorn
from fastapi import (
    APIRouter,
    Body,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Path as ApiPath,
    Query,
    Security,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field

import config
from infrastructure.storage import SettingsStore

if TYPE_CHECKING:
    from .bridge import Api


UPLOAD_CHUNK_BYTES = 1024 * 1024
SUPPORTED_MEDIA_SUFFIXES = {
    ".aac",
    ".flac",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
    ".wma",
}


API_OVERVIEW_DESCRIPTION = r"""
服务由 XB-SVCB 软件内手动启动。除健康检查和接口文档外，所有 `/api/v1` 接口都需要
`X-API-Key` 请求头。API Key 可在软件的“资料库 -> API 接入”页面查看。

## 公共请求头

| 参数名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `X-API-Key` | string | 是 | API 接入页显示的密钥；`GET /health` 不需要 |

## 完整示例：生成一首 AI 翻唱

下面的程序会依次完成：检查服务、上传歌曲、读取模型、按当前环境创建任务、轮询进度、
下载最终混音并清理上传文件。若选择到的唯一模型是 SeedVC，还会自动上传 `reference.wav`。

先安装依赖：`pip install requests`

```python
import time
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8765"
API_KEY = "替换为软件 API 接入页显示的密钥"
SOURCE_AUDIO = Path("song.wav")
REFERENCE_AUDIO = Path("reference.wav")  # 只有 SeedVC 需要
OUTPUT_AUDIO = Path("cover.wav")
HEADERS = {"X-API-Key": API_KEY}


def upload(path: Path) -> str:
    with path.open("rb") as audio:
        response = requests.post(
            f"{BASE_URL}/api/v1/uploads",
            headers=HEADERS,
            files={"file": (path.name, audio)},
            timeout=None,
        )
    response.raise_for_status()
    return response.json()["upload_id"]


requests.get(f"{BASE_URL}/health", timeout=10).raise_for_status()
source_upload_id = upload(SOURCE_AUDIO)
reference_upload_id = None

try:
    response = requests.get(f"{BASE_URL}/api/v1/models", headers=HEADERS, timeout=30)
    response.raise_for_status()
    model_data = response.json()
    if not model_data["items"]:
        raise RuntimeError("软件内还没有导入声音模型")

    # 优先选择不需要参考音频的模型；只有 SeedVC 时再上传 reference.wav。
    model = next(
        (item for item in model_data["items"] if item["framework"] != "seed-vc"),
        model_data["items"][0],
    )
    payload = {
        "source_upload_id": source_upload_id,
        "model_id": model["id"],
        "title": "API 翻唱示例",
        "workflow": "auto_mix",
        "params": {
            "pitch": 0,
            "f0_method": "rmvpe",
            "device": "auto",
        },
    }
    if model["framework"] == "seed-vc":
        reference_upload_id = upload(REFERENCE_AUDIO)
        payload["reference_upload_id"] = reference_upload_id

    response = requests.post(
        f"{BASE_URL}/api/v1/jobs",
        headers=HEADERS,
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    job_id = response.json()["id"]

    while True:
        response = requests.get(
            f"{BASE_URL}/api/v1/jobs/{job_id}", headers=HEADERS, timeout=30
        )
        response.raise_for_status()
        job = response.json()
        print(f"{job['status']}: {job['progress']}%")
        if job["status"] in {"done", "failed"}:
            break
        time.sleep(2)

    if job["status"] == "failed":
        raise RuntimeError(job.get("error") or "翻唱任务失败")

    with requests.get(
        f"{BASE_URL}{job['result_url']}", headers=HEADERS, stream=True, timeout=None
    ) as response:
        response.raise_for_status()
        with OUTPUT_AUDIO.open("wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                if chunk:
                    output.write(chunk)
    print(f"生成完成：{OUTPUT_AUDIO.resolve()}")
finally:
    for upload_id in (source_upload_id, reference_upload_id):
        if upload_id:
            requests.delete(
                f"{BASE_URL}/api/v1/uploads/{upload_id}",
                headers=HEADERS,
                timeout=30,
            )
```

## 状态码

| 状态码 | 说明 |
| --- | --- |
| `200` | 请求成功 |
| `201` | 文件上传成功 |
| `202` | 任务已进入队列 |
| `401` | API Key 缺失或不正确 |
| `404` | 文件、模型或任务不存在 |
| `409` | 资源当前状态不允许操作 |
| `415` | 上传格式不受支持 |
| `422` | 请求参数或参数组合无效 |
"""


def _api_operation_description(
    summary: str,
    method: str,
    path: str,
    parameters: list[tuple[str, str, str, str, str]],
    response_fields: list[tuple[str, str, str]],
    response_example: str,
    *,
    auth: bool = True,
    request_example: str = "",
    request_example_language: str = "json",
    response_example_language: str = "json",
    note: str = "",
) -> str:
    """生成与 go-cqhttp 接口页一致的参数表和返回示例结构。"""

    lines = [
        f"> {summary}",
        "",
        f"method: `{method}`",
        "",
        f"path: `{path}`",
        "",
        f"鉴权: `{'X-API-Key' if auth else '无需鉴权'}`",
        "",
        "参数:",
        "",
        "| 参数名 | 类型 | 必填 | 默认值 | 说明 |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(f"| `{name}` | {kind} | {required} | {default} | {desc} |" for name, kind, required, default, desc in parameters)
    if request_example:
        lines.extend(
            [
                "",
                "请求示例:",
                "",
                f"```{request_example_language}",
                request_example.strip(),
                "```",
            ]
        )
    if note:
        lines.extend(["", f"> 注意：{note}"])
    lines.extend(
        [
            "",
            "返回:",
            "",
            f"```{response_example_language}",
            response_example.strip(),
            "```",
            "",
            "响应数据:",
            "",
            "| 字段名 | 类型 | 说明 |",
            "| --- | --- | --- |",
        ]
    )
    lines.extend(f"| `{name}` | {kind} | {desc} |" for name, kind, desc in response_fields)
    return "\n".join(lines)


NO_PARAMETERS = [("无", "-", "-", "-", "-")]

HEALTH_API_DOC = _api_operation_description(
    "检查 HTTP API 是否已经启动，并读取软件和接口版本。",
    "GET",
    "/health",
    NO_PARAMETERS,
    [
        ("ok", "boolean", "服务是否正常响应"),
        ("app", "string", "应用名称"),
        ("version", "string", "XB-SVCB 软件版本"),
        ("api_version", "string", "HTTP API 主版本"),
    ],
    '{"ok": true, "app": "XB-SVCB", "version": "0.0.23", "api_version": "v1"}',
    auth=False,
)

SYSTEM_API_DOC = _api_operation_description(
    "读取集成工具状态，以及五个隔离环境实际可使用的 GPU/CPU 推理后端。",
    "GET",
    "/api/v1/system",
    NO_PARAMETERS,
    [
        ("ready", "boolean", "系统状态是否完成读取"),
        ("tools", "array", "UVR、ffmpeg 和四种歌声模型引擎状态"),
        ("tools[].key", "string", "工具标识"),
        ("tools[].status", "string", "运行环境和当前设备说明"),
        ("tools[].ok", "boolean", "工具是否可正常使用"),
        ("inference_devices.preferred", "string", "综合首选后端"),
        ("inference_devices.options", "array", "API 可选择的设备选项"),
        ("inference_devices.frameworks", "object", "按框架列出的环境探测结果"),
    ],
    """
{
  "ready": true,
  "tools": [
    {
      "key": "uvr",
      "name": "Ultimate Vocal Remover",
      "desc": "人声 / 伴奏分离引擎",
      "version": "0.44.2",
      "status": "DirectML · AMD Radeon",
      "ok": true
    }
  ],
  "inference_devices": {
    "preferred": "directml",
    "options": [
      {"value": "auto", "label": "自动选择", "backend": "auto", "frameworks": ["uvr", "rvc"]}
    ],
    "frameworks": {
      "rvc": {
        "ok": true,
        "torch_version": "2.4.1+cpu",
        "backends": ["directml", "cpu"],
        "devices": [{"backend": "directml", "name": "AMD Radeon", "index": 0}],
        "preferred": "directml"
      }
    }
  }
}
""",
)

MODEL_LIST_API_DOC = _api_operation_description(
    "列出软件内已经导入的声音模型；不会返回模型文件的本机路径。",
    "GET",
    "/api/v1/models",
    NO_PARAMETERS,
    [
        ("items", "array", "声音模型列表"),
        ("items[].id", "string", "创建任务时使用的模型 ID"),
        ("items[].name", "string", "模型显示名称"),
        ("items[].framework", "string", "so-vits-svc、rvc、seed-vc 或 ddsp-svc"),
        ("items[].sample_rate", "string|null", "模型采样率显示值"),
        ("items[].size", "string|null", "模型文件总大小显示值"),
        ("items[].favorite", "boolean|null", "是否在软件内收藏"),
        ("items[].tags", "array|null", "模型标签"),
        ("total", "integer", "模型总数"),
        ("default_id", "string|null", "软件当前默认模型 ID"),
    ],
    """
{
  "items": [
    {
      "id": "model_rvc_demo",
      "name": "示例 RVC",
      "type": "RVC",
      "framework": "rvc",
      "sample_rate": "40 kHz",
      "size": "92 MB",
      "favorite": true,
      "tags": ["中文"]
    }
  ],
  "total": 1,
  "default_id": "model_rvc_demo"
}
""",
)

MODEL_GET_API_DOC = _api_operation_description(
    "按模型 ID 读取单个声音模型的公开信息。",
    "GET",
    "/api/v1/models/{model_id}",
    [("model_id", "string", "是", "-", "由模型列表接口的 items[].id 返回")],
    [
        ("id", "string", "模型 ID"),
        ("name", "string", "模型显示名称"),
        ("type", "string|null", "模型类型标签"),
        ("framework", "string|null", "模型推理框架"),
        ("sample_rate", "string|null", "模型采样率显示值"),
        ("size", "string|null", "模型文件总大小显示值"),
        ("favorite", "boolean|null", "是否收藏"),
        ("tags", "array|null", "模型标签"),
    ],
    """
{
  "id": "model_rvc_demo",
  "name": "示例 RVC",
  "type": "RVC",
  "framework": "rvc",
  "sample_rate": "40 kHz",
  "size": "92 MB",
  "favorite": true,
  "tags": ["中文"]
}
""",
)

UPLOAD_API_DOC = _api_operation_description(
    "以 multipart/form-data 流式上传源歌曲或 SeedVC 参考音频。",
    "POST",
    "/api/v1/uploads",
    [
        (
            "file",
            "file",
            "是",
            "-",
            "音频或媒体文件；支持 AAC、FLAC、M4A、MKV、MOV、MP3、MP4、OGG、OPUS、WAV、WEBM、WMA",
        )
    ],
    [
        ("upload_id", "string", "上传文件 ID，创建任务和清理文件时使用"),
        ("filename", "string", "原始文件名"),
        ("size", "integer", "已接收的文件字节数"),
    ],
    '{"upload_id": "0123456789abcdef0123456789abcdef", "filename": "song.wav", "size": 48203144}',
    request_example='curl -X POST "http://127.0.0.1:8765/api/v1/uploads" -H "X-API-Key: YOUR_KEY" -F "file=@song.wav"',
    request_example_language="bash",
    note="接口没有固定文件大小上限，实际容量取决于磁盘剩余空间；调用方应关闭请求超时或设置足够长的超时。",
)

UPLOAD_DELETE_API_DOC = _api_operation_description(
    "删除上传接口保存的临时文件。",
    "DELETE",
    "/api/v1/uploads/{upload_id}",
    [("upload_id", "string", "是", "-", "上传接口返回的 32 位文件 ID")],
    [("ok", "boolean", "是否删除成功"), ("upload_id", "string", "已删除的上传 ID")],
    '{"ok": true, "upload_id": "0123456789abcdef0123456789abcdef"}',
    note="任务完成前不要删除它正在使用的源音频或 SeedVC 参考音频。",
)

JOB_LIST_API_DOC = _api_operation_description(
    "读取最近的翻唱任务、处理状态、进度和结果下载地址。",
    "GET",
    "/api/v1/jobs",
    [("limit", "integer", "否", "50", "最多返回多少条任务，允许范围 1~200")],
    [
        ("items", "array", "任务列表"),
        ("items[].id", "string", "任务 ID"),
        ("items[].status", "string", "queue、running、done 或 failed"),
        ("items[].progress", "integer", "整体进度，范围 0~100"),
        ("items[].result_url", "string|null", "成品下载路径，任务完成前为 null"),
        ("total", "integer", "本次响应包含的任务数量"),
    ],
    """
{
  "items": [
    {
      "id": "wrk_demo",
      "title": "API 翻唱示例 (AI 翻唱)",
      "model": "示例 RVC",
      "model_id": "model_rvc_demo",
      "framework": "rvc",
      "status": "done",
      "progress": 100,
      "duration": "03:42",
      "format": "WAV",
      "size": "38 MB",
      "created_at": "2026-07-23T12:00:00",
      "error": null,
      "steps": [],
      "workflow": "auto_mix",
      "queue_position": null,
      "result_url": "/api/v1/jobs/wrk_demo/audio"
    }
  ],
  "total": 1
}
""",
)

JOB_CREATE_API_DOC = _api_operation_description(
    "使用已上传文件或运行软件电脑上的绝对路径创建单模型 AI 翻唱任务。",
    "POST",
    "/api/v1/jobs",
    [
        ("source_upload_id", "string|null", "条件必填", "null", "上传接口返回的源歌曲 ID；与 source_path 二选一"),
        ("source_path", "string|null", "条件必填", "null", "运行 XB-SVCB 电脑上的绝对路径；与 source_upload_id 二选一"),
        ("model_id", "string|null", "否", "null", "模型 ID；省略时使用 default_id"),
        ("title", "string|null", "否", "源文件名", "作品标题，最长 120 个字符"),
        ("workflow", "string", "否", "auto_mix", "auto_mix、auto_then_editor 或 full_manual_editor"),
        ("reference_upload_id", "string|null", "SeedVC 必填", "null", "SeedVC 目标音色参考音频的上传 ID"),
        ("params.pitch", "integer", "否", "0", "四种框架；半音偏移，范围 -12~12"),
        ("params.f0_method", "string", "否", "rmvpe", "SVC/RVC/DDSP；基频算法，SeedVC 忽略"),
        ("params.device", "string", "否", "auto", "auto、cuda、rocm、directml 或 cpu"),
        ("params.uvr_model", "string", "否", "软件默认值", "四种框架；UVR 分离模型文件名"),
        ("params.diffusion_ratio", "number", "否", "0.5", "SVC/SeedVC；范围 0~1，越大质量越高、速度越慢"),
        ("params.speaker", "string", "否", '""', "SVC/DDSP；目标说话人名称或 ID"),
        ("params.index_rate", "number", "否", "0.75", "仅 RVC；索引检索占比，范围 0~1"),
        ("params.rms_mix", "number", "否", "0.25", "仅 RVC；响度包络融合，范围 0~1"),
        ("params.protect", "number", "否", "0.33", "仅 RVC；清辅音保护，范围 0~0.5"),
        ("params.filter_radius", "integer", "否", "3", "仅 RVC；F0 中值滤波半径，范围 0~7"),
        ("params.rvc_version", "string", "否", "v2", "仅 RVC；必须与模型训练版本一致"),
        ("params.reference_audio", "string", "否", '""', "仅 SeedVC；本机参考音频绝对路径"),
        ("params.ddsp_infer_steps", "integer", "否", "50", "仅 DDSP；采样步数，最小 1，推荐 50~100"),
        ("params.ddsp_formant_shift", "number", "否", "0", "仅 DDSP；共振峰半音偏移，范围 -2~2"),
    ],
    [
        ("id", "string", "任务 ID，用于查询、重试和下载"),
        ("title", "string", "作品标题"),
        ("model", "string", "模型显示名称"),
        ("model_id", "string", "实际使用的模型 ID"),
        ("framework", "string|null", "实际推理框架"),
        ("status", "string", "新任务通常为 queue"),
        ("progress", "integer", "整体进度，范围 0~100"),
        ("steps", "array", "各处理步骤及状态"),
        ("queue_position", "integer|null", "排队位置"),
        ("result_url", "string|null", "任务完成前为 null"),
    ],
    """
{
  "id": "wrk_demo",
  "title": "API 翻唱示例 (AI 翻唱)",
  "model": "示例 RVC",
  "model_id": "model_rvc_demo",
  "framework": "rvc",
  "status": "queue",
  "progress": 0,
  "duration": null,
  "format": null,
  "size": null,
  "created_at": "2026-07-23T12:00:00",
  "error": null,
  "steps": [],
  "workflow": "auto_mix",
  "queue_position": 1,
  "result_url": null
}
""",
    request_example="""
{
  "source_upload_id": "0123456789abcdef0123456789abcdef",
  "model_id": "model_rvc_demo",
  "title": "API 翻唱示例",
  "workflow": "auto_mix",
  "params": {
    "pitch": 0,
    "f0_method": "rmvpe",
    "device": "auto",
    "index_rate": 0.75,
    "rms_mix": 0.25,
    "protect": 0.33,
    "filter_radius": 3,
    "rvc_version": "v2"
  }
}
""",
    note="source_upload_id 与 source_path 必须且只能提供一个。params 中不适用于所选框架的字段会被忽略。",
)

QUEUE_API_DOC = _api_operation_description(
    "读取当前推理队列。",
    "GET",
    "/api/v1/jobs/queue",
    NO_PARAMETERS,
    [
        ("running", "boolean", "当前是否有任务正在执行"),
        ("pending", "array", "等待执行的任务 ID 列表"),
        ("size", "integer", "等待任务数量，不包含正在执行的任务"),
    ],
    '{"running": true, "pending": ["wrk_next"], "size": 1}',
)

JOB_GET_API_DOC = _api_operation_description(
    "按任务 ID 查询排队位置、处理步骤、进度、错误和下载地址。",
    "GET",
    "/api/v1/jobs/{job_id}",
    [("job_id", "string", "是", "-", "创建任务接口返回的任务 ID")],
    [
        ("id", "string", "任务 ID"),
        ("status", "string", "queue、running、done 或 failed"),
        ("progress", "integer", "整体进度，范围 0~100"),
        ("error", "string|null", "任务失败原因"),
        ("steps", "array", "各处理步骤及状态"),
        ("queue_position", "integer|null", "排队位置"),
        ("result_url", "string|null", "成品下载路径，完成前为 null"),
    ],
    """
{
  "id": "wrk_demo",
  "title": "API 翻唱示例 (AI 翻唱)",
  "model": "示例 RVC",
  "model_id": "model_rvc_demo",
  "framework": "rvc",
  "status": "running",
  "progress": 52,
  "duration": null,
  "format": null,
  "size": null,
  "created_at": "2026-07-23T12:00:00",
  "error": null,
  "steps": [{"key": "convert", "label": "声音转换", "status": "active"}],
  "workflow": "auto_mix",
  "queue_position": null,
  "result_url": null
}
""",
)

JOB_RETRY_API_DOC = _api_operation_description(
    "将允许重试的失败任务重新加入推理队列；任务 ID 不变。",
    "POST",
    "/api/v1/jobs/{job_id}/retry",
    [("job_id", "string", "是", "-", "需要重新执行的失败任务 ID")],
    [("ok", "boolean", "是否已重新加入队列"), ("job_id", "string", "被重试的任务 ID")],
    '{"ok": true, "job_id": "wrk_demo"}',
)

JOB_AUDIO_API_DOC = _api_operation_description(
    "下载最终成品、UVR 伴奏或转换后人声。",
    "GET",
    "/api/v1/jobs/{job_id}/audio",
    [
        ("job_id", "string", "是", "-", "已创建的翻唱任务 ID"),
        ("stem", "string", "否", "output", "output、instrumental 或 vocals"),
    ],
    [
        ("响应体", "binary", "音频文件二进制内容"),
        ("Content-Type", "header", "audio/wav、audio/mpeg、audio/flac 等实际格式"),
        ("Content-Disposition", "header", "建议的下载文件名"),
    ],
    "<binary audio data>",
    response_example_language="text",
    note="output 是最终伴奏混音，instrumental 是 UVR 分离出的伴奏，vocals 是模型转换后、尚未混音的人声。",
)


class InferenceParamsRequest(BaseModel):
    """四种歌声模型共用的推理参数；各框架只读取自己的字段。"""

    model_config = ConfigDict(extra="forbid")

    pitch: int = Field(
        default=0,
        ge=-12,
        le=12,
        description=(
            "整体音高偏移，单位为半音，四种框架均适用。正数升调、负数降调；"
            "常用范围 -12~12，例如男声转女声可尝试 +12，女声转男声可尝试 -12。"
        ),
        examples=[0, 12, -12],
    )
    f0_method: Literal[
        "rmvpe", "crepe", "harvest", "pm", "fcpe", "dio", "parselmouth"
    ] = Field(
        default="rmvpe",
        description=(
            "基频/F0 提取算法，适用于 So-VITS-SVC、RVC 和 DDSP-SVC，SeedVC 忽略。"
            "推荐 rmvpe；还可使用 crepe、harvest、pm。DDSP-SVC 另支持 fcpe、dio、"
            "parselmouth，其中 pm 会自动转换为 parselmouth。算法必须已被对应隔离环境支持。"
        ),
        examples=["rmvpe"],
    )
    device: Literal["auto", "cuda", "rocm", "directml", "cpu"] = Field(
        default="auto",
        description=(
            "UVR 分离与歌声模型使用的推理设备。auto 按当前隔离环境自动选择；"
            "cuda 为 NVIDIA，rocm 为 AMD ROCm，directml 为 Windows AMD，cpu 为处理器。"
            "显式选择不可用后端时任务会失败，不会静默回退。DDSP-SVC 在 Windows AMD "
            "环境会使用 CPU 稳定路径。"
        ),
    )
    uvr_model: str = Field(
        default=config.UVR_SEP_MODEL,
        description=(
            "UVR 人声/伴奏分离模型文件名，文件应位于软件的 models/uvr 目录。"
            "名称不存在时回退到软件默认分离模型。该参数影响所有框架推理前的分离阶段。"
        ),
        examples=[config.UVR_SEP_MODEL],
    )
    diffusion_ratio: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "扩散强度/质量比例，范围 0~1。So-VITS-SVC 映射为 1~200 个浅扩散步骤；"
            "SeedVC 映射为 10~50 个扩散步骤，值越大通常质量更高、速度更慢。"
            "RVC 和 DDSP-SVC 忽略此字段。"
        ),
    )
    speaker: str = Field(
        default="",
        description=(
            "目标说话人名称或 ID。So-VITS-SVC 留空时使用模型配置中的第一个说话人；"
            "DDSP-SVC 留空时使用说话人 1。RVC 和 SeedVC 忽略。"
        ),
        examples=["1"],
    )
    index_rate: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description=(
            "RVC 特征索引检索占比，范围 0~1，仅在模型带 .index 文件时有效。"
            "0 禁用索引，值越大越贴近目标音色，但过高可能增加金属感或检索噪声。"
        ),
    )
    rms_mix: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description=(
            "RVC 输出与原始人声音量包络的融合比例，范围 0~1。较小值更多保留原歌曲"
            "的响度起伏，较大值更多保留转换结果自身的响度；默认 0.25。"
        ),
    )
    protect: float = Field(
        default=0.33,
        ge=0.0,
        le=0.5,
        description=(
            "RVC 清辅音和呼吸保护强度，范围 0~0.5。较小值更贴近目标音色；"
            "较大值更多保留原声辅音、齿音和呼吸，通常可减少破音。"
        ),
    )
    filter_radius: int = Field(
        default=3,
        ge=0,
        le=7,
        description=(
            "RVC F0 中值滤波半径，范围 0~7。0 表示不滤波；3 或更高可降低 harvest "
            "等算法产生的呼吸杂音，对部分 F0 算法可能没有明显影响。"
        ),
    )
    rvc_version: Literal["v1", "v2"] = Field(
        default="v2",
        description=(
            "RVC 网络版本，必须与导入的模型训练版本一致。当前大多数新模型使用 v2；"
            "版本选错可能导致维度不匹配或音质异常。"
        ),
    )
    reference_audio: str = Field(
        default="",
        description=(
            "SeedVC 目标音色参考音频在运行 XB-SVCB 电脑上的绝对路径。远程调用推荐"
            "先上传参考音频并使用外层 reference_upload_id；提供 reference_upload_id 时会"
            "覆盖本字段。其他框架忽略。"
        ),
        examples=[r"D:\voice\reference.wav"],
    )
    ddsp_infer_steps: int = Field(
        default=50,
        ge=1,
        description=(
            "DDSP-SVC Rectified Flow 采样步数，仅 DDSP-SVC 使用。推荐 50~100；"
            "值越大通常更细致但推理更慢。若低于模型配置的推荐步数，运行时会自动提升。"
        ),
    )
    ddsp_formant_shift: float = Field(
        default=0.0,
        ge=-2.0,
        le=2.0,
        description=(
            "DDSP-SVC 共振峰偏移，单位为半音，范围 -2~2。负值通常更厚、更暗，"
            "正值通常更薄、更亮；只对使用 pitch augmentation 训练的模型有效。"
        ),
    )


class JobCreateRequest(BaseModel):
    """创建单模型翻唱任务。上传 ID 与本机路径必须且只能提供一个。"""

    model_config = ConfigDict(extra="forbid")

    source_upload_id: str | None = Field(
        default=None,
        description=(
            "源歌曲的上传 ID，由 POST /api/v1/uploads 返回。适合外部或局域网调用；"
            "与 source_path 必须且只能提供一个。"
        ),
        examples=["0123456789abcdef0123456789abcdef"],
    )
    source_path: str | None = Field(
        default=None,
        description=(
            "源歌曲在运行 XB-SVCB 电脑上的绝对路径，只适合同机程序或共享磁盘；"
            "与 source_upload_id 必须且只能提供一个。"
        ),
        examples=[r"D:\music\song.wav"],
    )
    model_id: str | None = Field(
        default=None,
        description=(
            "声音模型 ID，可从 GET /api/v1/models 获取。省略或为 null 时使用"
            "该接口返回的 default_id；没有默认模型时请求失败。"
        ),
    )
    title: str | None = Field(
        default=None,
        max_length=120,
        description="作品标题，最长 120 个字符。省略时使用源文件名，软件会追加“(AI 翻唱)”。",
    )
    workflow: Literal[
        "auto_mix", "auto_then_editor", "full_manual_editor"
    ] = Field(
        default="auto_mix",
        description=(
            "生成后处理流程：auto_mix 完成分离、转换和伴奏混音；auto_then_editor "
            "完成自动生成后可进入编辑器；full_manual_editor 创建全手动编辑流程。"
            "HTTP API 当前创建单模型任务，不提供多模型人声合并工作流。"
        ),
    )
    reference_upload_id: str | None = Field(
        default=None,
        description=(
            "SeedVC 目标音色参考音频的 upload_id，同样由上传接口取得。SeedVC 必填；"
            "其他框架忽略。提供后会覆盖 params.reference_audio。"
        ),
    )
    params: InferenceParamsRequest = Field(
        default_factory=InferenceParamsRequest,
        description="推理参数。展开此对象可查看每个字段的作用、范围、默认值和适用框架。",
    )


class RetryResponse(BaseModel):
    ok: bool = Field(description="是否已成功重新加入推理队列")
    job_id: str = Field(description="被重试的任务 ID")


class HealthResponse(BaseModel):
    ok: bool = Field(description="服务是否正常响应")
    app: str = Field(description="应用名称")
    version: str = Field(description="XB-SVCB 软件版本")
    api_version: str = Field(description="HTTP API 版本")


class UploadResponse(BaseModel):
    upload_id: str = Field(description="上传文件 ID，创建任务或删除上传时使用")
    filename: str = Field(description="原始文件名，仅保留文件名部分")
    size: int = Field(description="已接收的文件字节数")


class DeleteUploadResponse(BaseModel):
    ok: bool = Field(description="是否删除成功")
    upload_id: str = Field(description="已删除的上传 ID")


class ModelResponse(BaseModel):
    id: str = Field(description="模型 ID，创建任务时传入 model_id")
    name: str = Field(description="模型显示名称")
    type: str | None = Field(default=None, description="模型类型标签")
    framework: str | None = Field(
        default=None,
        description="推理框架：so-vits-svc、rvc、seed-vc 或 ddsp-svc",
    )
    sample_rate: str | None = Field(default=None, description="模型采样率显示值")
    size: str | None = Field(default=None, description="模型文件总大小显示值")
    favorite: bool | None = Field(default=None, description="是否在软件内收藏")
    tags: list[str] | None = Field(default=None, description="模型标签")


class ModelListResponse(BaseModel):
    items: list[ModelResponse] = Field(description="可用于创建任务的模型列表")
    total: int = Field(description="模型总数")
    default_id: str | None = Field(description="软件当前默认模型 ID，未设置时为 null")


class PipelineStepResponse(BaseModel):
    key: str = Field(description="流水线步骤标识")
    label: str = Field(description="步骤显示名称")
    status: Literal["wait", "active", "done", "failed"] = Field(
        description="步骤状态：等待、执行中、完成或失败"
    )


class JobResponse(BaseModel):
    id: str = Field(description="任务 ID，用于查询、重试和下载")
    title: str = Field(description="作品标题")
    model: str = Field(description="模型显示名称")
    model_id: str = Field(description="使用的模型 ID")
    framework: str | None = Field(default=None, description="实际推理框架")
    status: Literal["queue", "running", "done", "failed"] = Field(
        description="任务状态：排队、处理中、完成或失败"
    )
    progress: int = Field(description="整体进度百分比，范围 0~100")
    duration: str | None = Field(default=None, description="生成音频时长显示值")
    format: str | None = Field(default=None, description="生成音频格式显示值")
    size: str | None = Field(default=None, description="生成文件大小显示值")
    created_at: str = Field(description="任务创建时间，ISO 8601 本地时间")
    error: str | None = Field(default=None, description="失败原因，非失败任务通常为 null")
    steps: list[PipelineStepResponse] = Field(description="各处理步骤及状态")
    workflow: str | None = Field(default=None, description="任务后处理流程")
    queue_position: int | None = Field(default=None, description="排队位置；未排队时可能为 null")
    result_url: str | None = Field(
        default=None,
        description="任务完成后的成品下载路径；未完成时为 null",
    )


class JobListResponse(BaseModel):
    items: list[JobResponse] = Field(description="按软件作品列表顺序返回的任务")
    total: int = Field(description="本次响应包含的任务数量")


class QueueResponse(BaseModel):
    running: bool = Field(description="当前是否有任务正在执行")
    pending: list[str] = Field(description="等待执行的任务 ID 列表")
    size: int = Field(description="等待执行的任务数量，不包含正在执行的任务")


class ToolStatusResponse(BaseModel):
    key: str = Field(description="集成工具标识")
    name: str = Field(description="集成工具显示名称")
    desc: str = Field(description="该工具在翻唱流程中的用途")
    version: str = Field(description="已检测到的版本；未安装时显示“未安装”")
    status: str = Field(description="当前运行环境和设备状态说明")
    ok: bool = Field(description="该工具是否可正常使用")


class InferenceDeviceItemResponse(BaseModel):
    backend: Literal["cuda", "rocm", "directml", "cpu"] = Field(
        description="设备后端：NVIDIA CUDA、AMD ROCm、Windows AMD DirectML 或 CPU"
    )
    name: str = Field(description="显卡或处理器设备名称")
    index: int = Field(description="设备在当前推理环境中的索引")


class InferenceDeviceRuntimeResponse(BaseModel):
    ok: bool = Field(description="该框架隔离环境是否探测成功")
    torch_version: str = Field(description="该框架隔离环境中的 PyTorch 版本")
    backends: list[Literal["cuda", "rocm", "directml", "cpu"]] = Field(
        description="该框架当前可使用的推理后端"
    )
    devices: list[InferenceDeviceItemResponse] = Field(description="已探测到的加速设备")
    preferred: Literal["cuda", "rocm", "directml", "cpu"] = Field(
        description="auto 模式为该框架优先选择的后端"
    )
    error: str | None = Field(default=None, description="环境探测失败原因；成功时为 null")
    note: str | None = Field(default=None, description="框架特定的设备兼容说明；没有时为 null")


class InferenceDeviceOptionResponse(BaseModel):
    value: Literal["auto", "cuda", "rocm", "directml", "cpu"] = Field(
        description="提交 params.device 时使用的值"
    )
    label: str = Field(description="设备选项显示名称")
    backend: Literal["auto", "cuda", "rocm", "directml", "cpu"] = Field(
        description="该选项对应的推理后端"
    )
    name: str | None = Field(default=None, description="探测到的设备名称；可能为空")
    frameworks: list[str] = Field(description="当前支持该设备选项的模型框架")


class InferenceDeviceCapabilitiesResponse(BaseModel):
    preferred: Literal["cuda", "rocm", "directml", "cpu"] = Field(
        description="所有框架综合后的首选 GPU 后端；无可用 GPU 时为 cpu"
    )
    options: list[InferenceDeviceOptionResponse] = Field(
        description="前端和 API 可选择的设备选项"
    )
    frameworks: dict[str, InferenceDeviceRuntimeResponse] = Field(
        description="按 uvr、so-vits-svc、rvc、seed-vc、ddsp-svc 列出的环境探测结果"
    )


class SystemResponse(BaseModel):
    ready: bool = Field(description="系统状态信息是否已完成读取")
    tools: list[ToolStatusResponse] = Field(description="各集成工具及模型引擎状态")
    inference_devices: InferenceDeviceCapabilitiesResponse | None = Field(
        default=None,
        description="各隔离环境可用的 CUDA、ROCm、DirectML 和 CPU 推理能力",
    )


class ErrorResponse(BaseModel):
    detail: str | list[dict[str, Any]] = Field(
        description="错误原因；请求格式校验失败时为字段错误列表"
    )


def _public_model(item: dict[str, Any]) -> dict[str, Any]:
    """移除本机模型文件路径，仅保留外部调用需要的模型信息。"""
    return {
        key: item.get(key)
        for key in (
            "id",
            "name",
            "type",
            "framework",
            "sample_rate",
            "size",
            "favorite",
            "tags",
        )
    }


def _public_work(item: dict[str, Any], base_path: str = "/api/v1") -> dict[str, Any]:
    """将作品记录投影成稳定的 HTTP DTO，避免泄露内部文件与模型路径。"""
    work_id = str(item.get("id") or "")
    result = {
        key: item.get(key)
        for key in (
            "id",
            "title",
            "model",
            "model_id",
            "framework",
            "status",
            "progress",
            "duration",
            "format",
            "size",
            "created_at",
            "error",
            "steps",
            "workflow",
            "queue_position",
        )
    }
    result["result_url"] = (
        f"{base_path}/jobs/{work_id}/audio" if item.get("status") == "done" else None
    )
    return result


def _content_type(path: Path) -> str:
    return {
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".wav": "audio/wav",
    }.get(path.suffix.lower(), "application/octet-stream")


def _resolve_upload(upload_id: str) -> Path:
    normalized = (upload_id or "").strip().lower()
    if len(normalized) != 32 or any(c not in "0123456789abcdef" for c in normalized):
        raise HTTPException(status_code=422, detail="upload_id 格式无效")
    matches = list(config.API_UPLOADS_DIR.glob(f"{normalized}.*"))
    if len(matches) != 1 or not matches[0].is_file():
        raise HTTPException(status_code=404, detail="上传文件不存在或已删除")
    return matches[0]


def create_http_app(facade: "Api", api_key: str) -> FastAPI:
    """构建 HTTP 应用；与桌面桥复用同一个业务服务实例。"""
    app = FastAPI(
        title="XB-SVCB API",
        summary="XB-SVCB AI 翻唱外部接入接口",
        description=API_OVERVIEW_DESCRIPTION,
        version=config.APP_VERSION,
        openapi_tags=[
            {"name": "服务", "description": "健康检查、集成工具状态和当前 GPU 推理环境。"},
            {"name": "模型", "description": "读取 XB-SVCB 中已经导入的声音模型。"},
            {
                "name": "音频",
                "description": "上传源歌曲或参考音频，以及下载任务生成的音频。上传不限制文件大小。",
            },
            {"name": "任务", "description": "创建、查询和重试单模型 AI 翻唱任务。"},
        ],
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def require_api_key(value: str | None = Security(api_key_header)) -> None:
        if not value or not secrets.compare_digest(value, api_key):
            raise HTTPException(status_code=401, detail="API Key 无效")

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["服务"],
        summary="检查 API 服务",
        description=HEALTH_API_DOC,
    )
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "app": config.APP_NAME,
            "version": config.APP_VERSION,
            "api_version": "v1",
        }

    router = APIRouter(
        prefix="/api/v1",
        dependencies=[Depends(require_api_key)],
        responses={
            401: {
                "model": ErrorResponse,
                "description": "未提供 X-API-Key，或 API Key 不正确",
            }
        },
    )

    @router.get(
        "/system",
        response_model=SystemResponse,
        tags=["服务"],
        summary="读取系统和推理环境",
        description=SYSTEM_API_DOC,
    )
    def system_status() -> dict[str, Any]:
        return facade.get_system_status()

    @router.get(
        "/models",
        response_model=ModelListResponse,
        tags=["模型"],
        summary="列出声音模型",
        description=MODEL_LIST_API_DOC,
    )
    def list_models() -> dict[str, Any]:
        items = [_public_model(item) for item in facade.list_models()]
        return {"items": items, "total": len(items), "default_id": facade.get_default_model()}

    @router.get(
        "/models/{model_id}",
        response_model=ModelResponse,
        tags=["模型"],
        summary="读取单个声音模型",
        description=MODEL_GET_API_DOC,
        responses={404: {"model": ErrorResponse, "description": "模型 ID 不存在"}},
    )
    def get_model(
        model_id: str = ApiPath(
            ...,
            description="声音模型 ID，由 GET /api/v1/models 的 items[].id 返回",
            examples=["model_0123456789abcdef"],
        )
    ) -> dict[str, Any]:
        item = facade._models.get(model_id)
        if not item:
            raise HTTPException(status_code=404, detail="模型不存在")
        return _public_model(item)

    @router.post(
        "/uploads",
        response_model=UploadResponse,
        status_code=201,
        tags=["音频"],
        summary="上传音频或媒体文件",
        description=UPLOAD_API_DOC,
        responses={
            415: {"model": ErrorResponse, "description": "文件扩展名不受支持"},
        },
    )
    async def upload_audio(
        file: UploadFile = File(
            ...,
            description=(
                "源歌曲或 SeedVC 参考音频文件。支持 AAC、FLAC、M4A、MKV、MOV、MP3、MP4、"
                "OGG、OPUS、WAV、WEBM、WMA；不限制文件大小。"
            ),
        )
    ) -> dict[str, Any]:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in SUPPORTED_MEDIA_SUFFIXES:
            raise HTTPException(status_code=415, detail="不支持的音频或媒体格式")
        config.API_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        upload_id = uuid.uuid4().hex
        target = config.API_UPLOADS_DIR / f"{upload_id}{suffix}"
        total = 0
        try:
            with target.open("xb") as output:
                while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                    total += len(chunk)
                    output.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
        return {
            "upload_id": upload_id,
            "filename": Path(file.filename or target.name).name,
            "size": total,
        }

    @router.delete(
        "/uploads/{upload_id}",
        response_model=DeleteUploadResponse,
        tags=["音频"],
        summary="删除已上传文件",
        description=UPLOAD_DELETE_API_DOC,
        responses={
            404: {"model": ErrorResponse, "description": "上传文件不存在或已删除"},
            409: {"model": ErrorResponse, "description": "文件被占用或操作系统拒绝删除"},
        },
    )
    def delete_upload(
        upload_id: str = ApiPath(
            ...,
            description="上传文件 ID，由 POST /api/v1/uploads 返回",
            min_length=32,
            max_length=32,
            examples=["0123456789abcdef0123456789abcdef"],
        )
    ) -> dict[str, Any]:
        path = _resolve_upload(upload_id)
        try:
            path.unlink()
        except OSError as exc:
            raise HTTPException(status_code=409, detail=f"无法删除上传文件：{exc}") from exc
        return {"ok": True, "upload_id": upload_id}

    @router.get(
        "/jobs",
        response_model=JobListResponse,
        tags=["任务"],
        summary="列出翻唱任务",
        description=JOB_LIST_API_DOC,
    )
    def list_jobs(
        limit: int = Query(
            default=50,
            ge=1,
            le=200,
            description="最多返回多少条任务，默认 50，允许范围 1~200",
        )
    ) -> dict[str, Any]:
        items = [_public_work(item) for item in facade.list_works()[:limit]]
        return {"items": items, "total": len(items)}

    @router.post(
        "/jobs",
        response_model=JobResponse,
        status_code=202,
        tags=["任务"],
        summary="创建 AI 翻唱任务",
        description=JOB_CREATE_API_DOC,
        responses={
            404: {"model": ErrorResponse, "description": "源文件或模型不存在"},
        },
    )
    def create_job(
        request: JobCreateRequest = Body(
            ...,
            description=(
                "任务来源、模型、工作流与推理参数。source_upload_id 和 source_path 必须且只能提供一个。"
            ),
        )
    ) -> dict[str, Any]:
        if bool(request.source_upload_id) == bool(request.source_path):
            raise HTTPException(
                status_code=422,
                detail="source_upload_id 与 source_path 必须且只能提供一个",
            )
        if request.source_upload_id:
            source = _resolve_upload(request.source_upload_id)
        else:
            try:
                source = Path(str(request.source_path)).expanduser().resolve()
            except OSError as exc:
                raise HTTPException(status_code=422, detail="source_path 无效") from exc
            if not source.is_file():
                raise HTTPException(status_code=404, detail="source_path 指向的文件不存在")

        model_id = request.model_id or facade.get_default_model()
        if not model_id or not facade._models.get(model_id):
            raise HTTPException(status_code=404, detail="未找到可用模型，请提供有效 model_id")

        params = request.params.model_dump()
        if request.reference_upload_id:
            params["reference_audio"] = str(_resolve_upload(request.reference_upload_id))
        model = facade._models.get(model_id) or {}
        if str(model.get("framework") or "") == "seed-vc" and not params.get("reference_audio"):
            raise HTTPException(
                status_code=422,
                detail="SeedVC 任务需要 reference_upload_id 或 params.reference_audio",
            )

        payload = {
            "source_path": str(source),
            "model_id": model_id,
            "title": request.title or source.stem,
            "workflow": request.workflow,
            "params": params,
        }
        return _public_work(facade.create_work(payload))

    @router.get(
        "/jobs/queue",
        response_model=QueueResponse,
        tags=["任务"],
        summary="读取推理队列",
        description=QUEUE_API_DOC,
    )
    def queue_status() -> dict[str, Any]:
        return facade.get_inference_queue()

    @router.get(
        "/jobs/{job_id}",
        response_model=JobResponse,
        tags=["任务"],
        summary="读取翻唱任务",
        description=JOB_GET_API_DOC,
        responses={404: {"model": ErrorResponse, "description": "任务 ID 不存在"}},
    )
    def get_job(
        job_id: str = ApiPath(
            ...,
            description="翻唱任务 ID，由 POST /api/v1/jobs 返回",
            examples=["wrk_0123456789abcdef"],
        )
    ) -> dict[str, Any]:
        item = facade.get_work(job_id)
        if not item:
            raise HTTPException(status_code=404, detail="任务不存在")
        return _public_work(item)

    @router.post(
        "/jobs/{job_id}/retry",
        response_model=RetryResponse,
        tags=["任务"],
        summary="重试失败任务",
        description=JOB_RETRY_API_DOC,
        responses={
            404: {"model": ErrorResponse, "description": "任务 ID 不存在"},
            409: {"model": ErrorResponse, "description": "任务当前状态不允许重试"},
        },
    )
    def retry_job(
        job_id: str = ApiPath(
            ...,
            description="需要重新执行的失败任务 ID",
            examples=["wrk_0123456789abcdef"],
        )
    ) -> RetryResponse:
        if not facade.get_work(job_id):
            raise HTTPException(status_code=404, detail="任务不存在")
        if not facade.retry_work(job_id):
            raise HTTPException(status_code=409, detail="任务无法重试")
        return RetryResponse(ok=True, job_id=job_id)

    @router.get(
        "/jobs/{job_id}/audio",
        response_class=FileResponse,
        tags=["音频"],
        summary="下载任务音频",
        description=JOB_AUDIO_API_DOC,
        responses={
            200: {
                "description": "音频文件二进制内容",
                "content": {
                    "audio/wav": {"schema": {"type": "string", "format": "binary"}},
                    "audio/mpeg": {"schema": {"type": "string", "format": "binary"}},
                    "audio/flac": {"schema": {"type": "string", "format": "binary"}},
                },
            },
            404: {"model": ErrorResponse, "description": "任务 ID 不存在"},
            409: {"model": ErrorResponse, "description": "请求的音频尚未生成"},
        },
    )
    def download_audio(
        job_id: str = ApiPath(
            ...,
            description="已创建的翻唱任务 ID",
            examples=["wrk_0123456789abcdef"],
        ),
        stem: Literal["output", "instrumental", "vocals"] = Query(
            default="output",
            description=(
                "下载内容：output 为最终伴奏混音成品，instrumental 为 UVR 分离出的伴奏，"
                "vocals 为声音模型转换后、尚未与伴奏混合的人声"
            ),
        ),
    ) -> FileResponse:
        work = facade.get_work(job_id)
        if not work:
            raise HTTPException(status_code=404, detail="任务不存在")
        path = facade._stem_path(job_id, stem)
        if not path or not path.is_file():
            raise HTTPException(status_code=409, detail="请求的音频尚未生成")
        filename = f"{job_id}_{stem}{path.suffix.lower()}"
        return FileResponse(path, media_type=_content_type(path), filename=filename)

    app.include_router(router)
    return app


class HttpApiServer:
    """在当前 GUI 进程的后台线程运行 Uvicorn，不创建控制台子进程。"""

    SETTINGS_KEY = "http_api"

    def __init__(self, facade: "Api", settings: SettingsStore) -> None:
        self._facade = facade
        self._settings = settings
        self._lock = threading.RLock()
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._last_error = ""
        self._ensure_config()

    def _ensure_config(self) -> dict[str, Any]:
        current = self._settings.get(self.SETTINGS_KEY, {}) or {}
        scope = current.get("scope") if current.get("scope") in ("local", "lan") else "local"
        try:
            port = int(current.get("port", 8765))
        except (TypeError, ValueError):
            port = 8765
        if not 1024 <= port <= 65535:
            port = 8765
        api_key = str(current.get("api_key") or "")
        if len(api_key) < 16:
            api_key = secrets.token_urlsafe(32)
        normalized = {"scope": scope, "port": port, "api_key": api_key}
        if normalized != current:
            self._settings.set(self.SETTINGS_KEY, normalized)
        return normalized

    def configure(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            if self._is_running():
                return {**self.status(), "ok": False, "error": "请先停止 API 服务再修改配置"}
            payload = payload or {}
            current = self._ensure_config()
            scope = str(payload.get("scope", current["scope"]))
            if scope not in ("local", "lan"):
                return {**self.status(), "ok": False, "error": "监听范围只能是 local 或 lan"}
            try:
                port = int(payload.get("port", current["port"]))
            except (TypeError, ValueError):
                port = 0
            if not 1024 <= port <= 65535:
                return {**self.status(), "ok": False, "error": "端口必须在 1024 到 65535 之间"}
            updated = {**current, "scope": scope, "port": port}
            self._settings.set(self.SETTINGS_KEY, updated)
            return {**self.status(), "ok": True}

    def regenerate_key(self) -> dict[str, Any]:
        with self._lock:
            if self._is_running():
                return {**self.status(), "ok": False, "error": "请先停止 API 服务再更新密钥"}
            current = self._ensure_config()
            current["api_key"] = secrets.token_urlsafe(32)
            self._settings.set(self.SETTINGS_KEY, current)
            return {**self.status(), "ok": True}

    def start(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            if self._is_running():
                return {**self.status(), "ok": True, "message": "API 服务已在运行"}
            if payload:
                configured = self.configure(payload)
                if not configured.get("ok"):
                    return configured
            current = self._ensure_config()
            host = "0.0.0.0" if current["scope"] == "lan" else "127.0.0.1"
            port = int(current["port"])
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.bind((host, port))
            except OSError as exc:
                self._last_error = f"端口 {port} 无法使用：{exc}"
                return {**self.status(), "ok": False, "error": self._last_error}

            app = create_http_app(self._facade, current["api_key"])
            uvicorn_config = uvicorn.Config(
                app,
                host=host,
                port=port,
                log_level="warning",
                access_log=False,
                log_config=None,
                lifespan="on",
            )
            self._server = uvicorn.Server(uvicorn_config)
            self._last_error = ""
            self._thread = threading.Thread(
                target=self._run,
                name="xb-fastapi",
                daemon=True,
            )
            self._thread.start()

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            with self._lock:
                if self._server and self._server.started:
                    return {**self.status(), "ok": True, "message": "API 服务已启动"}
                if not self._thread or not self._thread.is_alive():
                    break
            time.sleep(0.05)
        with self._lock:
            if not self._last_error:
                self._last_error = "API 服务启动超时"
            self._request_stop()
            return {**self.status(), "ok": False, "error": self._last_error}

    def _run(self) -> None:
        server = self._server
        if not server:
            return
        try:
            server.run()
        except Exception as exc:  # noqa: BLE001 - 转为可在桌面页显示的启动错误
            with self._lock:
                self._last_error = f"API 服务异常退出：{exc}"

    def stop(self) -> dict[str, Any]:
        with self._lock:
            thread = self._thread
            thread_alive = bool(thread and thread.is_alive())
            if not self._is_running() and not thread_alive:
                self._server = None
                self._thread = None
                return {**self.status(), "ok": True, "message": "API 服务已停止"}
            self._request_stop()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        with self._lock:
            if thread and thread.is_alive() and self._server:
                self._server.force_exit = True
                thread.join(timeout=1.0)
            stopped = not thread or not thread.is_alive()
            if stopped:
                self._server = None
                self._thread = None
            return {
                **self.status(),
                "ok": stopped,
                "message": "API 服务已停止" if stopped else "API 服务停止超时",
                **({} if stopped else {"error": "API 服务停止超时"}),
            }

    def _request_stop(self) -> None:
        if self._server:
            self._server.should_exit = True

    def test(self) -> dict[str, Any]:
        status = self.status()
        if not status["running"]:
            return {"ok": False, "error": "请先启动 API 服务"}
        started = time.perf_counter()
        try:
            response = httpx.get(
                f"http://127.0.0.1:{status['port']}/api/v1/models",
                headers={"X-API-Key": status["api_key"]},
                timeout=5.0,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001 - 返回给前端显示诊断信息
            return {"ok": False, "error": f"连通性测试失败：{exc}"}
        return {
            "ok": True,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "model_count": int(data.get("total", 0)),
            "message": "API 鉴权与模型接口调用正常",
        }

    def open_docs(self, kind: str = "docs") -> bool:
        path = "redoc" if kind == "redoc" else "docs"
        status = self.status()
        if not status["running"]:
            return False
        return bool(webbrowser.open(f"http://127.0.0.1:{status['port']}/{path}"))

    def status(self) -> dict[str, Any]:
        with self._lock:
            current = self._ensure_config()
            running = self._is_running()
            port = int(current["port"])
            local_url = f"http://127.0.0.1:{port}"
            urls = [local_url]
            if current["scope"] == "lan":
                for address in self._lan_addresses():
                    url = f"http://{address}:{port}"
                    if url not in urls:
                        urls.append(url)
            return {
                "running": running,
                "scope": current["scope"],
                "host": "0.0.0.0" if current["scope"] == "lan" else "127.0.0.1",
                "port": port,
                "api_key": current["api_key"],
                "base_urls": urls,
                "docs_url": f"{local_url}/docs",
                "redoc_url": f"{local_url}/redoc",
                "last_error": self._last_error,
            }

    def shutdown(self) -> None:
        self.stop()

    def _is_running(self) -> bool:
        return bool(
            self._server
            and self._server.started
            and self._thread
            and self._thread.is_alive()
        )

    @staticmethod
    def _lan_addresses() -> list[str]:
        addresses: set[str] = set()
        try:
            for row in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                address = str(row[4][0])
                if not address.startswith("127.") and address != "0.0.0.0":
                    addresses.add(address)
        except OSError:
            pass
        return sorted(addresses)
