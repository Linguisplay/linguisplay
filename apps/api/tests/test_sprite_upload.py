# -*- coding: utf-8 -*-
"""🖼 玩家上传人物图 → 智能裁剪三件套 (rembg 打桩, 测几何与作废逻辑)."""
import io

from PIL import Image

from app.engine import sprites


def _photo(w=800, h=1200):
    """合成一张「人物照」: 灰底, 人形色块站在中下部, 头在 (400, 300) 附近."""
    im = Image.new("RGB", (w, h), (90, 96, 104))
    px = im.load()
    for y in range(260, 1150):
        for x in range(320, 480):
            px[x, y] = (180, 150, 120)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _fake_debg(data):
    """rembg 桩: 人形区域不透明, 其余全透明 (尺寸与原图一致)."""
    src = Image.open(io.BytesIO(data))
    out = Image.new("RGBA", src.size, (0, 0, 0, 0))
    px = out.load()
    for y in range(260, 1150):
        for x in range(320, 480):
            px[x, y] = (180, 150, 120, 255)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def test_ingest_upload_produces_smart_trio(tmp_path, monkeypatch):
    monkeypatch.setattr(sprites, "SPRITE_DIR", tmp_path / "sprite")
    monkeypatch.setattr(sprites, "AVATAR_DIR", tmp_path / "avatar")
    import app.engine.gal as gal
    monkeypatch.setattr(gal, "debg", _fake_debg)

    # 旧表情差分该作废
    (tmp_path / "sprite").mkdir(parents=True)
    (tmp_path / "sprite" / "c1_喜.webp").write_bytes(b"old")

    out = sprites.ingest_upload("c1", _photo())
    assert out["smart"] is True
    assert out["stale_exprs_removed"] == 1
    assert not (tmp_path / "sprite" / "c1_喜.webp").exists()

    sp = Image.open(tmp_path / "sprite" / "c1.webp")
    assert sp.mode == "RGBA"
    assert sp.width <= 240, "立绘裁到了人形包围盒 (整幅宽 800 的空白被裁掉)"
    assert (tmp_path / "sprite" / "c1_src.jpg").exists(), "改脸源图留档"

    av = Image.open(tmp_path / "avatar" / "c1.jpg")
    assert av.width == av.height, "头像是方的"


def test_ingest_upload_center_crop_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(sprites, "SPRITE_DIR", tmp_path / "sprite")
    monkeypatch.setattr(sprites, "AVATAR_DIR", tmp_path / "avatar")
    import app.engine.gal as gal
    monkeypatch.setattr(gal, "debg", lambda d: d)   # 抠底失败 → 原样返回 (无 alpha)

    out = sprites.ingest_upload("c2", _photo())
    assert out["smart"] is False
    av = Image.open(tmp_path / "avatar" / "c2.jpg")
    assert av.width == av.height
    assert (tmp_path / "sprite" / "c2.webp").exists()
