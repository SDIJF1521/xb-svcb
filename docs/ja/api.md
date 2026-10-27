[简体中文](../api.md) | [English](../en/api.md) | **日本語**

# XB-SVCB FastAPI連携

対象: XB-SVCB 0.0.32

## 起動とセキュリティ

FastAPIは既定で無効です。「資料庫 -> API接入」で待受範囲とportを設定し、手動で開始します。アプリ終了またはサービス停止でportを解放します。

- ローカル: `127.0.0.1`。同一PCの自動化向けです。
- LAN: `0.0.0.0`。同一networkの端末から画面表示のLAN addressを使います。本機へ解決済みのドメインも設定でき、ローカルへ戻すと消去します。
- 既定port: `8760`。`1024`から`65535`の空きportへ変更できます。
- 認証: `GET /health`、`/docs`、`/redoc`、`/openapi.json`以外は`X-API-Key`が必要です。
- API Key: 名前、期限、有効状態を持つ複数Keyを管理します。有効かつ期限内のKeyだけが使え、最低1件を残します。変更前にサービスを停止してください。旧単一Key設定は自動移行します。

LANモードは信頼できるnetworkだけで使用してください。ドメイン設定はDNS、HTTPS、公開networkの安全設定を自動構成しません。Windows Firewallではprivate network通信を許可し、portを直接internetへ公開しないでください。

## オンラインAPI資料

- Swagger UI: `http://127.0.0.1:8760/docs`
- ReDoc: `http://127.0.0.1:8760/redoc`
- OpenAPI JSON: `http://127.0.0.1:8760/openapi.json`

port変更時はURLも変更してください。LANでは状態画面のdomain URLも使えます。アプリ内接続テストは現在有効なKeyでモデルAPIを呼び、遅延とモデル数を返します。

## 標準フロー

1. `POST /api/v1/uploads`で音声をuploadし、`upload_id`を取得します。
2. `GET /api/v1/models`でモデルと`default_id`を取得します。
3. `POST /api/v1/jobs`で単一・複数モデルtaskを作成します。HTTPは`202`です。batchは`POST /api/v1/jobs/batch`です。
4. `GET /api/v1/jobs/{job_id}`を`done`または`failed`までpollします。
5. 成功後、`result_url`から成果物をdownloadします。

UIとAPIは同じ直列推論queueを使い、互いのtaskを確認できます。現在のCUDA、ROCm 10、DirectML、CPU環境を利用します。

## モデル管理

表示名だけを変更し、ID、weight、設定、source recordは変えません。

```http
PATCH /api/v1/models/{model_id}
Content-Type: application/json

{"name": "新しい表示名"}
```

## PyMSSボーカル処理

用途は`vocal_separation`と`dereverb`だけです。catalogを確認してdownloadします。

```http
GET /api/v1/preprocess/pymss/models?purpose=vocal_separation
POST /api/v1/preprocess/pymss/models/UVR-DeEcho-DeReverb.pth/download
DELETE /api/v1/preprocess/pymss/models/UVR-DeEcho-DeReverb.pth
GET /api/v1/preprocess/pymss/downloads
```

task作成時の`preprocess`例です。旧fieldも利用できます。

```json
{
  "preprocess": {
    "enabled": true,
    "engine": "pymss",
    "pymss_model": "bs_roformer_voc_hyperacev2",
    "harmony_removal_enabled": true,
    "harmony_model": "UVR-DeEcho-DeReverb.pth"
  }
}
```

`harmony_removal_enabled`は既定で`false`です。download状態は`GET /api/v1/preprocess/pymss/downloads`で確認します。モデル未導入、PyMSS利用不能、用途不一致は明確なerrorになります。

editor clipにも同じ処理を使えます。

```json
{
  "engine": "pymss",
  "pymss_model": "bs_roformer_voc_hyperacev2.ckpt",
  "harmony_removal_enabled": true,
  "harmony_model": "UVR-DeEcho-DeReverb.pth",
  "mute_source": true,
  "device": "auto"
}
```

送信先は`/api/v1/editor/projects/{project_id}/tracks/{track_id}/clips/{clip_id}/separate`です。作品から作ったprojectは元taskの`preprocess`設定を維持します。

## Python例

```bash
pip install requests
```

```python
import time
from pathlib import Path
import requests

BASE_URL = "http://127.0.0.1:8760"
HEADERS = {"X-API-Key": "XB-SVCBに表示されたAPI Keyへ置換"}

with open("song.wav", "rb") as audio:
    response = requests.post(
        f"{BASE_URL}/api/v1/uploads", headers=HEADERS,
        files={"file": ("song.wav", audio, "audio/wav")}, timeout=None,
    )
    response.raise_for_status()
    upload = response.json()

models = requests.get(f"{BASE_URL}/api/v1/models", headers=HEADERS, timeout=30)
models.raise_for_status()
model_data = models.json()
model_id = model_data["default_id"] or model_data["items"][0]["id"]

response = requests.post(
    f"{BASE_URL}/api/v1/jobs", headers=HEADERS,
    json={
        "source_upload_id": upload["upload_id"], "model_id": model_id,
        "params": {"pitch": 0, "f0_method": "rmvpe", "device": "auto"},
    }, timeout=30,
)
response.raise_for_status()
job = response.json()

while True:
    response = requests.get(f"{BASE_URL}/api/v1/jobs/{job['id']}", headers=HEADERS, timeout=30)
    response.raise_for_status()
    current = response.json()
    if current["status"] in {"done", "failed"}:
        break
    time.sleep(2)

if current["status"] != "done":
    raise RuntimeError(current.get("error") or "タスク失敗")
response = requests.get(f"{BASE_URL}{current['result_url']}", headers=HEADERS, timeout=None)
response.raise_for_status()
Path("cover.wav").write_bytes(response.content)
```

## SeedVC task

sourceとtarget voice referenceを別々にuploadし、`reference_upload_id`を指定します。

```json
{
  "source_upload_id": "source upload_id",
  "reference_upload_id": "reference upload_id",
  "model_id": "SeedVC model ID",
  "params": {"pitch": 0, "device": "auto"}
}
```

## 複数モデルカバー

`mode`を`multi`にし、`models`へモデル別設定、`segments`へ歌唱範囲を指定します。一つの`model_ids`に複数IDがあると合唱になります。

```json
{
  "source_upload_id": "source upload_id",
  "mode": "multi",
  "workflow": "auto_vocal_merge",
  "models": [
    {"model_id": "model_svc", "params": {"pitch": 0, "device": "auto"}},
    {"model_id": "model_seedvc", "reference_upload_id": "SeedVC reference upload_id", "params": {"pitch": 0, "device": "auto"}}
  ],
  "segments": [
    {"start": 0, "end": 12.5, "model_ids": ["model_svc"]},
    {"start": 12.5, "end": 24, "model_ids": ["model_svc", "model_seedvc"]}
  ]
}
```

workflowは`auto_mix`、`auto_vocal_merge`、`manual_vocal_merge`、`auto_then_editor`、`full_manual_editor`です。後二つのvocal merge方式は単一モデルには使えません。

`models[].params.auto_high_pitch_guard`はモデル別高音保護で、既定はtrueです。高音部分だけ低いpitchで推論後に戻します。旧requestはtop-level `params.auto_high_pitch_guard`も使えます。

完全な複数モデルPython client例は[英語版](../en/api.md#complete-python-example)または[中国語版](../api.md#完整-python-示例)にあり、fieldとendpointは言語間で共通です。

## Audio Editorフロー

1. 音声upload後に`POST /api/v1/editor/projects`を呼ぶか、`work_id`からprojectを作ります。
2. `GET /api/v1/editor/projects/{project_id}`でtimelineを読みます。clipはlocal `file`ではなく`audio_url`と`waveform_url`を返します。
3. 音量、fade、channel、envelope、role、effect chainを変更し、`PUT /api/v1/editor/projects/{project_id}`で保存します。新素材はimport、split、separate、rerun endpointで作成します。
4. project、track、clipの`/audio`からWAV、MP3、FLACをrenderします。

取得したprojectは変更して再送できます。`audio_url`、`waveform_url`、`render_url`は保存時に破棄され、実file参照はserverが復元するため、任意のlocal pathへ上書きできません。

`time_stretch`は`0.25 - 4.0`、既定`1.0`です。波形、preview、plugin monitor、renderへ一貫して反映します。範囲再推論の`auto_high_pitch_guard`は既定trueで、AI美声と併用時は高周波着色を自動的に抑えます。

## Endpoint一覧

| Method | Path | 内容 |
| --- | --- | --- |
| `GET` | `/health` | Key不要のhealth check |
| `GET` | `/api/v1/system` | toolとGPU runtime |
| `GET` | `/api/v1/models` | model一覧と既定model |
| `POST` | `/api/v1/models/default` | 既定model設定 |
| `GET/PATCH/DELETE` | `/api/v1/models/{model_id}` | 取得、表示名変更、削除 |
| `POST` | `/api/v1/models/{model_id}/favorite` | favorite切替 |
| `POST` | `/api/v1/models/{model_id}/inspect` | 検査と任意修復 |
| `POST/DELETE` | `/api/v1/uploads[/{upload_id}]` | stream upload / 削除 |
| `GET` | `/api/v1/jobs`, `/queue`, `/history` | task、queue、履歴 |
| `GET/POST/DELETE` | `/api/v1/jobs/presets[/{preset_id}]` | preset管理 |
| `POST` | `/api/v1/jobs` | 単一・複数モデルtask |
| `POST` | `/api/v1/jobs/batch` | 最大50件のbatch |
| `GET/PATCH/DELETE` | `/api/v1/jobs/{job_id}` | task取得、改名、削除 |
| `POST` | `/api/v1/jobs/{job_id}/retry` | retry |
| `GET` | `/api/v1/jobs/{job_id}/audio` | `output`、`instrumental`、`vocals`取得 |
| `GET/POST` | `/api/v1/editor/projects` | project一覧・作成 |
| `GET/PUT/DELETE` | `/api/v1/editor/projects/{project_id}` | project取得・保存・削除 |
| `POST` | project `/undo`、`/redo` | undo / redo |
| `POST/DELETE` | project `/tracks[/{track_id}]` | track追加・削除 |
| `POST` | track `/clips` | `upload_id`からclip import |
| `GET` | project / track / clip `/audio` | audio render |
| `GET` | clip `/waveform` | 波形取得 |
| `POST` | clip `/split/silence`、`/split/lyrics` | 無音またはTXT/LRC分割 |
| `POST` | clip `/separate` | UVR/PyMSS分離と任意dereverb |
| `POST` | clip `/rerun` | 範囲再推論 |
| `POST` | track `/clips/merge` | clip結合render |

## 主なstatus code

| Code | 内容 |
| --- | --- |
| `200` | 成功 |
| `201` | upload成功 |
| `202` | taskをqueueへ追加 |
| `401` | Key不足または不正 |
| `404` | model、task、file、`upload_id`なし |
| `409` | 結果未生成または現在状態では操作不可 |
| `415` | 非対応形式 |
| `422` | fieldまたはparameter組合せ不正 |

## Fileとcleanup

upload size上限は設定せず、固定小blockでdiskへstreamし、全fileをmemoryへ読みません。容量はdata directoryの空き容量に依存します。fileは`api/uploads`へ保存され、data directory移行に追従します。推論終了後に不要なuploadを削除してください。生成作品は「我的作品」で管理されます。
