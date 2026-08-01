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

MODEL = "cosyvoice-v3-flash"        # 预置音色全在这 (粤语/英语/普通话实测通)
CLONE_MODEL = "cosyvoice-v3.5-flash"  # 声音克隆的目标模型 (预置音色它反而不认)

_STATIC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
VOICE_DIR = os.path.join(_STATIC, "scene", "voice")
CACHE_DIR = os.path.join(VOICE_DIR, "cache")
SAMPLE_DIR = os.path.join(VOICE_DIR, "samples")

MAX_CHARS = 600   # 与正史编辑框同上限; 台词键按句计费, 不该有超长文本

# 语气音精灵台本 (分类对齐 director 惊/怒/哀/喜 + 常态; 文件名用 ASCII)。
# 标点与省略号就是全部演技; 离线批量 (gen_voice.py) 与克隆音即时生成共用这一份。
SPRITES: dict[str, dict[str, list[str]]] = {
    "zh": {
        "surprise": ["诶？！", "嗯？！"],
        "anger":    ["哼。", "啧。"],
        "sad":      ["唉……", "嗯……"],
        "joy":      ["哈哈。", "嘿嘿。"],
        "neutral":  ["嗯。", "嗯？"],
    },
    "yue": {
        "surprise": ["吓？！", "咦？！"],
        "anger":    ["哼。", "嘖。"],
        "sad":      ["唉……", "哎……"],
        "joy":      ["哈哈。", "嘻嘻。"],
        "neutral":  ["嗯。", "係。"],
    },
    "en": {
        "surprise": ["Huh?!", "What—?"],
        "anger":    ["Tch.", "Hmph."],
        "sad":      ["Haah...", "Mm..."],
        "joy":      ["Heh.", "Ha ha."],
        "neutral":  ["Mm.", "Hm?"],
    },
}


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


async def tts_line_cached(text: str, voice: str, speed: float = 1.0,
                          model: str | None = None) -> str:
    """合成一句台词 (缓存优先), 返回可直接播放的静态 URL.
    model 缺省走预置音色模型; 克隆音的角色卡带 model 字段 (CLONE_MODEL)。"""
    text = (text or "").strip()[:MAX_CHARS]
    if not text:
        raise TTSError("空台词")
    key = cache_key(text, voice, speed)
    path = os.path.join(CACHE_DIR, f"{key}.mp3")
    if not os.path.exists(path):
        audio = await asyncio.to_thread(synth, text, voice, speed, model or MODEL)
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = f"{path}.part"
        with open(tmp, "wb") as f:
            f.write(audio)
        os.replace(tmp, path)   # 原子落盘: 并发同句只会白算一次, 不会互相截断
    return f"/scene/voice/cache/{key}.mp3"


def gen_sprites_for(voice_id: str, lang: str = "zh", model: str = MODEL,
                    force: bool = False) -> int:
    """给一个音色生成整套语气音精灵 (10 段, 幂等)。克隆完成后后台跑;
    单段失败只跳过不炸 — 缺的精灵客户端本就静默降级。返回生成数。"""
    made = 0
    vdir = os.path.join(VOICE_DIR, voice_id)
    for cat, texts in SPRITES.get(lang, SPRITES["zh"]).items():
        for i, text in enumerate(texts, 1):
            path = os.path.join(vdir, f"{cat}_{i}.mp3")
            if not force and os.path.exists(path):
                continue
            try:
                audio = synth(text, voice_id, 1.0, model)
            except Exception as e:
                print(f"[voice] sprite {voice_id}/{cat}_{i} failed: {e}")
                continue
            os.makedirs(vdir, exist_ok=True)
            with open(path, "wb") as f:
                f.write(audio)
            made += 1
    return made


def _to_wav_16k(data: bytes, ext: str) -> tuple[bytes, str]:
    """ffmpeg 转 16k 单声道 wav (克隆入料的稳妥格式); 没有 ffmpeg 就原样上传."""
    import shutil
    import subprocess
    import tempfile
    if not shutil.which("ffmpeg"):
        return data, ext
    src = tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False)
    dst_path = src.name + ".wav"
    try:
        src.write(data)
        src.close()
        r = subprocess.run(["ffmpeg", "-y", "-i", src.name, "-ar", "16000", "-ac", "1",
                            "-f", "wav", dst_path], capture_output=True, timeout=60)
        if r.returncode != 0:
            raise TTSError(f"音频转码失败: {r.stderr.decode(errors='replace')[-200:]}")
        with open(dst_path, "rb") as f:
            return f.read(), "wav"
    finally:
        os.unlink(src.name)
        if os.path.exists(dst_path):
            os.unlink(dst_path)


def enroll(data: bytes, ext: str) -> str:
    """🎙 声音克隆: 音频样本 → CosyVoice 专属音色 id (10~30 秒清晰人声最佳)。
    DashScope 的 enrollment 只吃公网 URL — 样本临时落在 /scene/voice/samples/
    (uuid 文件名不可猜), 注册完即删。返回的 voice_id 配 CLONE_MODEL 合成。"""
    import uuid

    import httpx

    from ..config import get_settings
    st = get_settings()
    if not st.dashscope_api_key:
        raise TTSError("缺 dashscope_api_key")
    data, ext = _to_wav_16k(data, ext)
    name = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    sample_path = os.path.join(SAMPLE_DIR, name)
    with open(sample_path, "wb") as f:
        f.write(data)
    public_url = f"{st.public_base_url.rstrip('/')}/scene/voice/samples/{name}"
    try:
        resp = httpx.post(
            "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization",
            headers={"Authorization": f"Bearer {st.dashscope_api_key}",
                     "Content-Type": "application/json"},
            json={"model": "voice-enrollment",
                  "input": {"action": "create_voice", "target_model": CLONE_MODEL,
                            "prefix": f"lp{uuid.uuid4().hex[:6]}", "url": public_url}},
            timeout=120)
        if resp.status_code != 200:
            raise TTSError(f"克隆注册失败 {resp.status_code}: {resp.text[:200]}")
        out = resp.json().get("output") or {}
        voice_id = out.get("voice_id") or out.get("voice")
        if not voice_id:
            raise TTSError(f"克隆无音色返回: {resp.text[:200]}")
        return str(voice_id)
    finally:
        try:
            os.unlink(sample_path)   # 样本不留站 — 声音是比照片更敏感的生物特征
        except OSError:
            pass
