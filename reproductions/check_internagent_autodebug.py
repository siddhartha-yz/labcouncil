"""Run byte-identical upstream baseline twice, without exposing credentials."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "workspaces/upstreams/internagent"
OUTPUT = ROOT / "reproductions/2026-10-06-internagent-autodebug"
WORK = ROOT / "workspaces/internagent-autodebug"
PYTHON = ROOT / "workspaces/freephdlabor-author-env/bin/python"


def main():
    OUTPUT.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD"))}
    env.update(PYTHON_DOTENV_DISABLED="1", CUDA_VISIBLE_DEVICES="",
               OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    original = SOURCE / "tasks/AutoDebug/code/experiment.py"
    manifest = {"commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True).strip(),
        "source_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
        "environment": json.loads(subprocess.check_output(
            [str(PYTHON), "-c", "import sys,torch,sklearn,numpy,json; print(json.dumps(dict(python=sys.version,torch=torch.__version__,sklearn=sklearn.__version__,numpy=numpy.__version__,cuda_available=torch.cuda.is_available())))"],
            cwd=ROOT, env=env, text=True)), "attempts": []}
    for n in (1, 2):
        folder = WORK / f"attempt-{n:02d}" / "code"
        folder.mkdir(parents=True, exist_ok=True)
        script = folder / "experiment.py"
        if (folder.parent / "final_info.json").exists():
            raise SystemExit("Refusing to overwrite an existing attempt")
        shutil.copyfile(original, script)
        proc = subprocess.run([str(PYTHON), str(script)], cwd=folder,
                              env=env, capture_output=True, text=True, timeout=60)
        (OUTPUT / f"attempt-{n:02d}-stdout.txt").write_text(proc.stdout)
        (OUTPUT / f"attempt-{n:02d}-stderr.txt").write_text(proc.stderr)
        entry = {"attempt": n, "exit_code": proc.returncode,
                 "copy_sha256": hashlib.sha256(script.read_bytes()).hexdigest()}
        result = folder.parent / "final_info.json"
        if result.exists():
            shutil.copyfile(result, OUTPUT / f"attempt-{n:02d}-result.json")
            values = json.loads(result.read_text())
            entry.update(result=values, finite_metrics=all(
                math.isfinite(values[k]) for k in ("mse", "r2", "mae")),
                training_under_30_seconds=values["training_time"] <= 30)
        manifest["attempts"].append(entry)
        (OUTPUT / "baseline-manifest.json").write_text(json.dumps(manifest, indent=2))
        print(json.dumps(entry), flush=True)
    proc = subprocess.run([str(PYTHON), "launch_discovery.py", "--help"],
                          cwd=SOURCE, env=env, capture_output=True, text=True, timeout=60)
    (OUTPUT / "launcher-help-stdout.txt").write_text(proc.stdout)
    (OUTPUT / "launcher-help-stderr.txt").write_text(proc.stderr)
    (OUTPUT / "launcher-help-result.json").write_text(json.dumps(
        {"exit_code": proc.returncode, "credentials_removed": True,
         "dotenv_disabled": True}, indent=2))
    print("Original launcher precheck exit:", proc.returncode)


if __name__ == "__main__":
    main()
