#!/usr/bin/env python3
"""Run unchanged pinned upstream meeting functions with a recorded DeepSeek client."""

import argparse
import datetime
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

from check_deepseek_connectivity import load_config, redact


COMMIT = "8a3a4fd9ccc0cd297bd523751e03bc9527c91832"
DECISION = "TEST_REVIEW_MAE_3SEEDS"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def source_hashes(root):
    return {str(path.relative_to(root)): digest(path) for path in sorted((root / "src").rglob("*.py"))}


def validate_summary(summary, evidence, second):
    try:
        report = json.loads(summary)
    except json.JSONDecodeError:
        blocks = re.findall(r"```json\s*\n(.*?)\n```", summary, flags=re.DOTALL)
        if len(blocks) == 1:
            outside = re.sub(r"```json\s*\n.*?\n```", "", summary, flags=re.DOTALL)
            for match in re.finditer(r"(?m)^\s*\{", outside):
                try:
                    json.JSONDecoder().raw_decode(outside[match.start():].lstrip())
                except json.JSONDecodeError:
                    continue
                raise ValueError("Summary contains an unambiguous-block violation: another JSON object")
            report = json.loads(blocks[0])
        elif blocks:
            raise ValueError("Summary must contain one unambiguous JSON object") from None
        else:
            candidates = []
            decoder = json.JSONDecoder()
            for match in re.finditer(r"(?m)^\s*\{", summary):
                suffix = summary[match.start():].lstrip()
                try:
                    value, end = decoder.raw_decode(suffix)
                except json.JSONDecodeError:
                    continue
                candidates.append((value, suffix[end:].strip()))
            if len(candidates) != 1 or candidates[0][1]:
                raise ValueError("Summary must contain one unambiguous trailing JSON object") from None
            report = candidates[0][0]
    if report.get("evidence_refs") != [evidence["evidence_id"]]:
        raise ValueError("Summary evidence mismatch")
    for model in ("linear", "baseline"):
        value = report["observed_mse"][model]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isclose(
                value, evidence["results"][0]["metrics"]["mse"][model], abs_tol=1e-4, rel_tol=1e-4):
            raise ValueError("Summary numerical mismatch")
    for field in ("limitations", "next_steps"):
        if not isinstance(report.get(field), list) or not report[field] or not all(
                isinstance(item, str) and item.strip() for item in report[field]):
            raise ValueError("Summary lacks limits or next steps")
    if report.get("new_experiments_executed") is not False:
        raise ValueError("Summary claims experiments that the meeting did not execute")
    if second and (report.get("decision_ids") != [DECISION]
                   or report.get("planned_seeds") != [7, 19, 31]
                   or report.get("planned_metrics") != ["mse", "mae", "median_absolute_error"]):
        raise ValueError("Follow-up summary does not reflect the review fixture")
    return report


class RecordedCompletions:
    def __init__(self, client, output, key, not_given):
        self.client, self.output, self.key, self.not_given = client, output, key, not_given
        self.calls, self.usage, self.meeting = 0, {}, ""

    def event(self, item):
        with (self.output / "api-events.jsonl").open("a") as file:
            file.write(json.dumps(redact(item, self.key), ensure_ascii=False) + "\n")

    def create(self, **kwargs):
        if self.calls >= 8 or kwargs["model"] != "deepseek-flash":
            raise ValueError("Meeting API budget or model violation")
        if kwargs.get("tools", self.not_given) is not self.not_given:
            raise ValueError("External meeting tools are disabled for this protocol")
        kwargs = {key: value for key, value in kwargs.items() if value is not self.not_given}
        kwargs.update(max_tokens=768, extra_body={"thinking": {"type": "disabled"}})
        self.calls += 1
        self.event({"type": "request", "meeting": self.meeting, "call_id": self.calls, "kwargs": kwargs})
        start = time.monotonic()
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as error:
            self.event({"type": "api_failure", "meeting": self.meeting, "call_id": self.calls,
                        "error_type": type(error).__name__, "elapsed_seconds": time.monotonic() - start})
            raise RuntimeError("Meeting API request failed; inspect redacted event metadata") from None
        body = response.model_dump(mode="json")
        self.event({"type": "response", "meeting": self.meeting, "call_id": self.calls,
                    "elapsed_seconds": round(time.monotonic() - start, 3),
                    "response": {key: body.get(key) for key in ("model", "choices", "usage", "created")}})
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self.usage[field] = self.usage.get(field, 0) + (body.get("usage") or {}).get(field, 0)
        if response.choices[0].finish_reason != "stop" or not response.choices[0].message.content:
            raise ValueError("Meeting response empty, interrupted, truncated, or contains unexpected tools")
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resume-first", type=Path,
                        help="Explicitly reassess a saved first meeting and run only the second")
    args = parser.parse_args()
    config = load_config(Path(".env"))
    if config["DEEPSEEK_MODEL"] != "deepseek-flash":
        print("Local model must be deepseek-flash; no request sent.")
        return 2
    upstream = args.upstream.resolve()
    commit = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    if commit != COMMIT:
        print("Upstream commit does not match protocol; no request sent.")
        return 2
    if subprocess.run(["git", "-C", str(upstream), "diff", "--quiet", "HEAD", "--", "src"]).returncode:
        print("Upstream source differs from the pinned commit; no request sent.")
        return 2
    previous = None
    if args.resume_first is not None:
        previous = json.loads((args.resume_first / "metadata.json").read_text())
        if (previous.get("api_calls") != 4 or previous.get("failure_type") != "JSONDecodeError"
                or previous.get("upstream_commit") != COMMIT or not previous.get("source_unchanged")):
            print("Unsupported first-meeting checkpoint; no request sent.")
            return 2
        shutil.copytree(args.resume_first, args.output_dir)
        shutil.copyfile(args.output_dir / "metadata.json", args.output_dir / "original-metadata.json")
    else:
        args.output_dir.mkdir(parents=True, exist_ok=False)
    source_before = source_hashes(upstream)
    metadata = {"started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "python": platform.python_version(), "upstream_commit": commit,
                "upstream_source_hashes_before": source_before, "script_sha256": digest(Path(__file__)),
                "evidence_sha256": digest(args.evidence), "request_limit": 8, "max_output_tokens": 768,
                "automatic_retries": 0, "decision_source": "prewritten_test_fixture",
                "human_confirmed": False, "scope": "Changed-model upstream meeting-function validation",
                "dependencies": sorted(f"{d.metadata['Name']}=={d.version}" for d in importlib.metadata.distributions())}
    save(args.output_dir / "metadata.json", metadata)
    sys.path.insert(0, str(upstream / "src"))
    os.environ["TIKTOKEN_CACHE_DIR"] = "/tmp/labcouncil-tiktoken-cache"
    recorder = None
    try:
        from openai import OpenAI, NOT_GIVEN
        from virtual_lab import Agent
        from virtual_lab.utils import load_summaries
        from tiktoken import get_encoding
        module = importlib.import_module("virtual_lab.run_meeting")
        get_encoding("cl100k_base")  # Warm the upstream tokenizer cache before any model request.
        client = OpenAI(api_key=config["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com",
                        timeout=45, max_retries=0)
        recorder = RecordedCompletions(client, args.output_dir, config["DEEPSEEK_API_KEY"], NOT_GIVEN)
        if previous is not None:
            recorder.calls, recorder.usage = previous["api_calls"], dict(previous["usage"])
            metadata["reassessment_source"] = str(args.resume_first)
            metadata["original_script_sha256"] = previous["script_sha256"]
        module.OpenAI = lambda: SimpleNamespace(chat=SimpleNamespace(completions=recorder))
        agents = [Agent(title, expertise, goal, role, "deepseek-flash") for title, expertise, goal, role in (
            ("Principal Investigator", "experimental design", "summarize evidence and bounded next steps", "chair the meeting"),
            ("Experimentalist", "regression experiments", "report only provided evidence", "explain the numerical result"),
            ("Methodologist", "validation and uncertainty", "identify limits without inventing work", "critique the evidence"))]
        evidence = json.loads(args.evidence.read_text())
        context = "Observed synthetic evidence; no new experiments are executed by this meeting: " + json.dumps(evidence)
        rules = (
            "Keep every response concise, under 180 words. Do not invent experiments or evidence.",
            "The final Principal Investigator summary must be ONLY valid JSON, without markdown fences, with fields "
            "evidence_refs (array), observed_mse (object with linear and baseline numbers), limitations (nonempty string array), "
            "next_steps (nonempty string array), planned_seeds (integer array), planned_metrics (string array), "
            "decision_ids (string array), new_experiments_executed (false). Copy observed MSE faithfully.",
        )
        metadata["meeting_checks"] = []
        if previous is not None:
            transcript = json.loads((args.output_dir / "meeting-1.json").read_text())
            counts = {agent.title: sum(turn["agent"] == agent.title and bool(turn["message"])
                      for turn in transcript) for agent in agents}
            if counts != {agents[0].title: 2, agents[1].title: 1, agents[2].title: 1}:
                raise ValueError("Saved first meeting has unexpected speaker count")
            parsed = validate_summary(transcript[-1]["message"], evidence, False)
            metadata["meeting_checks"].append({"meeting": "meeting-1", "passed": True,
                "agent_response_counts": counts, "api_calls": 4, "assessment": "offline under revised format contract",
                "validated_summary": parsed})
        for number in ((2,) if previous is not None else (1, 2)):
            name = f"meeting-{number}"
            recorder.meeting = name
            before = recorder.calls
            if number == 1:
                summaries = ()
                agenda = "Assess this one-seed clean synthetic experiment, distinguish observed MSE from scientific quality, and propose bounded validation."
            else:
                summaries = load_summaries([args.output_dir / "meeting-1.json"])
                agenda = (f"TEST REVIEW FIXTURE {DECISION}, not a human-confirmed meeting decision: "
                          "Update the next-step plan to seeds 7,19,31 and metrics mse,mae,median_absolute_error. "
                          "Include decision_ids=['TEST_REVIEW_MAE_3SEEDS'], planned_seeds=[7,19,31], "
                          "planned_metrics=['mse','mae','median_absolute_error']. These new experiments have NOT run. "
                          "Retain the supplied first-round MSE as observed evidence and its limitations.")
            save(args.output_dir / f"{name}-inputs.json", {"agenda": agenda, "rules": rules,
                 "summaries": summaries, "contexts": [context], "num_rounds": 1,
                 "agents": [agent.prompt for agent in agents]})
            summary = module.run_meeting(meeting_type="team", agenda=agenda, save_dir=args.output_dir,
                save_name=name, team_lead=agents[0], team_members=tuple(agents[1:]), num_rounds=1,
                temperature=0, pubmed_search=False, contexts=(context,), summaries=summaries,
                agenda_rules=rules, return_summary=True)
            discussion = json.loads((args.output_dir / f"{name}.json").read_text())
            counts = {agent.title: sum(turn["agent"] == agent.title and bool(turn["message"])
                      for turn in discussion) for agent in agents}
            if counts != {agents[0].title: 2, agents[1].title: 1, agents[2].title: 1} or recorder.calls - before != 4:
                raise ValueError("Unexpected upstream speaking order or API call count")
            if summary != discussion[-1]["message"] or not (args.output_dir / f"{name}.md").exists():
                raise ValueError("Saved meeting and returned summary differ")
            if number == 2 and summaries != (json.loads((args.output_dir / "meeting-1.json").read_text())[-1]["message"],):
                raise ValueError("Follow-up input did not use the saved first summary")
            parsed = validate_summary(summary, evidence, number == 2)
            metadata["meeting_checks"].append({"meeting": name, "passed": True,
                "agent_response_counts": counts, "api_calls": recorder.calls - before,
                "validated_summary": parsed})
        metadata["status"] = "passed"
    except Exception as error:
        metadata["status"] = "failed"
        metadata["failure_type"] = type(error).__name__
        # Omit arbitrary SDK exception strings; recorded request/response data excludes credentials.
    finally:
        metadata["upstream_source_hashes_after"] = source_hashes(upstream)
        metadata["source_unchanged"] = metadata["upstream_source_hashes_after"] == source_before
        if not metadata["source_unchanged"]:
            metadata["status"] = "failed"
        metadata["api_calls"] = recorder.calls if recorder else 0
        metadata["usage"] = recorder.usage if recorder else {}
        save(args.output_dir / "metadata.json", redact(metadata, config["DEEPSEEK_API_KEY"]))
    print(json.dumps({field: metadata.get(field) for field in ("status", "api_calls", "usage", "source_unchanged", "failure_type")}, indent=2))
    return 0 if metadata["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
