"""Drive a full Chinese playthrough against the LIVE server to prove gating."""
import httpx

B = "http://127.0.0.1:8000/api/v1"
OUT = []


def log(*a):
    OUT.append(" ".join(str(x) for x in a))


with httpx.Client(base_url=B) as c:
    c.post("/auth/signup", json={"email": "demo_player@x.com", "password": "player123",
                                 "dob": "1995-05-05", "accepted_tos": True})
    c.post("/auth/login", json={"email": "demo_player@x.com", "password": "player123"})
    sid = c.get("/stories").json()["items"][0]["id"]
    pid = c.post("/personas", json={"name": "我", "pronouns": "they"}).json()["id"]
    rid = c.post("/runs", json={"story_id": sid, "persona_id": pid}).json()["id"]
    log(f"story={sid}\nrun={rid}\n" + "=" * 50)

    turns = [
        "老周，那几道安全门到底怎么回事，怎么会从外面锁上？",
        "小杨一直在哭，她在镜子里看到什么了？",
        "你的手电筒怎么说灭就灭了，监控里怎么找不到你",
        "镜子里到底是不是有六个人，多出来那个影子是谁",
        "你的手电筒、那些监控、照片，为什么从来没有你",
        "镜子，那第六个人，多出来的影子到底是什么",
        "苏婷查了刷卡记录，第五个名字谁都不认识",
        "刷卡记录上第五个名字……老周，你到底是谁，告诉我真相",
    ]
    for t in turns:
        r = c.post(f"/runs/{rid}/play", json={"input": t, "channel": "say"})
        dialogue = []
        for line in r.text.splitlines():
            if line.startswith("data:"):
                import json
                o = json.loads(line[5:])
                if o.get("event") == "beat" and o["beat"]["type"] == "dialogue":
                    dialogue.append(o["beat"]["text"])
        st = c.get(f"/runs/{rid}").json()["state"]
        log(f"\n>> 玩家: {t}")
        for d in dialogue:
            log(f"   老周: {d}")
        log(f"   [state] act={st['act']} affinity={st['affinity']} unlocked={len(st['unlocked_fragment_ids'])}")

with open("playthrough_out.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("done")
