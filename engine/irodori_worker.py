"""Persistent JSON-lines worker for Irodori-TTS.

This file is executed by the Irodori virtual environment, not by the desktop
application interpreter. The model is loaded lazily on the first request and
is released when this process exits.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
from pathlib import Path


if os.name == "nt":
    _OriginalPopen = subprocess.Popen

    class _HiddenChildPopen(_OriginalPopen):
        """Prevent third-party probes such as ``cmd /c ver`` opening a terminal."""

        def __init__(self, *args, **kwargs):
            creation_flags = int(kwargs.pop("creationflags", 0))
            creation_flags &= ~subprocess.CREATE_NEW_CONSOLE
            kwargs["creationflags"] = creation_flags | subprocess.CREATE_NO_WINDOW
            startupinfo = kwargs.get("startupinfo")
            if startupinfo is None:
                startupinfo = subprocess.STARTUPINFO()
                kwargs["startupinfo"] = startupinfo
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            super().__init__(*args, **kwargs)

    subprocess.Popen = _HiddenChildPopen

from huggingface_hub import hf_hub_download

from irodori_tts.inference_runtime import (
    InferenceRuntime,
    RuntimeKey,
    SamplingRequest,
    resolve_cfg_scales,
    save_wav,
)


PREFIX = "@@IRODORI@@"


def _emit(payload: dict) -> None:
    print(PREFIX + json.dumps(payload, ensure_ascii=True), flush=True)


def _checkpoint(request: dict) -> str:
    configured = str(request.get("checkpoint", "")).strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Checkpoint not found: {path}")
        return str(path)
    return str(
        hf_hub_download(
            repo_id=str(request["hf_checkpoint"]),
            filename="model.safetensors",
        )
    )


def _runtime_key(request: dict) -> RuntimeKey:
    return RuntimeKey(
        checkpoint=_checkpoint(request),
        model_device=str(request["model_device"]),
        model_precision=str(request["model_precision"]),
        codec_device=str(request["codec_device"]),
        codec_precision=str(request["codec_precision"]),
    )


def _synthesize(runtime: InferenceRuntime, request: dict) -> str:
    voice = request["voice"]
    speech_text = str(request["text"])
    no_ref = bool(voice.get("no_ref", False))
    caption = str(voice.get("caption", "")).strip() or None
    use_speaker = bool(runtime.model_cfg.use_speaker_condition_resolved and not no_ref)
    text_scale, caption_scale, speaker_scale, _ = resolve_cfg_scales(
        cfg_guidance_mode="independent",
        cfg_scale_text=float(voice.get("cfg_scale_text", 3.0)),
        cfg_scale_caption=float(voice.get("cfg_scale_caption", 3.0)),
        cfg_scale_speaker=float(voice.get("cfg_scale_speaker", 5.0)),
        cfg_scale=None,
        use_caption_condition=bool(runtime.model_cfg.use_caption_condition and caption),
        use_speaker_condition=use_speaker,
    )
    ref_wav = str(voice.get("ref_wav", "")).strip() or None
    if use_speaker and not ref_wav:
        raise ValueError("Speaker-conditioned voice requires ref_wav.")
    speaker_kv_scale = voice.get("speaker_kv_scale")
    result = runtime.synthesize(
        SamplingRequest(
            text=speech_text,
            caption=caption,
            ref_wav=ref_wav,
            no_ref=no_ref,
            duration_scale=float(request.get("duration_scale", 1.0)),
            num_steps=int(request.get("num_steps", 40)),
            cfg_scale_text=text_scale,
            cfg_scale_caption=caption_scale,
            cfg_scale_speaker=speaker_scale,
            cfg_guidance_mode="independent",
            speaker_kv_scale=None if speaker_kv_scale is None else float(speaker_kv_scale),
            speaker_kv_min_t=None
            if speaker_kv_scale is None
            else float(voice.get("speaker_kv_min_t", 0.9)),
        ),
        log_fn=None,
    )
    output = Path(str(request["output"])).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    return str(save_wav(output, result.audio, result.sample_rate).resolve())


def main() -> None:
    runtime: InferenceRuntime | None = None
    key: RuntimeKey | None = None
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        request_id = ""
        try:
            request = json.loads(line)
            request_id = str(request.get("id", ""))
            action = str(request.get("action", "synthesize"))
            if action == "shutdown":
                _emit({"id": request_id, "ok": True, "shutdown": True})
                return
            requested_key = _runtime_key(request)
            if runtime is None or key != requested_key:
                runtime = InferenceRuntime.from_key(requested_key)
                key = requested_key
            output = _synthesize(runtime, request)
            _emit({"id": request_id, "ok": True, "output": output})
        except Exception as exc:
            _emit(
                {
                    "id": request_id,
                    "ok": False,
                    "error": str(exc),
                    "detail": traceback.format_exc()[-3000:],
                }
            )


if __name__ == "__main__":
    main()
