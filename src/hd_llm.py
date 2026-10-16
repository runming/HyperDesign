# -*- coding: utf-8 -*-
"""
HyperDesign 共享 LLM 客户端
优先用 ollama-python，失败时自动回落 REST /api/chat（宿主 Ollama 偶发 ResponseError 时保证流水线不中断）
"""
import json
import urllib.request

try:  # Windows 控制台可能是 GBK，统一把 stdout/stderr 切到 UTF-8 容错，避免中文/³ 等字符抛 UnicodeEncodeError
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OLLAMA_HOST = "http://127.0.0.1:11434"


def chat(model: str, messages: list, keep_alive=0, options: dict = None, images: list = None,
         timeout: int = 900, host: str = OLLAMA_HOST) -> str:
    """返回助手回复纯文本。messages: [{"role","content"}]；images: 图片路径或 base64 列表(多模态)"""
    msgs = json.loads(json.dumps(messages, ensure_ascii=False))
    if images:
        import base64
        import os
        enc = []
        for im in images:
            if isinstance(im, str) and os.path.exists(im):
                with open(im, "rb") as fh:
                    enc.append(base64.b64encode(fh.read()).decode("ascii"))
            else:
                enc.append(im)
        msg = dict(msgs[-1])
        msg["images"] = enc
        msgs[-1] = msg
    try:
        import ollama
        resp = ollama.chat(model=model, messages=msgs, keep_alive=keep_alive, options=options or {})
        return resp["message"]["content"] if isinstance(resp, dict) else resp.message.content
    except Exception as e:
        last_err = e
    payload = {"model": model, "messages": msgs, "stream": False,
               "keep_alive": keep_alive, "options": options or {}}
    req = urllib.request.Request(host + "/api/chat",
                                data=json.dumps(payload).encode("utf-8"),
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return data["message"]["content"]
    except Exception as e:
        raise RuntimeError("LLM 调用失败 (ollama-python: %r / REST: %r)" % (last_err, e))


def unload(model: str) -> bool:
    """请求卸载常驻模型释放显存 (keep_alive=0)"""
    for path, payload in (("/api/generate", {"model": model, "prompt": " ", "keep_alive": 0, "options": {"num_predict": 1}}),):
        try:
            req = urllib.request.Request(OLLAMA_HOST + path,
                                         data=json.dumps(payload).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                r.read()
            return True
        except Exception:
            pass
    try:
        import ollama
        ollama.generate(model=model, prompt=" ", keep_alive=0, options={"num_predict": 1})
        return True
    except Exception:
        return False


def ps() -> list:
    try:
        with urllib.request.urlopen(OLLAMA_HOST + "/api/ps", timeout=30) as r:
            return json.loads(r.read()).get("models", [])
    except Exception:
        return []
