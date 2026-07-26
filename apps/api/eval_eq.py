# -*- coding: utf-8 -*-
"""🧪 情商考卷 (Yi 情商军令⑦): 固定 16 个刁钻情绪场景 → 生产同款提示词路径出台词 →
GLM 5.2 (Ark) 当判官打分。每次改提示词/换模型跑一遍, 调优从此有考卷。

用法 (服务器, 带 .env):
    set -a && . .env && set +a && python eval_eq.py --tag baseline
分数维度: 看见情绪 / 贴人设 / 像人话 / 入戏 (1~5)。报告存 eval_report_{tag}.json。
"""
import argparse
import concurrent.futures as futures
import json
import os
import sys
import time

sys.path.insert(0, ".")

from app.engine.llm import get_llm  # noqa: E402

import httpx  # noqa: E402

ARK_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
JUDGE_MODEL = "glm-5-2-260617"

# ── 三个考官角色 (故事无关的原型) ──
CHARS = {
    "泼辣嘴硬": {
        "speaker_name": "阿珍", "speaker_persona": "糖水店老板娘，泼辣嘴硬心软，亡夫留下的店撑了八年",
        "eq_style": "嘴硬心软——被撒娇就损人但手上让步；见人低落绝不讲道理，先递吃的",
        "voice_print": "短句，市井腔，句尾爱带「啦」；从不说客套话；心虚时才用省略号",
        "examples": ["糖水要趁热，人心也是啦。", "少来这套，坐下。", "我这儿不赊账，赊心事可以。"],
    },
    "闷话少": {
        "speaker_name": "细辉", "speaker_persona": "巷口修车匠，话少手巧讲义气，谁家有难半夜也来",
        "eq_style": "不安慰人，只做事——你难过他就默默把你的车修好、把伞塞你手里",
        "voice_print": "一句话不超过十个字；常用「嗯」「行」「放着」；从不解释自己",
        "examples": ["嗯。", "放着，我来。", "路滑，慢点。"],
    },
    "温柔姐姐": {
        "speaker_name": "文清", "speaker_persona": "诊所护士，温柔周到，见惯生死所以特别惜人",
        "eq_style": "正面接住情绪，从不回避；但温柔里有骨头，越界会被她轻轻挡回来",
        "voice_print": "句子完整，语速平；爱用「先」字（先坐下/先吃饭）；从不用反问句伤人",
        "examples": ["先坐下，喝口水，慢慢说。", "疼就说疼，忍着不算勇敢。"],
    },
}

# ── 16 道考题 (情绪类 × 角色) ──
CASES = [
    ("撒娇黏人", "泼辣嘴硬", [], "珍姐～我今天就想赖在你店里不走了，你养我嘛。"),
    ("撒娇黏人", "温柔姐姐", [], "姐，我不想回家，今晚让我在诊所沙发睡好不好嘛。"),
    ("试探敲打", "泼辣嘴硬", ["玩家：昨晚看见你和收租的说话了。"], "你们聊了挺久啊……聊什么呢，不方便说？"),
    ("试探敲打", "闷话少", [], "有人说你以前不是修车的。你以前……到底做什么的？"),
    ("低落难过", "泼辣嘴硬", [], "珍姐，我工作丢了。攒的钱也快见底了。"),
    ("低落难过", "闷话少", [], "细辉哥，我爸的病……医生说准备后事吧。"),
    ("低落难过", "温柔姐姐", [], "我好像谁都不需要我。真的，一个都没有。"),
    ("怄气冷战", "泼辣嘴硬", ["玩家：上次的事我还在气。", "阿珍：气什么啦，多大点事。"], "……没事。糖水多少钱，我付了就走。"),
    ("怄气冷战", "温柔姐姐", [], "你昨天明明看见我了，为什么装作不认识？算了，当我没问。"),
    ("敷衍走神", "泼辣嘴硬", [], "嗯……哦，你说什么？随便吧，都行。"),
    ("敷衍走神", "闷话少", [], "没什么。就是路过。你忙你的。"),
    ("坦诚交心", "闷话少", [], "细辉哥，其实我一直把你当亲哥。这话我憋了很久了。"),
    ("坦诚交心", "温柔姐姐", [], "姐，我跟你说件事，你别告诉别人……我可能要离开这里了。"),
    ("悲报强撑", "泼辣嘴硬", [], "哈哈，我没事啊，真的。对了你这糖水涨价没？（眼圈是红的）"),
    ("边界试探", "温柔姐姐", [], "姐你今晚下班之后，能不能……就我们两个人，去喝一杯？"),
    ("迁怒扎人", "闷话少", [], "修个车都这么慢，你是不是根本不会？烦死了！（今天处处不顺）"),
]


def gen_reply(llm, emotion, ck, history, line):
    c = CHARS[ck]
    hist = [{"role": "user" if h.startswith("玩家") else "assistant",
             "content": h.split("：", 1)[-1]} for h in history]
    prompt = {
        "speaker_name": c["speaker_name"], "channel": "say",
        "persona": {"name": "你"}, "player_name": "你",
        "speaker_persona": c["speaker_persona"], "eq_style": c["eq_style"],
        "voice_print": c["voice_print"], "examples": c["examples"],
        "history": hist, "player_input": line, "must_speak": True,
        "relation": "朋友",
    }
    out = llm.generate(prompt) or {}
    return " ".join((b.get("text") or "") for b in out.get("beats", []))[:400]


def judge(key, emotion, ck, line, reply):
    c = CHARS[ck]
    sys_p = ("你是苛刻的对话情商评委。给一段 AI 角色扮演回复打分, 只输出严格 JSON:"
             '{"seen":1-5,"chara":1-5,"natural":1-5,"immersion":1-5,"note":"≤30字"}。'
             "seen=有没有先看见并接住对方的情绪(答对字面接错心=低分); chara=贴不贴这个人设"
             "(含语言指纹); natural=像不像真人说话(套话/AI腔扣分); immersion=有没有身体/现场感。")
    u = json.dumps({"角色": c["speaker_persona"], "表达方式": c["eq_style"],
                    "语言指纹": c["voice_print"], "情绪类型": emotion,
                    "玩家说": line, "角色回复": reply}, ensure_ascii=False)
    for _ in range(2):
        try:
            r = httpx.post(ARK_URL, headers={"Authorization": f"Bearer {os.environ['ARK_API_KEY']}"},
                           json={"model": JUDGE_MODEL, "temperature": 0.2, "max_tokens": 2000,
                                 "messages": [{"role": "system", "content": sys_p},
                                              {"role": "user", "content": u}],
                                 "response_format": {"type": "json_object"}},
                           timeout=90)
            d = json.loads(r.json()["choices"][0]["message"]["content"])
            return {k: d.get(k) for k in ("seen", "chara", "natural", "immersion", "note")}
        except Exception as e:
            err = str(e)[:80]
            time.sleep(2)
    return {"seen": None, "chara": None, "natural": None, "immersion": None, "note": "JUDGE-FAIL " + err}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="run")
    args = ap.parse_args()
    llm = get_llm()   # 生产同款构造 (env 配置; 裸 QwenLLM() 默认 DashScope=欠费坑)
    rows = []
    print(f"出题 {len(CASES)} 道 …")
    for i, (emotion, ck, hist, line) in enumerate(CASES):
        reply = gen_reply(llm, emotion, ck, hist, line)
        rows.append({"i": i, "emotion": emotion, "char": ck, "line": line, "reply": reply})
        print(f"  [{i+1:2d}/{len(CASES)}] {emotion}·{ck}: {reply[:48]}…")
    print("判卷 (GLM 5.2) …")
    with futures.ThreadPoolExecutor(max_workers=4) as ex:
        fs = {ex.submit(judge, r["i"], r["emotion"], r["char"], r["line"], r["reply"]): r for r in rows}
        for f in futures.as_completed(fs):
            fs[f].update(f.result())
    dims = ("seen", "chara", "natural", "immersion")
    ok = [r for r in rows if isinstance(r.get("seen"), (int, float))]
    avg = {d: round(sum(r[d] for r in ok) / max(1, len(ok)), 2) for d in dims}
    avg["total"] = round(sum(avg[d] for d in dims), 2)
    print("\n== 成绩单 ==")
    for r in sorted(rows, key=lambda x: x["i"]):
        sc = "/".join(str(r.get(d, "?")) for d in dims)
        print(f"  {r['emotion']}·{r['char']}: {sc}  {r.get('note','')}")
    print(f"\n均分 (判到 {len(ok)}/{len(rows)}): 看见情绪 {avg['seen']} · 贴人设 {avg['chara']}"
          f" · 像人话 {avg['natural']} · 入戏 {avg['immersion']} · 总 {avg['total']}/20")
    out = {"tag": args.tag, "avg": avg, "rows": rows}
    fn = f"eval_report_{args.tag}.json"
    json.dump(out, open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("已存", fn)


if __name__ == "__main__":
    main()
