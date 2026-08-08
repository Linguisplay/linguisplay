# -*- coding: utf-8 -*-
"""🔀 分派不许被载荷键劫走 (实弹 2026-08-08, 我自己造的)。

qwen.generate 靠 `if prompt.get("X")` 分派。而我给主拍和手机的载荷里【也】加了一个
同名的 relation_read (TA 此刻怎么看玩家)。于是关系一落账:
  · 主拍 → 被路由到关系判官, 一个 beat 都不出, 角色彻底哑掉
  · 手机 → 同样被劫, 回不出消息
两条路一起死, 而且是静默的: 没有守卫开枪、审计单干干净净、单测全绿
(单测只测 _build_system 吐出来的字符串, 测不到分派这一层)。

修法: 分派键改名 relation_judge, 载荷键留着不动 (载荷那个名字有 5 处引用, 改分派只有 2 处)。
本文件从「复现 bug」改成「守住修复」。
"""
from app.engine import qwen


class Probe(qwen.QwenLLM):
    def __init__(self):
        self._model = self._summary_model = self._aux_model = "m"
        self._url, self._key = "http://never", "k"
        self.hit = []

    def _relation_read(self, p):
        self.hit.append("_relation_read")
        return {"mode": "面和心不和", "feeling": "有点烦", "why": "他刚顶撞了我"}

    def _phone_reply(self, p):
        self.hit.append("_phone_reply")
        return {"text": "嗯，我在。"}


PAYLOAD_REL = {"mode": "旧相识", "feeling": "念着旧情",
               "why": "上回替我挡了一刀", "at": 3}


def test_the_phone_still_answers_with_a_relation_on_board():
    llm = Probe()
    out = llm.generate({
        "phone_reply": True,
        # runtime._phone_exchange 原样传的就是 state["rel_read"][cid]
        "relation_read": PAYLOAD_REL,
        "text": "在吗", "char": {"name": "阿珍"},
    })
    assert llm.hit == ["_phone_reply"], f"手机回复被劫走了: {llm.hit}"
    assert "text" in out


def test_the_judge_is_reachable_by_its_own_key():
    """改名之后判官本人还叫得动 —— 别把 bug 修成功能没了。"""
    llm = Probe()
    out = llm.generate({"relation_judge": True, "char": {"name": "阿珍"},
                        "player_name": "我", "lines": []})
    assert llm.hit == ["_relation_read"], llm.hit
    assert out.get("mode")


def test_a_bare_timestamp_does_not_hijack_anything():
    """最小复现: 只有 at 也会触发 —— 它跟提示词无关, 纯粹是分派被劫。"""
    llm = Probe()
    llm.generate({"phone_reply": True, "relation_read": {"at": 3},
                  "text": "在吗", "char": {"name": "阿珍"}})
    assert llm.hit == ["_phone_reply"], llm.hit
