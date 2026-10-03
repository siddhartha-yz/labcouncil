#!/usr/bin/env python3
"""Send one bounded Gemini smoke request; never log authentication headers."""

import argparse
import datetime
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


ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
PROMPT = "Reply with exactly LABCOUNCIL_OK. Do not include any other text."


def load_key(path):
    # Parse one variable as data. Do not source/execute a credentials file.
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].strip()
            name, separator, value = line.partition("=")
            if separator and name.strip() == "GEMINI_API_KEY":
                values = shlex.split(value, comments=True)
                if len(values) != 1 or not values[0]:
                    raise ValueError("GEMINI_API_KEY must contain one nonempty value")
                return values[0]
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY is not configured")
    return key


def redact(value, key):
    encoded = json.dumps(value, ensure_ascii=False)
    encoded = encoded.replace(key, "[REDACTED]")
    encoded = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED]", encoded)
    encoded = re.sub(r"projects/\d+", "projects/[REDACTED]", encoded)
    return json.loads(encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--model", default="gemini-3.8-flash")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new attempt filename")
    try:
        key = load_key(args.env_file)
    except (OSError, ValueError):
        print("Credentials could not be loaded; values were not printed.")
        return 2

    payload = {
        "model": args.model,
        "input": PROMPT,
        "store": False,
        "generation_config": {"thinking_level": "low", "max_output_tokens": 256},
    }
    record = {
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "python": platform.python_version(),
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
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            record["http_status"] = response.status
            body = json.load(response)
        text = "".join(
            part.get("text", "")
            for step in body.get("steps", [])
            if step.get("type") == "model_output"
            for part in step.get("content", [])
            if part.get("type") == "text"
        )
        record.update(
            provider_model=body.get("model"),
            provider_status=body.get("status"),
            response_text=text,
            usage=body.get("usage"),
            passed=body.get("status") == "completed" and text.strip() == "LABCOUNCIL_OK",
        )
    except urllib.error.HTTPError as error:
        record.update(http_status=error.code, passed=False, failure="provider_http_error")
        try:
            body = json.loads(error.read())
            detail = body.get("error", {})
            if isinstance(detail, dict):
                record["provider_error_status"] = detail.get("status")
                record["provider_error_message"] = detail.get("message")
        except (ValueError, OSError):
            pass
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        record.update(passed=False, failure="transport_error", error_type=type(error).__name__)
        # Never print arbitrary exception strings, which may contain proxy credentials.
        reason = getattr(error, "reason", None)
        record["transport_reason_type"] = type(reason).__name__ if reason else None
    except (ValueError, TypeError, AttributeError):
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
