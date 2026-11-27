"""编辑器成品归档到作品库的用例测试。"""

from __future__ import annotations

import shutil
import wave
from pathlib import Path

from application.work_service import WorkService


class _Repo:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, item: dict) -> dict:
        self.items.append(dict(item))
        return item

    def all(self) -> list[dict]:
        return list(self.items)

    def get(self, item_id: str):
        return next((item for item in self.items if item.get("id") == item_id), None)

    def update(self, item_id: str, item: dict) -> None:
        for index, current in enumerate(self.items):
            if current.get("id") == item_id:
                self.items[index] = dict(item)
                return

    def remove(self, item_id: str) -> None:
        self.items = [item for item in self.items if item.get("id") != item_id]


class _Files:
    def __init__(self, root: Path) -> None:
        self.root = root

    def work_dir(self, work_id: str) -> Path:
        return self.root / work_id

    def remove_tree(self, path: Path) -> None:
        shutil.rmtree(path, ignore_errors=True)


def _write_wav(path: Path, seconds: float = 3.4) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(b"\x00\x00" * int(44100 * seconds))


def test_import_rendered_audio_archives_a_playable_work(tmp_path: Path) -> None:
    source = tmp_path / "render.wav"
    _write_wav(source)
    repo = _Repo()
    works_root = tmp_path / "works"
    service = WorkService(repo, None, None, None, files=_Files(works_root))  # type: ignore[arg-type]

    work = service.import_rendered_audio(
        source, title="我的编辑成品", duration=3.4
    )

    assert work is not None
    assert work["status"] == "done"
    assert work["title"] == "我的编辑成品"
    assert work["model"] == "音频编辑器"
    assert work["workflow"] == "audio_editor"
    assert work["duration"] == "00:03"
    assert work["format"] == "WAV"
    output = Path(str(work["output_path"]))
    assert output.is_file()
    assert output.read_bytes() == source.read_bytes()
    assert output.parent.parent == works_root
    assert repo.get(str(work["id"])) is not None
    assert work["steps"][0]["key"] == "editor"


def test_import_rendered_audio_rejects_non_audio(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("not audio", encoding="utf-8")
    repo = _Repo()
    service = WorkService(
        repo, None, None, None, files=_Files(tmp_path / "works")
    )  # type: ignore[arg-type]

    assert service.import_rendered_audio(source, title="无效") is None
    assert repo.items == []
