"""Offline experimental NumPy/protobuf probes; never changes installed packages.

Optional sources are existing site-packages directories. Only the named
packages are loaded from them, in child processes. This is a diagnostic, NOT
a production runtime layout or proof that the package metadata resolves.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def probe_header(sources: dict[str, str]) -> str:
    return "SOURCES = " + repr(sources) + "\n" + '''
import sys, importlib.abc, importlib.machinery
class SelectedPackageFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in SOURCES:
            return importlib.machinery.PathFinder.find_spec(fullname, [SOURCES[fullname]])
sys.meta_path.insert(0, SelectedPackageFinder())
def deny_network(event, args):
    if event in ('socket.connect', 'socket.sendto'):
        raise RuntimeError('Network disabled during compatibility probe')
sys.addaudithook(deny_network)
import numpy as np
import google.protobuf
from google.protobuf.internal import api_implementation
print('NumPy', np.__version__, np.__file__, flush=True)
print('protobuf', google.protobuf.__version__, google.protobuf.__file__, api_implementation.Type(), flush=True)
'''


def checks(root: Path) -> dict[str, tuple[Path, str]]:
    return {
        "uvr_onnx": (root, '''
from audio_separator.separator.architectures.mdx_separator import MDXSeparator
from audio_separator.separator.architectures.vr_separator import VRSeparator
import onnx, onnxruntime as ort
from onnx import helper, TensorProto
model = helper.make_model(helper.make_graph(
    [helper.make_node('Identity', ['x'], ['y'])], 'compatibility',
    [helper.make_tensor_value_info('x', TensorProto.FLOAT, [1, 4])],
    [helper.make_tensor_value_info('y', TensorProto.FLOAT, [1, 4])]),
    opset_imports=[helper.make_opsetid('', 17)])
model.ir_version = 8
blob = model.SerializeToString()
onnx.checker.check_model(onnx.load_model_from_string(blob))
session = ort.InferenceSession(blob, providers=['CPUExecutionProvider'])
x = np.arange(4, dtype=np.float32).reshape(1, 4)
np.testing.assert_array_equal(session.run(None, {'x': x})[0], x)
print('UVR VR/MDX imports and ONNX serialization/inference OK')
'''),
        "seedvc": (root / "engines/seed-vc", '''
import inference
from modules.length_regulator import InterpolateRegulator
from audiotools import AudioSignal
import librosa
x = (0.1*np.sin(2*np.pi*220*np.arange(16000)/16000)).astype(np.float32)
y = librosa.resample(x, orig_sr=16000, target_sr=24000)
mel = librosa.feature.melspectrogram(y=y, sr=24000, n_fft=1024, hop_length=256)
z = inference.crossfade(x.copy(), x.copy(), 320)
signal = AudioSignal(x, sample_rate=16000)
signal.stft()
assert np.isfinite(y).all() and np.isfinite(mel).all() and np.isfinite(z).all()
print('SeedVC imports, resample, mel, crossfade, AudioSignal STFT OK')
'''),
        "ddsp": (root / "engines/ddsp-svc", '''
from ddsp.vocoder import F0_Extractor, Volume_Extractor
import reflow.vocoder
x = (0.1*np.sin(2*np.pi*220*np.arange(16000)/16000)).astype(np.float32)
volume = Volume_Extractor(hop_size=160).extract(x)
for mode in ('dio', 'parselmouth'):
    f0 = F0_Extractor(mode, sample_rate=16000, hop_size=160).extract(x)
    assert np.isfinite(f0).all() and (f0 > 0).any()
    print(mode, len(f0), float(np.median(f0[f0 > 0])))
assert np.isfinite(volume).all()
print('DDSP imports, pitch and volume extraction OK')
'''),
        "tensorboard": (root, '''
import tempfile
from torch.utils.tensorboard import SummaryWriter
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
with tempfile.TemporaryDirectory(prefix='xb-tb-') as work:
    with SummaryWriter(work) as writer:
        writer.add_scalar('probe', 1.0, 1)
    events = EventAccumulator(work).Reload()
    assert events.Scalars('probe')[0].value == 1.0
print('TensorBoard scalar write/read OK')
'''),
        "tensorboardx": (root, '''
import tempfile
from tensorboardX import SummaryWriter
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
with tempfile.TemporaryDirectory(prefix='xb-tbx-') as work:
    with SummaryWriter(work) as writer:
        writer.add_scalar('probe', 1.0, 1)
    events = EventAccumulator(work).Reload()
    assert events.Scalars('probe')[0].value == 1.0
print('TensorBoardX scalar write/read OK')
'''),
    }


def run_probes(root: Path, sources: dict[str, str], timeout: int) -> dict:
    header = probe_header(sources)
    with tempfile.TemporaryDirectory(prefix="xb-compat-cache-") as cache:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                   HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", NUMBA_CACHE_DIR=cache)
        # Do not mask incompatibility by forcing the slower Python protobuf
        # implementation or disabling the generated-code version checks.
        env.pop("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", None)
        env.pop("TEMPORARILY_DISABLE_PROTOBUF_VERSION_CHECK", None)

        def run(item):
            name, (cwd, code) = item
            try:
                proc = subprocess.run([sys.executable, "-B", "-c", header + code], cwd=cwd,
                                      env=env, capture_output=True, encoding="utf-8", errors="replace",
                                      timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                return {"name": name, "ok": proc.returncode == 0, "exit_code": proc.returncode,
                        "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-6000:]}
            except (OSError, subprocess.SubprocessError) as exc:
                return {"name": name, "ok": False, "error": str(exc)}

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, item) for item in checks(root).items()]
            results = []
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
    return {"python": sys.executable, "sources": sources, "checks": sorted(results, key=lambda r: r["name"]),
            "ok": all(result["ok"] for result in results), "full_model_inference_tested": False,
            "package_resolution_tested": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    for name in ("numpy", "protobuf", "tensorboardx", "audiotools"):
        parser.add_argument(f"--{name}-source", type=Path)
    parser.add_argument("--timeout", type=int, default=55)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    sources = {}
    for package, source in (("numpy", args.numpy_source), ("tensorboardX", args.tensorboardx_source),
                            ("audiotools", args.audiotools_source)):
        if source:
            if not (source / package / "__init__.py").is_file():
                parser.error(f"{source} does not contain {package}")
            sources[package] = str(source.resolve())
    if args.protobuf_source:
        google = args.protobuf_source.resolve() / "google"
        if not (google / "protobuf" / "__init__.py").is_file():
            parser.error("protobuf source does not contain google/protobuf")
        sources.update({"google.protobuf": str(google), "google._upb": str(google)})
    report = run_probes(args.root.resolve(), sources, args.timeout)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
