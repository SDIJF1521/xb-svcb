"""自定义工作流：图校验、任务创建、节点图执行的单元测试。

用假 ffmpeg / UVR / 引擎替代真实推理，验证编排逻辑是否正确。
"""

import json
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
from application.audio_editor_service import AudioEditorService
from application.conversion_service import ConversionService
from application.work_service import WorkService
from domain.workflow_graph import topological_order, validate_graph
from infrastructure import pymss_catalog_meta
from infrastructure.pymss_worker import _match_configured_stem, _name_score
from infrastructure.pymss_tool import PymssTool
from infrastructure.storage import ListRepository, SettingsStore


@pytest.fixture
def wtmp() -> Path:
    """工作区内的临时目录（沙箱下比系统临时目录更可靠）。"""
    base = Path(__file__).resolve().parent / "_tmp_custom_workflow" / uuid.uuid4().hex
    base.mkdir(parents=True, exist_ok=True)
    yield base
    shutil.rmtree(base, ignore_errors=True)


# ---- 夹具 ----
def _graph(*, convert_params: dict | None = None, connect_save: bool = True) -> dict:
    convert_params = {
        "model_id": "mdl_a",
        "auto_high_pitch_guard": False,
        "manual_params_enabled": False,
        "device": "auto",
        **(convert_params or {}),
    }
    nodes = [
        {"id": "i", "type": "input", "x": 0, "y": 0, "params": {}},
        {"id": "s", "type": "separate", "x": 200, "y": 0, "params": {"engine": "uvr", "model": "MDX-Net", "device": "auto"}},
        {"id": "c", "type": "convert", "x": 400, "y": 0, "params": convert_params},
        {"id": "m", "type": "mix", "x": 600, "y": 0, "params": {"enhanced": False}},
        {"id": "o", "type": "output", "x": 800, "y": 0, "params": {"file_template": "%filename%_%stem%_%model%"}},
    ]
    edges = [
        {"id": "e1", "from": {"node": "i", "port": "audio"}, "to": {"node": "s", "port": "audio"}},
        {"id": "e2", "from": {"node": "s", "port": "vocals"}, "to": {"node": "c", "port": "audio"}},
        {"id": "e3", "from": {"node": "s", "port": "instrumental"}, "to": {"node": "m", "port": "instrumental"}},
        {"id": "e4", "from": {"node": "c", "port": "audio"}, "to": {"node": "m", "port": "vocals"}},
    ]
    if connect_save:
        edges.append({"id": "e5", "from": {"node": "m", "port": "audio"}, "to": {"node": "o", "port": "audio"}})
    return {"name": "测试工作流", "updated_at": "", "nodes": nodes, "edges": edges}


class _QueuedConversion:
    def __init__(self) -> None:
        self.started: list[str] = []

    def start(self, work_id: str) -> None:
        self.started.append(work_id)


class _FakeModels:
    def __init__(self, models: list[dict]) -> None:
        self._by_id = {m["id"]: m for m in models}

    def get(self, model_id: str):
        return self._by_id.get(model_id)

    def default_id(self):
        return None


class _FakeFfmpeg:
    available = True
    ffmpeg = None  # AudioEditorService 会包一层 FFmpegEngine

    def probe_duration(self, _path: Path) -> float:
        return 125.0

    def adaptive_mix_profile(self, _v: Path, _i: Path) -> dict:
        return {"vocal_gain_db": 0.0, "instrumental_gain_db": 0.0, "vocal_lufs": -16.0, "instrumental_lufs": -18.0}

    def mix(self, vocals: Path, instrumental: Path, output: Path, **_kwargs) -> bool:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(vocals.read_bytes() + instrumental.read_bytes())
        return True

    def convert(self, source: Path, output: Path, *_args, **_kwargs) -> bool:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(source.read_bytes())
        return True

    def slice(self, src: Path, start: float, end: float, dst: Path, sample_rate: int = 44100, fade: float = 0.0) -> bool:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"trim:" + str(round(end - start, 2)).encode() + b":" + src.read_bytes())
        return True

    def concat(self, parts: list[Path], dst: Path, sample_rate: int = 44100) -> bool:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"".join(p.read_bytes() for p in parts))
        return True

    def merge_tracks(self, inputs: list[Path], dst: Path, sample_rate: int = 44100) -> bool:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"merged:" + b"+".join(p.read_bytes() for p in inputs))
        return True

    def apply_effect(self, src: Path, dst: Path, effect_type: str, params: dict, sample_rate: int = 44100) -> bool:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"fx:" + effect_type.encode() + b":" + src.read_bytes())
        return True

    def loudnorm(self, src: Path, dst: Path, target_lufs: float = -14.0, sample_rate: int = 44100) -> bool:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"loudnorm:" + src.read_bytes())
        return True

    def tempo(self, src: Path, dst: Path, speed: float, sample_rate: int = 44100) -> bool:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"tempo:" + src.read_bytes())
        return True

    def pitch(self, src: Path, dst: Path, semitones: int, sample_rate: int = 44100) -> bool:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"pitch:" + str(semitones).encode() + b":" + src.read_bytes())
        return True

    def fade(self, src: Path, dst: Path, fade_in: float, fade_out: float, sample_rate: int = 44100) -> bool:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"fade:" + src.read_bytes())
        return True


class _FakeUvr:
    available = True

    def separate(self, _source: Path, output_dir: Path, _model: str, _device: str):
        output_dir.mkdir(parents=True, exist_ok=True)
        vocals = output_dir / "vocals.wav"
        instrumental = output_dir / "instrumental.wav"
        vocals.write_bytes(b"vocals")
        instrumental.write_bytes(b"instrumental")
        return SimpleNamespace(vocals=vocals, instrumental=instrumental, simulated=False, device="cpu")


class _FakeEngine:
    available = True

    def infer(self, *, model, vocals, out_path, params, duration, log_file) -> None:  # noqa: ANN001
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"converted-" + vocals.read_bytes())


class _FakeEngines:
    sovits = None

    def __init__(self) -> None:
        self._engines: dict[str, _FakeEngine] = {}

    def for_framework(self, framework: str) -> _FakeEngine:
        return self._engines.setdefault(framework, _FakeEngine())


class _FakeEnhancer:
    available = False


class _FakePymss:
    available = False


class _FakePymssMultiStem:
    """模拟「输出音轨与人声分离不一致」的 PyMSS 模型（例如多轨 / 去混响模型）。"""

    available = True
    declared = ["Vocals", "Drums"]

    def declared_stems(self, _model: str = "") -> list[str]:
        return list(self.declared)

    def separate(  # noqa: ARG002
        self,
        _source: Path,
        output_dir: Path,
        _model: str,
        _device: str,
        purpose: str = "",
        primary_stem: str = "",
    ):
        self.last_primary = str(primary_stem)
        output_dir.mkdir(parents=True, exist_ok=True)
        vocals = output_dir / "pymss_vocals.wav"
        drums = output_dir / "pymss_stem_01.wav"
        vocals.write_bytes(b"vocals")
        drums.write_bytes(b"drums")
        return SimpleNamespace(
            vocals=vocals,
            instrumental=None,
            simulated=False,
            device="cpu",
            stems=[
                {"name": "Vocals", "path": str(vocals)},
                {"name": "Drums", "path": str(drums)},
            ],
        )


def _repo(wtmp: Path, monkeypatch) -> ListRepository:  # noqa: ANN001
    data = wtmp / "data"
    monkeypatch.setattr(config, "WORKS_DIR", data / "works")
    monkeypatch.setattr(config, "WORKS_DB", data / "works.json")
    monkeypatch.setattr(config, "SETTINGS_DB", data / "settings.json")
    return ListRepository(config.WORKS_DB)


# ---- 图校验 ----
def test_validate_full_pipeline() -> None:
    assert validate_graph(_graph()) is None


def test_validate_requires_exactly_one_input() -> None:
    graph = _graph()
    graph["nodes"].append({"id": "i2", "type": "input", "x": 0, "y": 0, "params": {}})
    assert "输入音频" in (validate_graph(graph) or "")


def test_validate_requires_exactly_one_save_node() -> None:
    graph = _graph()
    graph["nodes"].append({"id": "o2", "type": "output", "x": 0, "y": 0, "params": {}})
    assert "保存" in (validate_graph(graph) or "")


def test_validate_rejects_unknown_node_type() -> None:
    graph = _graph()
    graph["nodes"].append({"id": "x", "type": "mystery", "x": 0, "y": 0, "params": {}})
    assert "未知节点类型" in (validate_graph(graph) or "")


def test_validate_rejects_cycle() -> None:
    graph = {
        "nodes": [
            {"id": "i", "type": "input"},
            {"id": "b1", "type": "blend"},
            {"id": "b2", "type": "blend"},
            {"id": "o", "type": "output"},
        ],
        "edges": [
            {"id": "e1", "from": {"node": "i", "port": "audio"}, "to": {"node": "b1", "port": "audio"}},
            {"id": "e2", "from": {"node": "b1", "port": "audio"}, "to": {"node": "b2", "port": "audio"}},
            {"id": "e3", "from": {"node": "b2", "port": "audio"}, "to": {"node": "b1", "port": "audio"}},
            {"id": "e4", "from": {"node": "b2", "port": "audio"}, "to": {"node": "o", "port": "audio"}},
        ],
    }
    assert "循环" in (validate_graph(graph) or "")


def test_validate_allows_multi_input_save() -> None:
    graph = _graph()
    # 再把人声也直接接到保存节点（保存节点 audio 端口允许多路）。
    graph["edges"].append({"id": "e6", "from": {"node": "c", "port": "audio"}, "to": {"node": "o", "port": "audio"}})
    assert validate_graph(graph) is None


def test_validate_rejects_two_edges_to_single_input() -> None:
    graph = _graph()
    graph["edges"].append({"id": "e6", "from": {"node": "s", "port": "instrumental"}, "to": {"node": "c", "port": "audio"}})
    assert "只能连接一条线" in (validate_graph(graph) or "")


def test_validate_allows_dynamic_stem_ports() -> None:
    graph = _graph()
    # 多轨 PyMSS 模型可按实际音轨动态输出：other / stem:<label>。
    graph["edges"].append({"id": "e6", "from": {"node": "s", "port": "other"}, "to": {"node": "o", "port": "audio"}})
    graph["edges"].append({"id": "e7", "from": {"node": "s", "port": "stem:drums"}, "to": {"node": "o", "port": "audio"}})
    graph["edges"].append({"id": "e8", "from": {"node": "s", "port": "audio"}, "to": {"node": "o", "port": "audio"}})
    assert validate_graph(graph) is None


def test_validate_rejects_unknown_separate_port() -> None:
    graph = _graph()
    graph["edges"].append({"id": "e6", "from": {"node": "s", "port": "drums"}, "to": {"node": "o", "port": "audio"}})
    assert "没有输出端口" in (validate_graph(graph) or "")


def test_pymss_generic_scoring_prefers_dry_stem() -> None:
    """自定义工作流用 generic 跑模型时，干声要优先于湿声（混响）输出。"""
    assert _name_score(Path("song_(No Reverb).wav"), "generic", "vocals") > _name_score(
        Path("song_(Reverb).wav"), "generic", "vocals"
    )
    # 普通多轨模型（人声/鼓/贝斯）不受干湿偏好影响
    assert _name_score(Path("song_Drums.wav"), "generic", "drums") == _name_score(
        Path("song_Bass.wav"), "generic", "bass"
    )


def test_pymss_primary_stem_uses_whole_word_match() -> None:
    """主音轨 male 不能命中 female。"""
    assert _name_score(Path("song_(male).wav"), "generic", "male") > _name_score(
        Path("song_(female).wav"), "generic", "male"
    )


def test_pymss_stem_label_uses_whole_word_match() -> None:
    """男/女声分离：female 输出不能被误标成 male（否则端口会变成 male_2）。"""
    names = ["male", "female"]
    assert _match_configured_stem("song_(male)", names) == "male"
    assert _match_configured_stem("song_(female)", names) == "female"
    assert _match_configured_stem("song (Female)", names) == "female"
    # 文件名没带音轨名时不猜测，交给上层按声明顺序兜底。
    assert _match_configured_stem("song_stem_01", names) is None


def test_parse_instruments_supports_inline_and_block_lists() -> None:
    assert pymss_catalog_meta.parse_instruments(
        "training:\n  instruments: [vocals, instrumental]\n"
    ) == ["vocals", "instrumental"]
    assert pymss_catalog_meta.parse_instruments(
        "training:\n  instruments:\n  - male\n  - female\n  lr: 0.1\n"
    ) == ["male", "female"]
    assert pymss_catalog_meta.parse_instruments("model:\n  depth: 12\n") == []


def test_pymss_model_stems_are_read_from_yaml(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    """模型 yaml 声明的输出音轨要能补进 catalog 行，供节点生成端口。"""
    model_dir = wtmp / "pymss_models"
    target = model_dir / "vocal" / "vocal_gender_chorus"
    target.mkdir(parents=True)
    (target / "m.gender_chorus.ckpt").write_bytes(b"w")
    (target / "m.gender_chorus.yaml").write_text(
        "training:\n  instruments:\n    - male\n    - female\n  target_instrument: null\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "PYMSS_MODEL_DIR", model_dir)

    rows = [
        {"name": "m.gender_chorus.ckpt"},
        {"name": "m.gender_chorus.ckpt", "target_stem": "female"},
    ]
    pymss_catalog_meta.attach_model_stems(rows, model_dir)

    assert rows[0]["stems"] == ["male", "female"]
    assert rows[0]["primary_stem"] == "male"
    # catalog 指定了目标音轨时以目标音轨为主
    assert rows[1]["primary_stem"] == "female"
    assert PymssTool.declared_stems("m.gender_chorus.ckpt") == ["male", "female"]


def test_topological_order_respects_dependencies() -> None:
    graph = _graph()
    order = topological_order(graph["nodes"], graph["edges"])
    assert order is not None
    pos = {node_id: index for index, node_id in enumerate(order)}
    assert pos["i"] < pos["s"] < pos["c"] < pos["m"] < pos["o"]


# ---- 任务创建 ----
def test_create_workflow_builds_steps_and_models(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    repo = _repo(wtmp, monkeypatch)
    conversion = _QueuedConversion()
    model = {
        "id": "mdl_a", "name": "Model A", "type": "RVC", "framework": "rvc",
        "main_model": {"name": "a.pth", "path": "/models/a.pth"},
        "main_config": {"name": "", "path": ""},
        "diffusion_model": None, "diffusion_config": None, "index_file": None,
        "metadata": {},
    }
    service = WorkService(repo, conversion, _FakeModels([model]), SettingsStore(config.SETTINGS_DB))
    source = wtmp / "song.wav"
    source.write_bytes(b"song")

    work = service.create({"mode": "workflow", "source_path": str(source), "title": "T", "workflow_graph": _graph()})

    assert work["mode"] == "workflow"
    assert work["workflow"] == "workflow"
    assert work["status"] == "queue"
    keys = [step["key"] for step in work["steps"]]
    assert keys == topological_order(_graph()["nodes"], _graph()["edges"])
    assert work["workflow_models"]["c"]["main_model_path"] == "/models/a.pth"
    assert work["workflow_models"]["c"]["framework"] == "rvc"
    assert conversion.started == [work["id"]]
    # 生成的翻唱成品作为作品出现在「我的作品」列表中。
    assert any(item["id"] == work["id"] for item in service.list())


def test_create_workflow_applies_detected_rvc_version(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    repo = _repo(wtmp, monkeypatch)
    conversion = _QueuedConversion()
    model = {
        "id": "mdl_a", "name": "Model A", "type": "RVC", "framework": "rvc",
        "main_model": {"name": "a.pth", "path": "/models/a.pth"},
        "main_config": {"name": "", "path": ""},
        "diffusion_model": None, "diffusion_config": None, "index_file": None,
        # 软件检测出的版本（v1），节点里即使残留 v2 也应以检测结果为准。
        "metadata": {"rvc_version": "v1"},
    }
    service = WorkService(repo, conversion, _FakeModels([model]), SettingsStore(config.SETTINGS_DB))
    source = wtmp / "song.wav"
    source.write_bytes(b"song")
    graph = _graph(convert_params={"model_id": "mdl_a", "rvc_version": "v2"})
    work = service.create({"mode": "workflow", "source_path": str(source), "title": "T", "workflow_graph": graph})

    assert work["workflow_models"]["c"]["params"]["rvc_version"] == "v1"


def test_retry_workflow_rebuilds_steps_and_models(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    repo = _repo(wtmp, monkeypatch)
    conversion = _QueuedConversion()
    model = {
        "id": "mdl_a", "name": "Model A", "type": "RVC", "framework": "rvc",
        "main_model": {"name": "a.pth", "path": "/models/a.pth"},
        "main_config": {"name": "", "path": ""},
        "diffusion_model": None, "diffusion_config": None, "index_file": None,
        "metadata": {},
    }
    service = WorkService(repo, conversion, _FakeModels([model]), SettingsStore(config.SETTINGS_DB))
    source = wtmp / "song.wav"
    source.write_bytes(b"song")
    work = service.create({"mode": "workflow", "source_path": str(source), "title": "T", "workflow_graph": _graph()})
    record = repo.get(work["id"])
    record["status"] = "failed"
    record["steps"] = []
    repo.update(record["id"], record)
    conversion.started.clear()

    assert service.retry(work["id"]) is True
    retried = repo.get(work["id"])
    assert retried["status"] == "queue"
    assert [step["key"] for step in retried["steps"]] == topological_order(_graph()["nodes"], _graph()["edges"])
    assert retried["workflow_models"]["c"]["main_model_path"] == "/models/a.pth"
    assert conversion.started == [work["id"]]


def test_create_workflow_rejects_invalid_graph(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    repo = _repo(wtmp, monkeypatch)
    service = WorkService(repo, _QueuedConversion(), _FakeModels([]), SettingsStore(config.SETTINGS_DB))
    source = wtmp / "song.wav"
    source.write_bytes(b"song")
    graph = _graph()
    graph["nodes"] = [n for n in graph["nodes"] if n["type"] != "input"]
    try:
        service.create({"mode": "workflow", "source_path": str(source), "workflow_graph": graph})
        raised = False
    except ValueError:
        raised = True
    assert raised


# ---- 节点图执行 ----
def _run_service(repo: ListRepository) -> ConversionService:
    return ConversionService(
        repo,
        _FakeFfmpeg(),
        _FakeUvr(),
        _FakeEngines(),
        vocal_enhancement=_FakeEnhancer(),
        pymss=_FakePymss(),
    )


def _work_record(wtmp: Path, graph: dict) -> dict:
    source = wtmp / "song.wav"
    source.write_bytes(b"song")
    order = topological_order(graph["nodes"], graph["edges"]) or []
    return {
        "id": "wrk_wf",
        "title": "测试工作流",
        "mode": "workflow",
        "workflow": "workflow",
        "status": "queue",
        "progress": 0,
        "source_path": str(source),
        "workflow_graph": graph,
        "workflow_models": {
            "c": {
                "name": "Model A",
                "framework": "rvc",
                "main_model_path": "/models/a.pth",
                "main_config_path": "",
                "diffusion_model_path": "",
                "diffusion_config_path": "",
                "index_path": "",
                "params": {"auto_high_pitch_guard": False, "manual_params_enabled": False, "device": "auto"},
            }
        },
        "steps": [{"key": key, "label": key, "status": "wait"} for key in order],
        "params": {},
        "vocal_enhancement": {},
        "preprocess": {},
    }


def test_run_workflow_executes_and_saves_output(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    repo = _repo(wtmp, monkeypatch)
    graph = _graph()
    work = _work_record(wtmp, graph)
    repo.add(work)

    service = _run_service(repo)
    service._run_workflow(work["id"])  # noqa: SLF001

    saved = repo.get(work["id"])
    assert saved is not None
    assert saved["status"] == "done", saved.get("error")
    assert Path(saved["output_path"]).is_file()
    assert saved["workflow_outputs"]
    assert all(step["status"] == "done" for step in saved["steps"])
    assert saved["duration"] == "02:05"


def test_run_workflow_saves_multiple_tracks_into_one_save_node(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    repo = _repo(wtmp, monkeypatch)
    graph = _graph()
    # 人声直接保存 + 混音结果保存，共两路进入同一个保存节点。
    graph["edges"].append({"id": "e6", "from": {"node": "c", "port": "audio"}, "to": {"node": "o", "port": "audio"}})
    work = _work_record(wtmp, graph)
    repo.add(work)

    service = _run_service(repo)
    service._run_workflow(work["id"])  # noqa: SLF001

    saved = repo.get(work["id"])
    assert saved is not None
    assert saved["status"] == "done", saved.get("error")
    assert len(saved["workflow_outputs"]) == 2


def test_editor_material_includes_extra_workflow_outputs(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    repo = _repo(wtmp, monkeypatch)
    work_dir = config.WORKS_DIR / "wrk_wf"
    work_dir.mkdir(parents=True, exist_ok=True)
    primary = work_dir / "output.wav"
    primary.write_bytes(b"primary")
    extra_dir = work_dir / "outputs"
    extra_dir.mkdir(parents=True, exist_ok=True)
    extra = extra_dir / "track_01.wav"
    extra.write_bytes(b"extra")
    repo.add(
        {
            "id": "wrk_wf", "title": "T", "mode": "workflow", "workflow": "workflow",
            "status": "done", "duration": "02:05",
            "output_path": str(primary), "converted_path": str(primary),
            "source_path": "", "workflow_outputs": [
                {"index": 0, "primary": True, "path": str(primary), "label": "混音合成"},
                {"index": 1, "primary": False, "path": str(extra), "label": "人声分离"},
            ],
        }
    )
    service = AudioEditorService(
        ListRepository(wtmp / "editor.json"),
        repo,
        None,  # type: ignore[arg-type]
        _FakeFfmpeg(),
        None,  # type: ignore[arg-type]
        None,
        vocal_enhancement=_FakeEnhancer(),
        pymss=_FakePymss(),
    )
    project = service.create_from_work("wrk_wf")  # noqa: SLF001
    assert project is not None
    names = [track["name"] for track in project["tracks"]]
    # 成品进入「翻唱成品」轨，附加音轨作为「素材」轨自动导入。
    assert any("翻唱成品" in name for name in names)
    assert any("人声分离" in name for name in names)


def test_run_workflow_maps_pymss_extra_stems(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    """PyMSS 模型输出不含伴奏 / 含附加音轨时，按实际音轨生成端口。"""
    repo = _repo(wtmp, monkeypatch)
    monkeypatch.setattr(config, "pymss_model_ready", lambda *_args, **_kwargs: True)
    graph = _graph()
    graph["nodes"] = [n for n in graph["nodes"] if n["type"] in {"input", "separate", "output"}]
    graph["nodes"][1]["params"] = {"engine": "pymss", "model": "multi_stem_model", "device": "auto"}
    graph["edges"] = [
        {"id": "e1", "from": {"node": "i", "port": "audio"}, "to": {"node": "s", "port": "audio"}},
        {"id": "e2", "from": {"node": "s", "port": "vocals"}, "to": {"node": "o", "port": "audio"}},
        {"id": "e3", "from": {"node": "s", "port": "other"}, "to": {"node": "o", "port": "audio"}},
        {"id": "e4", "from": {"node": "s", "port": "stem:drums"}, "to": {"node": "o", "port": "audio"}},
    ]
    work = _work_record(wtmp, graph)
    repo.add(work)

    service = ConversionService(
        repo,
        _FakeFfmpeg(),
        _FakeUvr(),
        _FakeEngines(),
        vocal_enhancement=_FakeEnhancer(),
        pymss=_FakePymssMultiStem(),
    )
    service._run_workflow(work["id"])  # noqa: SLF001

    saved = repo.get(work["id"])
    assert saved is not None
    assert saved["status"] == "done", saved.get("error")
    ports = [item["port"] for item in saved["workflow_outputs"]]
    # 人声 + other（第一路附加音轨）+ stem:drums 三路都能被保存节点收集。
    assert ports == ["vocals", "other", "stem:drums"]
    drum_track = saved["workflow_outputs"][2]
    assert Path(drum_track["path"]).read_bytes() == b"drums"


def test_run_workflow_reports_missing_upstream_stem(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    """上游端口没有产出音轨时，报错要说明是哪个音轨缺失。"""
    repo = _repo(wtmp, monkeypatch)
    graph = _graph()
    for edge in graph["edges"]:
        if edge["id"] == "e2":
            edge["from"]["port"] = "other"
    work = _work_record(wtmp, graph)
    repo.add(work)

    service = _run_service(repo)
    service._run_workflow(work["id"])  # noqa: SLF001

    saved = repo.get(work["id"])
    assert saved is not None
    assert saved["status"] == "failed"
    assert "未产出" in str(saved.get("error") or "")


def test_run_workflow_forwards_primary_stem(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    """节点里选的主音轨要传给 PyMSS，端口仍按模型声明的音轨生成。"""
    repo = _repo(wtmp, monkeypatch)
    monkeypatch.setattr(config, "pymss_model_ready", lambda *_args, **_kwargs: True)
    graph = _graph()
    graph["nodes"] = [n for n in graph["nodes"] if n["type"] in {"input", "separate", "output"}]
    graph["nodes"][1]["params"] = {
        "engine": "pymss", "model": "multi_stem_model", "device": "auto", "primary_stem": "Drums",
    }
    graph["edges"] = [
        {"id": "e1", "from": {"node": "i", "port": "audio"}, "to": {"node": "s", "port": "audio"}},
        {"id": "e2", "from": {"node": "s", "port": "vocals"}, "to": {"node": "o", "port": "audio"}},
        {"id": "e3", "from": {"node": "s", "port": "stem:drums"}, "to": {"node": "o", "port": "audio"}},
    ]
    work = _work_record(wtmp, graph)
    repo.add(work)
    fake = _FakePymssMultiStem()

    service = ConversionService(
        repo,
        _FakeFfmpeg(),
        _FakeUvr(),
        _FakeEngines(),
        vocal_enhancement=_FakeEnhancer(),
        pymss=fake,
    )
    service._run_workflow(work["id"])  # noqa: SLF001

    assert fake.last_primary == "Drums"
    saved = repo.get(work["id"])
    assert saved is not None
    assert saved["status"] == "done", saved.get("error")
    # 标题带上端口名，方便在音频编辑器里区分素材。
    labels = [item["label"] for item in saved["workflow_outputs"]]
    assert labels == ["人声分离 · 人声", "人声分离 · 音轨 drums"]


def test_workflow_file_round_trip(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    """导出的工作流文件可以被重新导入，并保留节点、连线与名称。"""
    repo = _repo(wtmp, monkeypatch)
    service = WorkService(repo, _QueuedConversion(), _FakeModels([]), SettingsStore(config.SETTINGS_DB))
    graph = _graph()
    graph["name"] = "我的工作流"
    payload = service.workflow_file_payload(graph)

    assert payload["kind"] == "xb-cover-workflow"
    assert payload["name"] == "我的工作流"
    # 走一遍 JSON 序列化，确认文件内容可读回
    restored = service.parse_workflow_file(json.loads(json.dumps(payload)))
    assert restored["name"] == "我的工作流"
    assert restored["id"] == ""
    assert len(restored["nodes"]) == len(graph["nodes"])
    assert len(restored["edges"]) == len(graph["edges"])
    assert validate_graph(restored) is None


def test_parse_workflow_file_rejects_invalid_graph() -> None:
    with pytest.raises(ValueError):
        WorkService.parse_workflow_file({"nodes": "bad", "edges": []})
    # 缺少输入节点 / 保存节点的图也要拒绝
    with pytest.raises(ValueError):
        WorkService.parse_workflow_file(
            {"nodes": [{"id": "c", "type": "convert"}], "edges": []}
        )


def test_save_workflow_avoids_duplicate_names(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    """同一名称保存两次时自动加序号，更新已有工作流则保留原名。"""
    repo = _repo(wtmp, monkeypatch)
    service = WorkService(repo, _QueuedConversion(), _FakeModels([]), SettingsStore(config.SETTINGS_DB))
    first = service.save_workflow("我的工作流", _graph())
    second = service.save_workflow("我的工作流", _graph())
    assert first["name"] == "我的工作流"
    assert second["name"] == "我的工作流 (2)"
    assert second["id"] != first["id"]
    # 按 id 更新同一条工作流时不会误加序号
    updated = service.save_workflow("我的工作流", {**_graph(), "id": first["id"]})
    assert updated["id"] == first["id"]
    assert updated["name"] == "我的工作流"


def test_run_workflow_dedupes_duplicate_edges_and_labels(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    """重复连线只保存一次；不同节点同名标签自动加序号，避免重名素材。"""
    repo = _repo(wtmp, monkeypatch)
    graph = {
        "name": "去重",
        "nodes": [
            {"id": "i", "type": "input", "x": 0, "y": 0, "params": {}},
            {"id": "s", "type": "separate", "x": 1, "y": 0, "params": {"engine": "uvr", "model": "MDX-Net", "device": "auto"}},
            {"id": "c1", "type": "convert", "x": 2, "y": 0, "params": {"model_id": "mdl_a", "auto_high_pitch_guard": False, "device": "auto"}},
            {"id": "c2", "type": "convert", "x": 2, "y": 1, "params": {"model_id": "mdl_b", "auto_high_pitch_guard": False, "device": "auto"}},
            {"id": "o", "type": "output", "x": 3, "y": 0, "params": {"file_template": "%filename%_%stem%_%model%"}},
        ],
        "edges": [
            {"id": "e1", "from": {"node": "i", "port": "audio"}, "to": {"node": "s", "port": "audio"}},
            {"id": "e2", "from": {"node": "s", "port": "vocals"}, "to": {"node": "c1", "port": "audio"}},
            {"id": "e3", "from": {"node": "s", "port": "vocals"}, "to": {"node": "c2", "port": "audio"}},
            {"id": "e4", "from": {"node": "c1", "port": "audio"}, "to": {"node": "o", "port": "audio"}},
            {"id": "e5", "from": {"node": "c2", "port": "audio"}, "to": {"node": "o", "port": "audio"}},
            # 重复连线：同一输出接到保存节点两次
            {"id": "e6", "from": {"node": "c1", "port": "audio"}, "to": {"node": "o", "port": "audio"}},
        ],
    }
    source = wtmp / "song.wav"
    source.write_bytes(b"song")
    order = topological_order(graph["nodes"], graph["edges"]) or []
    repo.add(
        {
            "id": "wrk_dedupe",
            "title": "去重",
            "mode": "workflow",
            "workflow": "workflow",
            "status": "queue",
            "progress": 0,
            "source_path": str(source),
            "workflow_graph": graph,
            "workflow_models": {
                "c1": {"name": "Model A", "framework": "rvc", "main_model_path": "/m/a.pth", "main_config_path": "", "diffusion_model_path": "", "diffusion_config_path": "", "index_path": "", "params": {"auto_high_pitch_guard": False, "device": "auto"}},
                "c2": {"name": "Model B", "framework": "rvc", "main_model_path": "/m/b.pth", "main_config_path": "", "diffusion_model_path": "", "diffusion_config_path": "", "index_path": "", "params": {"auto_high_pitch_guard": False, "device": "auto"}},
            },
            "steps": [{"key": key, "label": key, "status": "wait"} for key in order],
            "params": {},
            "vocal_enhancement": {},
            "preprocess": {},
        }
    )

    service = _run_service(repo)
    service._run_workflow("wrk_dedupe")  # noqa: SLF001

    saved = repo.get("wrk_dedupe")
    assert saved is not None
    assert saved["status"] == "done", saved.get("error")
    outputs = saved["workflow_outputs"]
    # 重复连线只算一路；两个转换节点各保存一路
    assert len(outputs) == 2
    paths = [item["path"] for item in outputs]
    assert len(paths) == len(set(paths))
    labels = [item["label"] for item in outputs]
    assert len(labels) == len(set(labels))


class _FakeAudioEngine:
    """替代 FFmpegEngine：直接写出一个文件，用轨道数量标记渲染内容。"""

    available = True

    def render_timeline(self, project: dict, dst: Path, _cache_dir: Path, _fmt: str) -> bool:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"tracks:" + str(len(project.get("tracks") or [])).encode())
        return True


def test_editor_render_track_only_renders_selected_track(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    """导出单轨：只把选中的那条音轨交给渲染器，其它音轨不参与。"""
    repo = _repo(wtmp, monkeypatch)
    monkeypatch.setattr(config, "EDITOR_DIR", wtmp / "editor")
    monkeypatch.setattr(config, "EDITOR_CACHE_DIR", wtmp / "editor" / "cache")
    project = {
        "id": "proj_1",
        "title": "测试工程",
        "duration": 12.0,
        "sample_rate": 44100,
        "tracks": [
            {"id": "tr_vocal", "name": "翻唱成品", "type": "audio", "clips": [{"id": "c1", "start": 0, "end": 12, "file": "a.wav"}]},
            {"id": "tr_bgm", "name": "伴奏", "type": "audio", "clip": [], "clips": []},
        ],
    }
    editor_repo = ListRepository(wtmp / "editor_projects.json")
    editor_repo.add(project)
    service = AudioEditorService(
        editor_repo,
        repo,
        None,  # type: ignore[arg-type]
        _FakeFfmpeg(),
        None,  # type: ignore[arg-type]
        None,
        vocal_enhancement=_FakeEnhancer(),
        pymss=_FakePymss(),
    )
    service._audio = _FakeAudioEngine()  # noqa: SLF001 - 替换真实 ffmpeg 渲染

    rendered = service.render_track("proj_1", "tr_vocal", "wav")

    assert rendered is not None and rendered.is_file()
    # 只有 1 条音轨被渲染，说明没有把整轨混音当作单轨导出
    assert rendered.read_bytes() == b"tracks:1"
    assert service.render_track("proj_1", "missing", "wav") is None


def test_run_workflow_fails_when_save_node_has_no_input(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    repo = _repo(wtmp, monkeypatch)
    graph = _graph(connect_save=False)
    work = _work_record(wtmp, graph)
    repo.add(work)

    service = _run_service(repo)
    service._run_workflow(work["id"])  # noqa: SLF001

    saved = repo.get(work["id"])
    assert saved is not None
    assert saved["status"] == "failed"
    assert saved.get("error")


# ---- 扩展节点：结构 / 音频处理 ----
def test_validate_new_processing_nodes() -> None:
    """新增的音频处理 / 结构节点通过图校验。"""
    graph = {
        "nodes": [
            {"id": "i", "type": "input", "params": {}},
            {"id": "fx", "type": "effect", "params": {"effect": "eq"}},
            {"id": "t", "type": "trim", "params": {"start": 0, "end": 10}},
            {"id": "f", "type": "fade", "params": {}},
            {"id": "p", "type": "pitch", "params": {"semitones": 2}},
            {"id": "st", "type": "stretch", "params": {"speed": 1.2}},
            {"id": "n", "type": "normalize", "params": {"target_lufs": -14}},
            {"id": "o", "type": "output", "params": {}},
        ],
        "edges": [
            {"id": "e1", "from": {"node": "i", "port": "audio"}, "to": {"node": "fx", "port": "audio"}},
            {"id": "e2", "from": {"node": "fx", "port": "audio"}, "to": {"node": "t", "port": "audio"}},
            {"id": "e3", "from": {"node": "t", "port": "audio"}, "to": {"node": "f", "port": "audio"}},
            {"id": "e4", "from": {"node": "f", "port": "audio"}, "to": {"node": "p", "port": "audio"}},
            {"id": "e5", "from": {"node": "p", "port": "audio"}, "to": {"node": "st", "port": "audio"}},
            {"id": "e6", "from": {"node": "st", "port": "audio"}, "to": {"node": "n", "port": "audio"}},
            {"id": "e7", "from": {"node": "n", "port": "audio"}, "to": {"node": "o", "port": "audio"}},
        ],
    }
    assert validate_graph(graph) is None


def test_validate_merge_and_concat_allow_multi_input() -> None:
    """多轨混合 / 顺序拼接允许一个输入端口接入多路（fan-out → fan-in）。"""
    graph = {
        "nodes": [
            {"id": "i", "type": "input", "params": {}},
            {"id": "a", "type": "convert", "params": {}},
            {"id": "b", "type": "convert", "params": {}},
            {"id": "g", "type": "merge", "params": {}},
            {"id": "o", "type": "output", "params": {}},
        ],
        "edges": [
            {"id": "e1", "from": {"node": "i", "port": "audio"}, "to": {"node": "a", "port": "audio"}},
            {"id": "e2", "from": {"node": "i", "port": "audio"}, "to": {"node": "b", "port": "audio"}},
            {"id": "e3", "from": {"node": "a", "port": "audio"}, "to": {"node": "g", "port": "audio"}},
            {"id": "e4", "from": {"node": "b", "port": "audio"}, "to": {"node": "g", "port": "audio"}},
            {"id": "e5", "from": {"node": "g", "port": "audio"}, "to": {"node": "o", "port": "audio"}},
        ],
    }
    assert validate_graph(graph) is None


def test_run_workflow_merges_two_converted_vocals(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    """男女声分别转换后再合并为一首歌（fan-out → convert ×2 → merge → 保存）。"""
    repo = _repo(wtmp, monkeypatch)
    monkeypatch.setattr(config, "pymss_model_ready", lambda *_args, **_kwargs: True)
    fake = _FakePymssMultiStem()
    graph = {
        "name": "男女声翻唱",
        "nodes": [
            {"id": "i", "type": "input", "x": 0, "y": 0, "params": {}},
            {"id": "s", "type": "separate", "x": 1, "y": 0, "params": {"engine": "pymss", "model": "multi_stem_model", "device": "auto"}},
            {"id": "c1", "type": "convert", "x": 2, "y": 0, "params": {"model_id": "mdl_a", "auto_high_pitch_guard": False, "device": "auto"}},
            {"id": "c2", "type": "convert", "x": 2, "y": 1, "params": {"model_id": "mdl_b", "auto_high_pitch_guard": False, "device": "auto"}},
            {"id": "g", "type": "merge", "x": 3, "y": 0, "params": {}},
            {"id": "o", "type": "output", "x": 4, "y": 0, "params": {"file_template": "%filename%_%stem%_%model%"}},
        ],
        "edges": [
            {"id": "e1", "from": {"node": "i", "port": "audio"}, "to": {"node": "s", "port": "audio"}},
            {"id": "e2", "from": {"node": "s", "port": "vocals"}, "to": {"node": "c1", "port": "audio"}},
            {"id": "e3", "from": {"node": "s", "port": "stem:drums"}, "to": {"node": "c2", "port": "audio"}},
            {"id": "e4", "from": {"node": "c1", "port": "audio"}, "to": {"node": "g", "port": "audio"}},
            {"id": "e5", "from": {"node": "c2", "port": "audio"}, "to": {"node": "g", "port": "audio"}},
            {"id": "e6", "from": {"node": "g", "port": "audio"}, "to": {"node": "o", "port": "audio"}},
        ],
    }
    source = wtmp / "song.wav"
    source.write_bytes(b"song")
    order = topological_order(graph["nodes"], graph["edges"]) or []
    repo.add(
        {
            "id": "wrk_merge",
            "title": "男女声翻唱",
            "mode": "workflow",
            "workflow": "workflow",
            "status": "queue",
            "progress": 0,
            "source_path": str(source),
            "workflow_graph": graph,
            "workflow_models": {
                "c1": {"name": "Model A", "framework": "rvc", "main_model_path": "/m/a.pth", "main_config_path": "", "diffusion_model_path": "", "diffusion_config_path": "", "index_path": "", "params": {"auto_high_pitch_guard": False, "device": "auto"}},
                "c2": {"name": "Model B", "framework": "rvc", "main_model_path": "/m/b.pth", "main_config_path": "", "diffusion_model_path": "", "diffusion_config_path": "", "index_path": "", "params": {"auto_high_pitch_guard": False, "device": "auto"}},
            },
            "steps": [{"key": key, "label": key, "status": "wait"} for key in order],
            "params": {},
            "vocal_enhancement": {},
            "preprocess": {},
        }
    )

    service = ConversionService(
        repo,
        _FakeFfmpeg(),
        _FakeUvr(),
        _FakeEngines(),
        vocal_enhancement=_FakeEnhancer(),
        pymss=fake,
    )
    service._run_workflow("wrk_merge")  # noqa: SLF001

    saved = repo.get("wrk_merge")
    assert saved is not None
    assert saved["status"] == "done", saved.get("error")
    assert Path(saved["output_path"]).read_bytes() == b"merged:converted-vocals+converted-drums"


def test_run_workflow_applies_effect_and_trim(wtmp: Path, monkeypatch) -> None:  # noqa: ANN001
    """音频效果 / 裁剪节点在推理后按顺序应用。"""
    repo = _repo(wtmp, monkeypatch)
    graph = {
        "name": "处理链",
        "nodes": [
            {"id": "i", "type": "input", "x": 0, "y": 0, "params": {}},
            {"id": "fx", "type": "effect", "x": 1, "y": 0, "params": {"effect": "eq", "frequency_hz": 1000, "gain_db": 2, "q": 1}},
            {"id": "t", "type": "trim", "x": 2, "y": 0, "params": {"start": 1, "end": 5, "fade": 0.2}},
            {"id": "o", "type": "output", "x": 3, "y": 0, "params": {}},
        ],
        "edges": [
            {"id": "e1", "from": {"node": "i", "port": "audio"}, "to": {"node": "fx", "port": "audio"}},
            {"id": "e2", "from": {"node": "fx", "port": "audio"}, "to": {"node": "t", "port": "audio"}},
            {"id": "e3", "from": {"node": "t", "port": "audio"}, "to": {"node": "o", "port": "audio"}},
        ],
    }
    source = wtmp / "song.wav"
    source.write_bytes(b"song")
    order = topological_order(graph["nodes"], graph["edges"]) or []
    repo.add(
        {
            "id": "wrk_fx",
            "title": "处理链",
            "mode": "workflow",
            "workflow": "workflow",
            "status": "queue",
            "progress": 0,
            "source_path": str(source),
            "workflow_graph": graph,
            "workflow_models": {},
            "steps": [{"key": key, "label": key, "status": "wait"} for key in order],
            "params": {},
            "vocal_enhancement": {},
            "preprocess": {},
        }
    )

    service = _run_service(repo)
    service._run_workflow("wrk_fx")  # noqa: SLF001

    saved = repo.get("wrk_fx")
    assert saved is not None
    assert saved["status"] == "done", saved.get("error")
    # 效果（fx:eq:…）先应用，随后裁剪（trim:4.0:…）叠加。
    assert Path(saved["output_path"]).read_bytes() == b"trim:4.0:fx:eq:song"
