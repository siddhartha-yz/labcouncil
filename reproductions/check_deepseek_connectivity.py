#!/usr/bin/env python3
"""One bounded DeepSeek smoke request; no credential or account logging."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import sys
import time
import urllib.error
import urllib.request


ENDPOINT = "https://api.deepseek.com/chat/completions"
PROMPT = "Reply with exactly LABCOUNCIL_OK. Do not include any other text."


def load_config(path):
    names = ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL")
    config = {name: os.environ.get(name) for name in names}
    seen = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].strip()
            name, separator, value = line.partition("=")
            name = name.strip()
            if separator and name in names:
                if name in seen:
                    raise ValueError("Duplicate configuration field")
                seen.add(name)
                values = shlex.split(value, comments=True)
                if len(values) != 1 or not values[0]:
                    raise ValueError("Empty or malformed configuration field")
                config[name] = values[0]
    if not config["DEEPSEEK_API_KEY"]:
        raise ValueError("DeepSeek key is missing")
    config["DEEPSEEK_MODEL"] = config["DEEPSEEK_MODEL"] or "deepseek-v4-pro"
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", config["DEEPSEEK_MODEL"]):
        raise ValueError("Malformed model name")
    return config


def redact(value, key):
    encoded = json.dumps(value, ensure_ascii=False).replace(key, "[REDACTED]")
    encoded = re.sub(r"sk-[0-9A-Za-z_-]{16,}", "[REDACTED]", encoded)
    return json.loads(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new attempt filename")
    try:
        config = load_config(args.env_file)
    except (OSError, ValueError):
        print("DeepSeek configuration could not be loaded; credentials were not printed.")
        return 2
    key = config["DEEPSEEK_API_KEY"]
    payload = {
        "model": config["DEEPSEEK_MODEL"],
        "messages": [{"role": "user", "content": PROMPT}],
        "thinking": {"type": "disabled"},
        "max_tokens": 128,
        "temperature": 0,
        "stream": False,
    }
    record = {
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "python": platform.python_version(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "endpoint": ENDPOINT,
        "request": payload,
        "request_attempts": 1,
        "automatic_retries": 0,
        "timeout_seconds": 45,
        "scope": "API connectivity and exact text response only; not agent/research validation",
        "usage": None,
    }
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            record["http_status"] = response.status
            body = json.load(response)
        choice = body["choices"][0]
        text = choice["message"].get("content") or ""
        record.update(
            provider_model=body.get("model"),
            finish_reason=choice.get("finish_reason"),
            response_text=text,
            usage=body.get("usage"),
            passed=choice.get("finish_reason") == "stop" and text.strip() == "LABCOUNCIL_OK",
        )
    except urllib.error.HTTPError as error:
        record.update(http_status=error.code, passed=False, failure="provider_http_error")
        try:
            detail = json.loads(error.read()).get("error", {})
            if isinstance(detail, dict):
                record["provider_error_type"] = detail.get("type")
                record["provider_error_code"] = detail.get("code")
                record["provider_error_message"] = detail.get("message")
        except (ValueError, OSError, AttributeError):
            pass
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        record.update(passed=False, failure="transport_error", error_type=type(error).__name__)
        reason = getattr(error, "reason", None)
        record["transport_reason_type"] = type(reason).__name__ if reason else None
    except (ValueError, TypeError, AttributeError, KeyError, IndexError):
        record.update(passed=False, failure="unrecognized_response")
    record["elapsed_seconds"] = round(time.monotonic() - start, 3)
    record = redact(record, key)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
