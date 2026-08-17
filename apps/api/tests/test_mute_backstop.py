# -*- coding: utf-8 -*-
"""🔇 哑巴疫情的两层修法合同 (Yi 报障 2026-08-17「角色不回复了」, 狗笼实锤)。

现场: 渲染拍请求里历史是【一条 assistant 消息 = 恰好一行】× 18 条 —— 模型照
形状学, 写一行旁白就 finish=stop (流式/非流式都复现), 台词行永远轮不到出场;
哑拍落库又成为下一拍的单行旁白示范, 自我强化, 新局开场即 15 条纯旁白, 出生带病。
~08-13 起 deepseek 服务端更贴范例、更不服从「写3~6行」, 旧形状翻车。
这是 08-07「行首前缀」事故的第二层: 那次矫的是每一行的【前缀】,
这次矫的是每一条消息的【行数】。同一条家法: 示范必须长得跟要求的输出一样。

  ① 示范矫形: _turn_messages 把窗口切完后连续的 assistant 历史合并成一条
     多行消息。只动消息边界, 不动一个字 —— 窗口口径/记忆切点/判官读的
     都是合并前的原始条目, 前缀缓存的块状稳定性也不受影响。
  ② 机械保证: say 通道被直接搭话, 渲染完一行台词都没有 → 引擎在门口补一枪
     只要台词行, 不撕已流出的旁白。约束住在引擎门口, 不进正常路的提示词
     (堵死出口模型会翻墙 —— 邀约锁的教训)。member 的沉默依旧合法。
  ③ 失守必响: 夜巡判官红灯, 见 test_night_tour_mute.py。
"""
import json

from app.engine import qwen


# ══ ① 示范矫形: 连续 assistant 合并成多行消息 ═══════════════════════════════════

def _msgs(history, **over):
    prompt = {"history": history, "channel": "say", "player_input": "你还好吗",
              "persona": {"name": "蔡妍"}, **over}
    return qwen._turn_messages(prompt, "SYS", "蓝信一")


U1 = {"role": "user", "content": "在吗"}
A1 = {"role": "assistant", "content": "旁白：他抬起头。"}
A2 = {"role": "assistant", "content": "蓝信一：来了。"}
A3 = {"role": "assistant", "content": "旁白：夜风更凉。"}
U2 = {"role": "user", "content": "说重点"}
A4 = {"role": "assistant", "content": "蓝信一：急什么。"}
A5 = {"role": "assistant", "content": "旁白：他偏了偏头。"}


def test_consecutive_assistant_beats_merge_into_one_message():
    """一回合的多拍要合成一条多行消息 —— 这才是要求模型产出的形状。"""
    ms = _msgs([U1, A1, A2, A3, U2, A4, A5])
    assistants = [m["content"] for m in ms if m["role"] == "assistant"]
    assert assistants == ["旁白：他抬起头。\n蓝信一：来了。\n旁白：夜风更凉。",
                          "蓝信一：急什么。\n旁白：他偏了偏头。"], assistants


def test_merge_never_crosses_a_player_line():
    """合并只吃连续段, 玩家的行是硬边界 — 回合归属不许被搅浑。"""
    ms = _msgs([U1, A1, U2, A2])
    roles = [m["role"] for m in ms]
    # system + u1 + a(合并段1) + u2 + a(合并段2) + 本回合的 user
    assert roles == ["system", "user", "assistant", "user", "assistant", "user"], roles


def test_opening_scroll_merges_into_one_demonstration():
    """开场卷轴 15 条纯旁白 = 出生即 15 条单行示范, 正是新局出生带病的病灶。
    合并后它是一条 15 行的消息 — 一个多行输出的正确示范。"""
    scroll = [{"role": "assistant", "content": f"旁白：第{i}句。"} for i in range(15)]
    ms = _msgs(scroll + [U1, A1])
    assistants = [m["content"] for m in ms if m["role"] == "assistant"]
    assert len(assistants) == 2
    assert assistants[0].count("\n") == 14, "开场卷轴没有合成一条多行消息"


def test_merge_keeps_every_line_verbatim():
    """只动消息边界, 不动一个字 — 内容变了就是另一种污染。"""
    ms = _msgs([U1, A1, A2])
    merged = next(m["content"] for m in ms if m["role"] == "assistant")
    assert merged.splitlines() == ["旁白：他抬起头。", "蓝信一：来了。"]


def test_prefix_cache_stays_block_stable():
    """前缀缓存的命根: 新回合追加历史时, 旧回合的合并段必须逐字不变
    (39% 命中率靠的就是这个边界 — 见 history_window 的原委)。"""
    h1 = [U1, A1, A2]
    h2 = [U1, A1, A2, U2, A4, A5]
    m1 = _msgs(h1)
    m2 = _msgs(h2)
    # 两次的历史段开头 (system + u1 + 合并段1) 必须逐字相同
    assert m2[:3] == m1[:3]


# ══ ② 机械保证: say 被搭话必有台词行 ═══════════════════════════════════════════

class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def _plan_resp(outline=("他懒懒回话",)):
    args = json.dumps({"grounding": "巷口对峙", "outline": list(outline)})
    return _Resp({"choices": [{"message": {"tool_calls": [
        {"function": {"name": "plan_turn", "arguments": args}}]}}]})


def _respeak_resp(line="蓝信一：「几个收数的小子。」"):
    return _Resp({"choices": [{"message": {"content": line}}]})


def _mk_llm():
    llm = qwen.QwenLLM.__new__(qwen.QwenLLM)
    llm._url, llm._key, llm._model = "http://fake", "k", "deepseek-v4-pro"
    llm._summary_model = llm._aux_model = llm._model
    return llm


def _wire(monkeypatch, render_text, respeak=None, respeak_raises=False):
    """打桩传输层: plan 固定过, render 吐指定散文, respeak 按需。返回调用账本。"""
    calls = []

    def fake_post(url, key, body, timeout=30, kind=""):
        calls.append(kind)
        if kind == "plan":
            return _plan_resp()
        if kind == "respeak":
            if respeak_raises:
                raise RuntimeError("provider down")
            return respeak or _respeak_resp()
        raise AssertionError(f"unexpected _post_chat kind={kind}")

    def fake_stream(url, key, body, timeout=60, kind=""):
        calls.append(f"stream:{kind}")
        yield render_text

    monkeypatch.setattr(qwen, "_post_chat", fake_post)
    monkeypatch.setattr(qwen, "_post_chat_stream", fake_stream)
    return calls


def _run(llm, **over):
    prompt = {"speaker_name": "蓝信一", "channel": "say", "language": "zh",
              "player_input": "巷里怎么回事", "persona": {"name": "蔡妍"},
              "history": [], "cast": ["蓝信一"], **over}
    final = None
    for kind, payload in llm.plan_and_render(prompt):
        if kind == "final":
            final = payload
    return final


def test_mute_render_gets_exactly_one_respeak_line(monkeypatch):
    """渲染只给了旁白就停笔 (实弹里 3/4 的形状) → 门口补一枪, 台词必到。"""
    calls = _wire(monkeypatch, "旁白：他偏了偏头，没接话。\n")
    final = _run(_mk_llm())
    dlg = [b for b in final["beats"] if b.get("type") == "dialogue"
           and (b.get("speaker_name") or "").strip()]
    assert dlg, f"say 被搭话却零台词: {final['beats']}"
    assert dlg[-1]["speaker_name"] == "蓝信一"
    assert "几个收数的小子" in dlg[-1]["text"]
    assert calls.count("respeak") == 1
    # 已流出的旁白一个字不许撕 (守卫开枪的旧病不许在这里复发)
    assert any(b.get("type") == "description" and "偏了偏头" in b.get("text", "")
               for b in final["beats"])


def test_healthy_render_never_triggers_respeak(monkeypatch):
    """正常路零新增调用零行为差 — 保险只在出险时掏钱。"""
    calls = _wire(monkeypatch, "旁白：他偏了偏头。\n蓝信一：「讲数的。」\n")
    final = _run(_mk_llm())
    assert calls.count("respeak") == 0
    assert any(b.get("type") == "dialogue" for b in final["beats"])


def test_do_channel_silence_is_legal(monkeypatch):
    """玩家只是做动作, 角色不吭声合法 — speechless_turn 的三前提在这里同样成立。"""
    calls = _wire(monkeypatch, "旁白：他看了你一眼。\n")
    final = _run(_mk_llm(), channel="do")
    assert calls.count("respeak") == 0
    assert not any(b.get("type") == "dialogue" for b in final["beats"])


def test_member_silence_is_legal(monkeypatch):
    """成员的「无」是合法沉默 (5秒军令), 不许被保险改判。"""
    calls = _wire(monkeypatch, "无")
    final = _run(_mk_llm(), group_mode="member")
    assert calls.count("respeak") == 0
    assert final["beats"] == []


def test_observer_never_respeaks(monkeypatch):
    """旁观局玩家不在戏里, 没有「被搭话」这回事。"""
    calls = _wire(monkeypatch, "旁白：两人对视。\n")
    final = _run(_mk_llm(), observer=True)
    assert calls.count("respeak") == 0


def test_respeak_failure_degrades_to_narration(monkeypatch):
    """保险自己坏了不许炸回合 — 最坏退回今天的样子 (旁白拍照走)。"""
    calls = _wire(monkeypatch, "旁白：他偏了偏头。\n", respeak_raises=True)
    final = _run(_mk_llm())
    assert calls.count("respeak") == 1
    assert final["beats"], "respeak 失败把整拍弄丢了"
    assert all(b.get("type") == "description" for b in final["beats"])


def test_fallback_generate_path_is_also_guarded(monkeypatch):
    """plan 整拍失败走老单拍兜底 — 那条路同样吃这道保证 (同一次模型漂移
    不会因为走了兜底就重新变成哑巴)。"""
    calls = []

    def fake_post(url, key, body, timeout=30, kind=""):
        calls.append(kind)
        if kind == "plan":
            raise RuntimeError("plan down")
        if kind == "respeak":
            return _respeak_resp()
        raise AssertionError(kind)

    monkeypatch.setattr(qwen, "_post_chat", fake_post)
    llm = _mk_llm()
    monkeypatch.setattr(llm, "generate", lambda p: {
        "beats": [{"type": "description", "speaker_name": None, "text": "他看着你。"}]},
        raising=False)
    final = _run(llm)
    assert calls.count("respeak") == 1
    assert any(b.get("type") == "dialogue" for b in final["beats"])


def test_respeak_salvages_a_bare_line(monkeypatch):
    """补枪回来的行就算忘了打前缀, 也要抢救成台词 — 保险自己不许再犯原病。"""
    calls = _wire(monkeypatch, "旁白：他没接话。\n",
                  respeak=_Resp({"choices": [{"message": {"content": "「几个小子讲数。」"}}]}))
    final = _run(_mk_llm())
    dlg = [b for b in final["beats"] if b.get("type") == "dialogue"]
    assert dlg and dlg[-1]["speaker_name"] == "蓝信一"
    assert dlg[-1]["text"] == "几个小子讲数。"
