#!/usr/bin/env python3
"""Bounded two-round real-model workflow, with a clearly labeled review fixture."""

import argparse
import csv
import datetime
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import shutil
import statistics
import sys
import time
import urllib.error
import urllib.request

from check_deepseek_connectivity import ENDPOINT, load_config, redact


EXPECTED = {
    1: {"task_version": 1, "seeds": [7], "outlier_fraction": 0.0, "metrics": ["mse"]},
    2: {"task_version": 2, "seeds": [7, 19, 31], "outlier_fraction": 0.1,
        "metrics": ["mse", "mae", "median_absolute_error"]},
}
REVIEW_FIXTURE = (
    "TEST REVIEW FIXTURE, not a real human meeting decision. Task version 2: "
    "A single clean-data run is insufficient. Run seeds 7, 19, 31, with 10% test-label "
    "outliers of magnitude 10, keeping training data unchanged. Report mse, mae and "
    "median_absolute_error. Create fresh evidence and preserve round 1. Do not claim "
    "this synthetic exercise establishes scientific quality."
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def metric_values(errors, names):
    methods = {
        "mse": lambda: statistics.mean(e * e for e in errors),
        "mae": lambda: statistics.mean(abs(e) for e in errors),
        "median_absolute_error": lambda: statistics.median(abs(e) for e in errors),
    }
    return {name: methods[name]() for name in names}


def run_experiment(root, evidence_id, parameters):
    directory = root / "artifacts" / evidence_id
    directory.mkdir(parents=True, exist_ok=False)
    results, files = [], []
    for seed in parameters["seeds"]:
        rng = random.Random(seed)
        train = [(rng.uniform(-2, 2), rng.gauss(0, 0.4)) for _ in range(40)]
        train = [(x, 2 + 3 * x + noise) for x, noise in train]
        test = [(rng.uniform(-2, 2), rng.gauss(0, 0.4)) for _ in range(100)]
        test = [(x, 2 + 3 * x + noise) for x, noise in test]
        indices = list(range(100))
        rng.shuffle(indices)
        for index in indices[:round(100 * parameters["outlier_fraction"])]:
            x, y = test[index]
            test[index] = (x, y + rng.choice((-10, 10)))
        x_bar = statistics.mean(x for x, _ in train)
        y_bar = statistics.mean(y for _, y in train)
        slope = sum((x - x_bar) * (y - y_bar) for x, y in train) / sum(
            (x - x_bar) ** 2 for x, _ in train)
        intercept = y_bar - slope * x_bar
        errors_linear = [intercept + slope * x - y for x, y in test]
        errors_baseline = [y_bar - y for _, y in test]
        linear = metric_values(errors_linear, parameters["metrics"])
        baseline = metric_values(errors_baseline, parameters["metrics"])
        results.append({"seed": seed, "metrics": {
            name: {"linear": linear[name], "baseline": baseline[name]}
            for name in parameters["metrics"]}})
        path = directory / f"seed-{seed}.csv"
        with path.open("w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(("split", "x", "y", "linear_prediction", "baseline_prediction"))
            for split, rows in (("train", train), ("test", test)):
                for x, y in rows:
                    writer.writerow((split, x, y, intercept + slope * x, y_bar))
        files.append({"seed": seed, "path": str(path.relative_to(root)), "sha256": digest(path)})
    artifact = {"evidence_id": evidence_id, "parameters": parameters,
                "results": results, "files": files}
    path = directory / "experiment.json"
    write_json(path, artifact)
    return artifact, {"path": str(path.relative_to(root)), "sha256": digest(path)}


def verify_artifact(root, artifact, manifest):
    if digest(root / manifest["path"]) != manifest["sha256"]:
        raise ValueError("Experiment manifest hash mismatch")
    comparisons = []
    for entry, expected in zip(artifact["files"], artifact["results"], strict=True):
        path = root / entry["path"]
        if digest(path) != entry["sha256"]:
            raise ValueError("CSV hash mismatch")
        with path.open(newline="") as file:
            rows = list(csv.DictReader(file))
        train = [r for r in rows if r["split"] == "train"]
        test = [r for r in rows if r["split"] == "test"]
        if len(train) != 40 or len(test) != 100:
            raise ValueError("Unexpected split size")
        xs = [float(r["x"]) for r in train]
        ys = [float(r["y"]) for r in train]
        # Independent raw-moment fit, rather than reuse the experiment's centered fit.
        n = len(xs)
        sx, sy = math.fsum(xs), math.fsum(ys)
        slope = (n * math.fsum(x * y for x, y in zip(xs, ys)) - sx * sy) / (
            n * math.fsum(x * x for x in xs) - sx * sx)
        intercept, baseline = (sy - slope * sx) / n, sy / n
        errors = {"linear": [], "baseline": []}
        for row in test:
            prediction = intercept + slope * float(row["x"])
            if not math.isclose(prediction, float(row["linear_prediction"]), abs_tol=1e-9):
                raise ValueError("Saved linear prediction does not match training fit")
            if not math.isclose(baseline, float(row["baseline_prediction"]), abs_tol=1e-9):
                raise ValueError("Saved baseline does not match training mean")
            errors["linear"].append(prediction - float(row["y"]))
            errors["baseline"].append(baseline - float(row["y"]))
        computed = {}
        for metric in artifact["parameters"]["metrics"]:
            computed[metric] = {}
            for model, values in errors.items():
                absolute = sorted(abs(e) for e in values)
                if metric == "mse":
                    value = math.fsum(e * e for e in values) / len(values)
                elif metric == "mae":
                    value = math.fsum(absolute) / len(absolute)
                else:
                    middle = len(absolute) // 2
                    value = (absolute[middle - 1] + absolute[middle]) / 2
                if not math.isclose(value, expected["metrics"][metric][model],
                                    abs_tol=1e-9, rel_tol=1e-9):
                    raise ValueError("Saved metric does not match recomputation")
                computed[metric][model] = value
        comparisons.append({"seed": entry["seed"], "metrics": computed})
    return {"evidence_id": artifact["evidence_id"], "verified": True,
            "checks": ["manifest_hash", "csv_hashes", "split_sizes", "training_fit",
                       "saved_predictions", "recomputed_metrics"], "results": comparisons}


def tool_schema(name):
    if name == "run_regression_experiment":
        fields = {"task_version": {"type": "integer"},
                  "seeds": {"type": "array", "items": {"type": "integer"}},
                  "outlier_fraction": {"type": "number"},
                  "metrics": {"type": "array", "items": {"type": "string"}}}
        description = "Execute bounded synthetic regression; save CSV, hashes and metrics."
    else:
        fields = {"evidence_id": {"type": "string"}}
        description = "Independently verify saved evidence hashes, predictions and metrics."
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": fields,
                           "required": list(fields), "additionalProperties": False}}}


def validate_report(report, version, artifact, role, known_ids=None):
    if report.get("task_version") != version:
        raise ValueError("Report task version mismatch")
    refs = report.get("evidence_refs")
    allowed = set(known_ids or [artifact["evidence_id"]])
    if (not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs)
            or len(set(refs)) != len(refs) or artifact["evidence_id"] not in refs
            or not set(refs).issubset(allowed)):
        raise ValueError("Report evidence references mismatch")
    limitations = report.get("limitations")
    if not isinstance(limitations, list) or not limitations or not all(
            isinstance(item, str) and item.strip() for item in limitations):
        raise ValueError("Report must include limitations")
    if role == "reviewer":
        if report.get("verified") is not True:
            raise ValueError("Reviewer did not confirm successful verification")
        return
    expected = {(r["seed"], name): values for r in artifact["results"]
                for name, values in r["metrics"].items()}
    observed = {}
    for observation in report.get("observations", []):
        pair = (observation["seed"], observation["metric"])
        if pair in observed or pair not in expected:
            raise ValueError("Duplicate or unexpected observation")
        for model in ("linear", "baseline"):
            value = observation[model]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Non-numeric observation")
            if not math.isclose(value, expected[pair][model], abs_tol=1e-4, rel_tol=1e-4):
                raise ValueError("Report metric differs from evidence")
        observed[pair] = observation
    if set(observed) != set(expected) or not isinstance(report.get("conclusion"), str) or not report["conclusion"].strip():
        raise ValueError("Incomplete report")


class Workflow:
    def __init__(self, root, config, state):
        self.root, self.config, self.state = root, config, state

    def save(self):
        write_json(self.root / "state.json", redact(self.state, self.config["DEEPSEEK_API_KEY"]))

    def event(self, event):
        event = redact(event, self.config["DEEPSEEK_API_KEY"])
        with (self.root / "events.jsonl").open("a") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")

    def call(self, phase, messages, tool, require_tool=False):
        if self.state["api_calls"] + self.state.get("prior_api_calls", 0) >= 12:
            raise ValueError("API request budget exhausted")
        if len(json.dumps(messages)) > 40000:
            raise ValueError("Context character budget exhausted")
        payload = {"model": self.state["model"], "messages": messages, "tools": [tool],
                   "thinking": {"type": "disabled"}, "temperature": 0, "max_tokens": 2048,
                   "stream": False, "response_format": {"type": "json_object"}}
        payload["tool_choice"] = (
            {"type": "function", "function": {"name": tool["function"]["name"]}}
            if require_tool else "auto")
        self.state["api_calls"] += 1
        self.save()
        call_id = self.state["api_calls"]
        self.event({"type": "api_request", "phase": phase, "call_id": call_id, "payload": payload})
        request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.config["DEEPSEEK_API_KEY"]}, method="POST")
        start = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                status, body = response.status, json.load(response)
        except urllib.error.HTTPError as error:
            self.event({"type": "api_error", "phase": phase, "http_status": error.code,
                        "call_id": call_id, "elapsed_seconds": time.monotonic() - start})
            raise RuntimeError(f"Provider HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            self.event({"type": "api_error", "phase": phase, "failure": "transport_error",
                        "call_id": call_id, "elapsed_seconds": time.monotonic() - start})
            raise RuntimeError("API transport failure") from None
        self.event({"type": "api_response", "phase": phase, "call_id": call_id,
                    "elapsed_seconds": round(time.monotonic() - start, 3), "http_status": status,
                    "response": {k: body.get(k) for k in ("model", "choices", "usage", "created")}})
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self.state["usage"][field] += body.get("usage", {}).get(field, 0)
        self.save()
        choice = body["choices"][0]
        if choice["finish_reason"] not in ("stop", "tool_calls"):
            raise ValueError("Response interrupted or truncated")
        message = {k: v for k, v in choice["message"].items()
                   if k in ("role", "content", "tool_calls", "reasoning_content") and v is not None}
        return message

    def phase(self, version, role):
        phase = f"round-{version}-{role}"
        if role == "executor":
            if version == 1:
                messages = [{"role": "system", "content": (
                    "You are the experiment executor. You must use the provided tool, then return "
                    "only a JSON report: task_version (integer), evidence_refs (array of experiment IDs), "
                    "observations (one object per seed/metric with seed, metric, linear, baseline), "
                    "conclusion (string), limitations (nonempty array of strings). Copy numeric results "
                    "faithfully. This is a synthetic workflow test, not proof of scientific quality.")},
                    {"role": "user", "content": "Execute task version 1 using exactly these tool parameters: " + json.dumps(EXPECTED[1])}]
            else:
                messages = self.state["executor_history"] + [{"role": "user", "content": REVIEW_FIXTURE}]
            tool_name = "run_regression_experiment"
        else:
            artifact = self.state["artifacts"][-1]
            messages = [{"role": "system", "content": (
                "You are an evidence reviewer. Call verify_evidence before reporting. Return only JSON: "
                "task_version (integer), evidence_refs (array of verified IDs), verified (boolean), "
                "limitations (nonempty array of strings). A passing arithmetic check does not establish "
                "scientific usefulness or independent model judgment.")}, {"role": "user", "content": json.dumps({
                    "task_version": version, "executor_report": self.state["reports"][f"round-{version}-executor"],
                    "evidence_id": artifact["evidence_id"]})}]
            tool_name = "verify_evidence"
        tool_count = 0
        for _ in range(3):
            message = self.call(phase, messages, tool_schema(tool_name), require_tool=not tool_count)
            messages.append(message)
            calls = message.get("tool_calls", [])
            if calls:
                for call in calls:
                    tool_count += 1
                    if tool_count > 2 or call["function"]["name"] != tool_name:
                        raise ValueError("Tool budget or allowlist violation")
                    arguments = json.loads(call["function"]["arguments"])
                    if role == "executor":
                        if arguments != EXPECTED[version] or type(arguments.get("task_version")) is not int:
                            raise ValueError("Tool parameters do not match task version")
                        if tool_count != 1:
                            raise ValueError("Duplicate experiment request")
                        evidence_id = f"experiment-{len(self.state['artifacts']) + 1:04d}"
                        artifact, manifest = run_experiment(self.root, evidence_id, arguments)
                        self.state["artifacts"].append(artifact)
                        self.state["manifests"][evidence_id] = manifest
                        result = artifact
                    else:
                        artifact = self.state["artifacts"][-1]
                        if arguments != {"evidence_id": artifact["evidence_id"]}:
                            raise ValueError("Unknown or stale evidence ID")
                        result = verify_artifact(self.root, artifact, self.state["manifests"][artifact["evidence_id"]])
                    self.state["tool_calls"] += 1
                    self.save()
                    self.event({"type": "tool_result", "phase": phase,
                                "tool": tool_name, "arguments": arguments, "result": result})
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
                continue
            if not tool_count:
                raise ValueError("Model returned a report without executing the required tool")
            report = json.loads(message.get("content", ""))
            validate_report(report, version, self.state["artifacts"][-1], role,
                            [item["evidence_id"] for item in self.state["artifacts"]])
            self.state["reports"][phase] = report
            if role == "executor":
                self.state["executor_history"] = messages
            write_json(self.root / f"{phase}.json", report)
            self.save()
            return
        raise ValueError("Phase API request limit exhausted")

    def run(self, stage):
        if stage == "continue" and self.state["status"] == "completed":
            return {"status": "already_completed", "new_api_calls": 0, "new_tool_calls": 0}
        if stage == "reassess":
            if self.state.get("failure_message") != "Report evidence references mismatch":
                raise ValueError("Reassessment supports only the recorded citation validator failure")
            responses = [json.loads(line) for line in (self.root / "events.jsonl").read_text().splitlines()]
            candidates = [event for event in responses if event.get("type") == "api_response"
                          and event.get("phase") == "round-2-executor"]
            report = json.loads(candidates[-1]["response"]["choices"][0]["message"]["content"])
            artifact = self.state["artifacts"][-1]
            validate_report(report, 2, artifact, "executor",
                            [item["evidence_id"] for item in self.state["artifacts"]])
            self.state["reports"]["round-2-executor"] = report
            write_json(self.root / "round-2-executor.json", report)
            self.event({"type": "offline_reassessment", "source_call_id": candidates[-1]["call_id"],
                        "reason": "Permit accurate registered historical evidence references",
                        "new_experiments": 0, "new_executor_api_calls": 0})
            self.phase(2, "reviewer")
            self.state["status"] = "completed"
        elif stage == "first":
            self.phase(1, "executor")
            self.phase(1, "reviewer")
            self.state["status"] = "meeting_ready"
        else:
            if self.state["status"] != "meeting_ready":
                raise ValueError("Continuation requires a completed first round")
            self.state["decision"] = {"decision_source": "prewritten_test_fixture",
                "human_confirmed": False, "task_version": 2, "content": REVIEW_FIXTURE}
            self.save()
            self.phase(2, "executor")
            self.phase(2, "reviewer")
            self.state["status"] = "completed"
        self.save()
        return {"status": self.state["status"], "api_calls": self.state["api_calls"],
                "tool_calls": self.state["tool_calls"], "usage": self.state["usage"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("first", "continue", "reassess"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path,
                        help="Copy a failed checkpoint for explicit offline reassessment")
    parser.add_argument("--prior-api-calls", type=int, default=0,
                        help="Requests consumed by previous attempts under the shared 12-call budget")
    args = parser.parse_args()
    try:
        config = load_config(Path(".env"))
        if not 0 <= args.prior_api_calls < 12:
            raise ValueError("Invalid prior request count")
        if config["DEEPSEEK_MODEL"] != "deepseek-flash":
            raise ValueError("Protocol requires deepseek-flash")
        root = args.output_dir
        if args.stage == "first":
            root.mkdir(parents=True, exist_ok=False)
            state = {"status": "running", "model": "deepseek-flash", "python": platform.python_version(),
                "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "script_sha256": digest(Path(__file__)),
                "config_loader_sha256": digest(Path(__file__).with_name("check_deepseek_connectivity.py")),
                "api_calls": 0, "prior_api_calls": args.prior_api_calls,
                "tool_calls": 0, "artifacts": [], "manifests": {}, "reports": {},
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        else:
            if args.stage == "reassess":
                if args.source_dir is None or root.exists():
                    raise ValueError("Reassessment requires a source and a fresh output directory")
                shutil.copytree(args.source_dir, root)
            state = json.loads((root / "state.json").read_text())
            if args.stage == "reassess":
                state["reassessment_source"] = str(args.source_dir)
                state["original_script_sha256"] = state["script_sha256"]
                state["script_sha256"] = digest(Path(__file__))
            elif state["script_sha256"] != digest(Path(__file__)):
                raise ValueError("Workflow script changed between stages")
            if state["config_loader_sha256"] != digest(Path(__file__).with_name("check_deepseek_connectivity.py")):
                raise ValueError("Configuration loader changed between stages")
            for artifact in state["artifacts"]:
                verify_artifact(root, artifact, state["manifests"][artifact["evidence_id"]])
        workflow = Workflow(root, config, state)
        try:
            result = workflow.run(args.stage)
        except (ValueError, RuntimeError, KeyError, IndexError, TypeError, OSError) as error:
            state["status"] = "failed"
            # Only fixed local diagnostic strings; HTTP payloads and credentials are not printed.
            state["failure_type"] = type(error).__name__
            state["failure_message"] = redact(str(error), config["DEEPSEEK_API_KEY"])
            workflow.event({"type": "workflow_failure", "failure_type": type(error).__name__,
                            "failure_message": state["failure_message"]})
            workflow.save()
            print("Workflow failed; preserved events and partial state. Error type: " + type(error).__name__)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError):
        print("Configuration/checkpoint could not be loaded; credentials were not printed.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
