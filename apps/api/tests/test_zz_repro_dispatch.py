"""复现: relation_read 抢在 phone_reply / 主拍分支之前, 把整拍生成劫走。"""
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


def test_phone_reply_is_hijacked():
    llm = Probe()
    out = llm.generate({
        "phone_reply": True,
        # runtime._phone_exchange 原样传的就是 state["rel_read"][cid]
        "relation_read": {"mode": "旧相识", "feeling": "念着旧情",
                          "why": "上回替我挡了一刀", "at": 3},
        "text": "在吗", "char": {"name": "阿珍"},
    })
    assert llm.hit == ["_relation_read"], llm.hit
    assert "text" not in out


def test_main_turn_is_hijacked():
    llm = Probe()
    out = llm.generate({
        "speaker_name": "阿珍", "channel": "say", "player_input": "你还好吗",
        "history": [],
        "relation_read": {"mode": "旧相识", "feeling": "念着旧情",
                          "why": "上回替我挡了一刀", "at": 3},
    })
    assert llm.hit == ["_relation_read"], llm.hit
    assert "beats" not in out
