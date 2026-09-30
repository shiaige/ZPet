#!/usr/bin/env python3
"""Ask the local CLIProxyAPI vision model (gpt-6-astra) to critique pet art."""
import base64
import json
import sys
import urllib.request

KEY = "6c3f341fa1da0e0db5cf85c0de16b66430fa7941681c7499"
URL = "http://127.0.0.1:8317/v1/chat/completions"


def b64(path):
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def ask(prompt, images):
    content = [{"type": "text", "text": prompt}]
    for p in images:
        content.append({"type": "image_url", "image_url": {"url": b64(p)}})
    body = json.dumps({
        "model": "gpt-6-astra",
        "reasoning_effort": "low",
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": content}],
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.load(r)
    print(data["choices"][0]["message"]["content"])


if __name__ == "__main__":
    ask(sys.argv[1], sys.argv[2:])