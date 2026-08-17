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
