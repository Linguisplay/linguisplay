# -*- coding: utf-8 -*-
"""🎙 配音服务 — CosyVoice (DashScope) 按需合成 + 落盘缓存.

台词播放键的后端: 文本 + 音色 → mp3 静态文件, 返回 /scene/voice/cache/ URL。
法度: ① 合成必缓存 (同文同声重播零成本, 缓存目录在 scene 下 — 真相在服务器,
部署不覆盖); ② 缺 key / 缺包 / 云端拒绝(🔞审核) → TTSError, 调用方降级 —
语气音精灵是兜底, 台词全配音只是锦上添花; ③ 剧本无关 — 音色与语速全部来自
角色卡的 voice 字段 {"id": 音色名, "speed": 语速}, 这里不认识任何具体角色。
"""
from __future__ import annotations

import asyncio
import hashlib
import os

MODEL = "cosyvoice-v3-flash"   # 全线一个模型: 粤语/英语/普通话音色实测都在这

_STATIC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
CACHE_DIR = os.path.join(_STATIC, "scene", "voice", "cache")

MAX_CHARS = 600   # 与正史编辑框同上限; 台词键按句计费, 不该有超长文本


class TTSError(RuntimeError):
    pass


def synth(text: str, voice: str, speed: float = 1.0, model: str = MODEL) -> bytes:
    """Blocking synthesis. websocket 偶发握手超时 (实测) — 失败重试一次."""
    try:
        import dashscope
        from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer
    except ImportError as e:
        raise TTSError("dashscope 未安装") from e
    from ..config import get_settings
    key = get_settings().dashscope_api_key
    if not key:
        raise TTSError("缺 dashscope_api_key")
    dashscope.api_key = key
    last: Exception | None = None
    for _ in range(2):
        try:
            s = SpeechSynthesizer(model=model, voice=voice,
                                  speech_rate=float(speed or 1.0),
                                  format=AudioFormat.MP3_22050HZ_MONO_256KBPS)
            audio = s.call(text)
            if audio:
                return bytes(audio)
            # 空返回 = 音色不存在或内容被审核拒绝 — 重试无益, 直接报
            raise TTSError("云端返回空音频 (音色不存在或内容未过审)")
        except TTSError:
            raise
        except Exception as e:   # 网络/握手类, 值得再试一枪
            last = e
    raise TTSError(f"TTS 合成失败: {last}")


def cache_key(text: str, voice: str, speed: float) -> str:
    return hashlib.sha1(f"{voice}|{speed}|{text}".encode("utf-8")).hexdigest()


async def tts_line_cached(text: str, voice: str, speed: float = 1.0) -> str:
    """合成一句台词 (缓存优先), 返回可直接播放的静态 URL."""
    text = (text or "").strip()[:MAX_CHARS]
    if not text:
        raise TTSError("空台词")
    key = cache_key(text, voice, speed)
    path = os.path.join(CACHE_DIR, f"{key}.mp3")
    if not os.path.exists(path):
        audio = await asyncio.to_thread(synth, text, voice, speed)
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = f"{path}.part"
        with open(tmp, "wb") as f:
            f.write(audio)
        os.replace(tmp, path)   # 原子落盘: 并发同句只会白算一次, 不会互相截断
    return f"/scene/voice/cache/{key}.mp3"
