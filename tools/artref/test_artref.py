# -*- coding: utf-8 -*-
"""审美参考库核心逻辑测试: 过滤/去重/落库。跑法:
cd tools/artref && ../../apps/api/.venv/Scripts/python.exe -m pytest test_artref.py -q"""
import os
import tempfile

os.environ["ARTREF_ROOT"] = tempfile.mkdtemp(prefix="artref_test_")

import artref  # noqa: E402

POST = {"id": 1, "md5": "a" * 32, "file_url": "https://x/img/a.jpg", "rating": "g",
        "score": 99, "tag_string_artist": "someone", "tag_string_general": "1boy solo",
        "image_width": 1000, "image_height": 1400}


def test_good_post_becomes_a_row():
    row = artref.row_from_post(POST, min_score=40)
    assert row and row["md5"] == "a" * 32 and row["artist"] == "someone"


def test_non_general_rating_is_refused():
    assert artref.row_from_post({**POST, "rating": "s"}, 0) is None, \
        "参考库要能大大方方打开 — 只收全年龄"


def test_low_score_and_missing_url_are_refused():
    assert artref.row_from_post({**POST, "score": 5}, 40) is None
    assert artref.row_from_post({**POST, "file_url": "", "large_file_url": ""}, 0) is None


def test_weird_extension_is_refused():
    assert artref.row_from_post({**POST, "file_url": "https://x/a.mp4"}, 0) is None


def test_md5_dedup_on_insert():
    con = artref.open_db()
    row = {**artref.row_from_post(POST, 0), "local": "a.jpg"}
    assert artref.insert_ref(con, row) is True
    assert artref.insert_ref(con, row) is False, "同 md5 二进 = 库要炸重"


def test_require_tags_filter_locally():
    """匿名 API 限 2 个查询标签 — 挤不下的条件必须本地能补刀。"""
    assert artref.has_tags(POST, ["solo"]) is True
    assert artref.has_tags(POST, ["solo", "suit"]) is False


def test_pick_ext_only_images():
    assert artref.pick_ext("https://x/p/b.webp?q=1") == ".webp"
    assert artref.pick_ext("https://x/p/b.zip") == ""


def test_rate_persists_and_rejects_bogus_verdict():
    con = artref.open_db()
    row = {**artref.row_from_post({**POST, "md5": "b" * 32,
                                   "file_url": "https://x/b.jpg"}, 0), "local": "b.jpg"}
    artref.insert_ref(con, row)
    assert artref.rate(con, "b" * 32, "love", "脸 光影", "眼神光克制") is True
    v, f, c = con.execute("select verdict, facets, comment from refs where md5=?",
                          ("b" * 32,)).fetchone()
    assert (v, f, c) == ("love", "脸 光影", "眼神光克制")
    assert artref.rate(con, "b" * 32, "maybe") is False, "只认 love/reject/清空"
    assert artref.rate(con, "no_such", "love") is False


def test_taste_export_aggregates_by_frequency():
    con = artref.open_db()
    con.execute("update refs set verdict=''")   # 全套件共库: 先清别的用例的判断
    con.commit()
    for i, (v, f) in enumerate([("love", "脸 光影"), ("love", "脸"), ("reject", "塑料感")]):
        md5 = f"c{i}" * 16
        artref.insert_ref(con, {**artref.row_from_post(
            {**POST, "md5": md5, "file_url": f"https://x/c{i}.jpg"}, 0), "local": "x.jpg"})
        artref.rate(con, md5, v, f, "")
    text = (artref.pathlib.Path(artref.taste_export())).read_text(encoding="utf-8")
    assert "脸 ×2" in text and "光影 ×1" in text, "正面词表要按判断次数聚合"
    assert "塑料感 ×1" in text, "反例词表同等值钱"


def test_open_db_migration_is_idempotent():
    artref.open_db().close()
    con = artref.open_db()   # 二开不许因重复加列而炸
    cols = {r[1] for r in con.execute("pragma table_info(refs)")}
    assert {"verdict", "facets", "comment"} <= cols
