# -*- coding: utf-8 -*-
"""Seed 《魔道祖师·引魂灯》— BL/耽美 showcase（忘羡同人致敬，案件剧情全原创）。

沿用九龙城寨先例：借用人物与世界观做同人致敬（非商用内测），文本全部原创。
玩法：扮演魏无羡与蓝忘机并肩夜猎（relation_default=flirt，开局即张力拉满），
或上帝模式旁观 CP。原创案件「引魂灯」：一对殉情乐师的执念，镜像问灵十三载。

Run:  python seed_mdzs.py   (idempotent; publishes public v1)
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from datetime import datetime  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Fragment, Persona, Run, Secret, Story, StorySnapshot, User  # noqa: E402
from app.routers.stories import _to_secret, _to_story  # noqa: E402
from app.security import hash_password  # noqa: E402

TITLE = "魔道祖师·引魂灯"
DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

CHARACTERS = [
    {
        "id": "mdz_wwx", "name": "魏无羡", "role": "夷陵老祖，重生归来",
        "is_lead": False, "playable": True,
        "persona_text": "嬉皮笑脸，满嘴跑马，逗人的本事天下第一。可玩笑话说到第三句，"
        "眼睛里偶尔会闪过十三年生死之外的东西，快得没人接得住。",
        "background": "借体重生没多久，走到哪儿都跟着一位面冷心热的含光君。",
        "items": [{"name": "陈情", "detail": "一支黑色竹笛，笛尾红穗磨得发亮"}],
    },
    {
        "id": "mdz_lwj", "name": "蓝忘机", "role": "含光君，姑苏蓝氏二公子",
        "is_lead": True,
        "persona_text": "抹额一丝不苟，白衣纤尘不染，一天说的话十根手指数得完。"
        "冷是真冷，但谁的伤都是他先看见，谁的酒都是他默不作声地付账。"
        "被撩到极限时耳根会红，表情纹丝不动。",
        "background": "外人只知含光君避尘不离身、逢乱必出。没人知道他这十三年是怎么过的。",
        "eq_style": "话极少，关心全部落在行动上；玩笑不接，但记得每一句；被戳破心事就沉默",
        "agenda": "这一次寸步不离地守着他。但有些话，要等他自己开口",
        "relation_default": "flirt",
        "relation_allowed": ["peer", "friend", "flirt", "lover"],
        "examples": [
            "嗯。",
            "不必。……拿着。",
            "魏婴。",
            "无聊。……但你高兴就好。",
            "夜里凉。披上。",
        ],
        "bio_layers": [
            {"closeness_min": 12, "text": "他的静室常年焚一种冷香。思追说，那香方十三年没换过。"},
            {"closeness_min": 25, "text": "他受过很重的戒鞭伤，从不让人看。医师只被放进去过一次。"},
            {"closeness_min": 40, "text": "云深不知处禁酒。可他的静室地下，埋着整整一排天子笑。"},
        ],
        "schedule": [
            {"from_act": 1, "location_id": "mdz_inn"},
            {"from_act": 2, "location_id": "mdz_path"},
            {"from_act": 3, "location_id": "mdz_shrine"},
            {"from_act": 4, "location_id": "mdz_jingshi"},
        ],
        "ties": [{"char_id": "mdz_szh", "stance": 2, "label": "亲手带大的孩子"},
                 {"char_id": "mdz_jl", "stance": 1, "label": "故人之侄"},
                 {"char_id": "mdz_wn", "stance": 1, "label": "看在一个人的份上"}],
    },
    {
        "id": "mdz_szh", "name": "蓝思追", "role": "姑苏蓝氏小辈，温润守礼",
        "persona_text": "十六七岁，行礼永远一板一眼，说话永远先想三秒。"
        "对魏无羡有种说不清的亲近，他自己也不知道为什么。",
        "eq_style": "礼数周全，心思细，看破不说破；着急时会忘了先生教的规矩",
        "agenda": "查清梦游人的事；顺便偷偷观察含光君和魏前辈——大家都看出来了，就他们俩没挑明",
        "examples": ["魏前辈，请用茶。", "含光君他……其实一直都……不，晚辈失言了。"],
        "home_location_id": "mdz_inn",
        "schedule": [{"from_act": 1, "location_id": "mdz_inn"},
                     {"from_act": 2, "location_id": "mdz_path"},
                     {"from_act": 3, "location_id": "mdz_shrine"}],
        "ties": [{"char_id": "mdz_lwj", "stance": 2, "label": "养育之恩"},
                 {"char_id": "mdz_wn", "stance": 2, "label": "说不出口的恩人"},
                 {"char_id": "mdz_jl", "stance": 1, "label": "斗嘴的同辈"}],
    },
    {
        "id": "mdz_jl", "name": "金凌", "role": "兰陵金氏少主，嘴硬心软",
        "appears_from_act": 2,
        "persona_text": "锦衣玉带，灵犬仙子不离身。一开口就带刺，被戳中软处就炸毛，"
        "炸完毛又会别别扭扭地把好东西塞过来。",
        "eq_style": "口嫌体正直；关心人只会用凶的方式",
        "agenda": "证明自己不靠舅舅也能办成事；顺便盯着这个来历可疑的魏无羡",
        "examples": ["谁要你管！……喂，那个给你，看在你没拖后腿的份上。", "仙子，咬他！"],
        "home_location_id": "mdz_path",
        "ties": [{"char_id": "mdz_szh", "stance": 1, "label": "拌嘴的交情"}],
    },
    {
        "id": "mdz_wn", "name": "温宁", "role": "鬼将军，藏在暗处",
        "appears_from_act": 3,
        "persona_text": "苍白，安静，说话轻得像怕碰碎什么。力气能拆山，性子软得欺负不还手。"
        "只在魏无羡身处险境时才现身。",
        "eq_style": "结结巴巴，善意藏都藏不住；被感谢会手足无措",
        "agenda": "远远跟着公子，不给他添麻烦；有个关于思追的秘密，他答应过不说",
        "examples": ["公子……我、我没事。", "对不起，吓到你们了……我马上就走。"],
        "home_location_id": "mdz_path",
        "ties": [{"char_id": "mdz_szh", "stance": 2, "label": "看着长大的孩子"}],
    },
]

LOCATIONS = [
    {"id": "mdz_inn", "name": "山下客栈", "detail": "掌柜的把门闩换成了三道，柜台上供着一碗倒扣的米。"
     "大堂里人人压着嗓子说话，说到「灯」字就住口。",
     "exits": ["上山官道"]},
    {"id": "mdz_path", "name": "上山官道", "detail": "青石板路被夜露浸得发黑，路边草叶上挂着一排排"
     "烧尽的纸灯骨架。越往上走，虫鸣越少。",
     "exits": ["山下客栈", "山腰旧祠", "静室"]},
    {"id": "mdz_shrine", "name": "山腰旧祠", "detail": "半塌的乐神祠，梁上悬着一盏完好得反常的白灯笼。"
     "供桌积灰里有两只并排放着的旧笛，一长一短。",
     "exits": ["上山官道"],
     "unlock": {"required_fragment_ids": ["mdz_case2"]},
     "props": [{"name": "引魂灯", "detail": "灯纸上密密写满小字，像一封没寄出去的信。",
                "fragment_id": "mdz_case3"}]},
    {"id": "mdz_jingshi", "name": "静室", "detail": "姑苏蓝氏的静室，冷香极淡。琴案一尘不染，"
     "唯独墙角一只旧木匣，摆得离床头很近。",
     "exits": ["上山官道"],
     "unlock": {"act_min": 4},
     "props": [{"name": "旧木匣", "detail": "没有上锁。匣盖内侧刻着一个「羡」字，刻痕很深，像是描过很多遍。",
                "fragment_id": "mdz_thirteen3"}]},
]

ACTS = [
    {"id": "a1", "index": 1, "title": "梦游的人", "time": {"day": 1, "slot": "夜"},
     "goal": "镇上接连有人提着白灯笼梦游上山。先从客栈里问出这灯的来路",
     "advance": {"required_fragment_ids": ["mdz_case1"]},
     "events": [
         {"id": "mdz_e_sleepwalk", "what_happens": "大堂里一阵骚动：白日里刚被抬回来的货郎又直挺挺地站了起来，手里不知何时多了一盏白灯笼。",
          "who_character_ids": []},
         {"id": "mdz_e_tea", "what_happens": "蓝忘机把一盏热茶放到你面前，又把你顺手拿的酒壶面无表情地挪远了半尺。",
          "who_character_ids": ["mdz_lwj"]},
     ]},
    {"id": "a2", "index": 2, "title": "上山", "time": {"day": 2, "slot": "夜"},
     "goal": "沿官道追梦游人的脚印。弄清旧祠里那对乐师的故事",
     "advance": {"required_fragment_ids": ["mdz_case2"]},
     "events": [
         {"id": "mdz_e_jl", "what_happens": "金凌带着仙子从岔路杀出来，嘴上说是路过，手里却攥着和你们一样的纸人符。",
          "who_character_ids": ["mdz_jl"]},
         {"id": "mdz_e_shadow", "what_happens": "队伍后方远远缀着一个影子，脚步声轻得不像活人。仙子冲着黑暗低吼，又莫名安静下来。",
          "who_character_ids": []},
     ]},
    {"id": "a3", "index": 3, "title": "旧祠", "time": {"day": 2, "slot": "夜"},
     "goal": "进旧祠。梁上那盏引魂灯写满了字，去读它",
     "advance": {"required_fragment_ids": ["mdz_case3"]},
     "events": [
         {"id": "mdz_e_duet", "what_happens": "祠里无风，供桌上那两支旧笛却同时轻轻响了半个音，像谁起了个头，在等另一个人接。",
          "who_character_ids": ["mdz_lwj"]},
     ]},
    {"id": "a4", "index": 4, "title": "十三年", "time": {"day": 3, "slot": "夜"},
     "goal": "灯要引的是「没等到的人」。可你忽然更想知道：你死后这十三年，他是怎么过的",
     "advance": {"required_fragment_ids": ["mdz_thirteen3"]},
     "events": [
         {"id": "mdz_e_guqin", "what_happens": "静室里琴声响了一夜。同一支曲子，翻来覆去，只有你听得出那是首问灵曲。",
          "who_character_ids": ["mdz_lwj"]},
     ]},
    {"id": "a5", "index": 5, "title": "灯为谁留", "time": {"day": 4, "slot": "夜"},
     "goal": "执念已解，灯该灭了。可它偏偏不灭，浮在你们两人之间，等一句话",
     "choice": {
         "prompt": "引魂灯的光落在蓝忘机脸上。他看着你，抹额的穗子被夜风吹起来，他没有躲。",
         "options": [
             {"id": "speak", "label": "「蓝湛，问灵十三载——你问的人，现在就站在这儿。」",
              "flag": "chose_speak", "character_id": "mdz_lwj",
              "closeness_delta": 4, "romance_delta": 6},
             {"id": "tease", "label": "笑着岔开：「这灯莫不是看上你了，含光君？」",
              "flag": "chose_tease"},
         ]},
     "events": [
         {"id": "mdz_e_lantern", "what_happens": "满山烧尽的纸灯骨架同时立了起来，无火自明，像一条送行的灯河。",
          "who_character_ids": ["mdz_lwj"]},
     ]},
]

# (title, character_id, sensitivity, known_by, [(fid, layer, content, retrieval_key, unlock, cover)])
SECRETS = [
    ("引魂灯的来历", "mdz_szh", "light", ["mdz_szh", "mdz_lwj"], [
        ("mdz_case1", 1,
         "梦游的人手里那盏白灯笼，镇上没人扎得出来——灯纸是三十年前的旧账房纸，糊灯的浆糊里掺着祭祀用的香灰。"
         "老人们说，山腰旧乐神祠里，从前就挂着这么一盏。",
         "灯 灯笼 白灯 来路 来历 哪里来 梦游 旧祠 祠堂",
         {"affinity_min": 0, "act_min": 1, "asks_min": 2},
         "不过是寻常邪祟作怪，烧了灯就干净了。"),
        ("mdz_case2", 2,
         "三十年前祠里住过一对乐师：吹笛的叫裴郎，抚琴的叫阿萤。两人约定灯亮为号、灯灭为散。裴郎下山采买遇了山洪，"
         "阿萤守着灯等了七年，灯油添到死。镇上人把祠封了，谁也不敢提。",
         "乐师 裴郎 阿萤 殉情 故事 从前 三十年 等 约定",
         {"affinity_min": 8, "act_min": 2, "asks_min": 2},
         None),
        ("mdz_case3", 3,
         "灯纸上的小字是阿萤写的：「不怪山洪，不怪路远。怪我只敢点灯，不敢说等你回来是想同你过一生。」"
         "这盏灯引的从来不是路——是替所有把话咽回去的人，找那个没等到的人。",
         "灯纸 小字 写的什么 读 信 引魂 执念",
         {"location_id": "mdz_shrine", "act_min": 3},
         None),
    ]),
    ("蓝忘机的十三年", "mdz_lwj", "heavy", ["mdz_lwj", "mdz_szh"], [
        ("mdz_thirteen1", 1,
         "思追说漏过嘴：含光君曾重伤静养整整三年，闭门谢客，连宗主都少见。那三年恰好是从乱葬岗出事那年算起的。",
         "十三年 这些年 三年 闭关 静养 受伤 过去 怎么过",
         {"affinity_min": 10, "act_min": 2, "asks_min": 2},
         "含光君的事，外人不便多问。"),
        ("mdz_thirteen2", 2,
         "问灵十三载。每一年，每一处传闻有怨魂的地方，他都去问。问的始终是同一个人。十三年，没有一次得到回应——"
         "因为那个人根本没有做鬼，他回来了。",
         "问灵 找谁 问谁 找我 十三载 为什么 等",
         {"affinity_min": 18, "act_min": 4, "asks_min": 3},
         None),
        ("mdz_thirteen3", 3,
         "旧木匣里：半截烧焦的红笛穗，和一张写满又划掉的纸。纸上反反复复只有一句问灵的起手指法，"
         "旁边小字注着：「若有回应，第一句说什么。」十三年，他连第一句话都排练好了。",
         "木匣 匣子 静室 藏着什么 里面 打开",
         {"location_id": "mdz_jingshi", "act_min": 4},
         None),
    ]),
    ("暗处的影子", "mdz_wn", "light", ["mdz_wn", "mdz_szh"], [
        ("mdz_wn1", 1,
         "夜里缀着队伍的影子是温宁。他一直没走远，怕吓着人不敢现身，只在你们看不见的地方把拦路的邪祟悄悄掰碎了。",
         "影子 跟着 后面 谁 脚步声 暗处",
         {"affinity_min": 0, "act_min": 2, "asks_min": 1},
         None),
    ]),
]

ENDINGS = [
    {"id": "mdz_end_true", "kind": "true", "title": "问灵有答",
     "text": "灯应声而灭。黑暗里蓝忘机的声音近得贴着耳廓，稳得吓人：「第一句，我排练了十三年。」"
             "他顿了顿，像把一生的话都压进两个字里——「别走。」满山灯河次第亮起，替一对乐师，也替你们，照完这段没走完的路。",
     "condition": {"affinity_min": 24, "act_min": 0,
                   "required_fragment_ids": ["mdz_thirteen3"],
                   "required_flags": {"chose_speak": True}}},
    {"id": "mdz_end_normal", "kind": "normal", "title": "并肩下山",
     "text": "灯在你的玩笑话里慢慢暗下去，像叹了口气。下山的路上谁都没说话，肩膀却挨得比来时近。"
             "走到山脚，蓝忘机忽然停住，把一样东西塞进你手里——是那半截烧焦的红笛穗。他什么也没说。你忽然觉得，这句话迟早会有人说出口的。",
     "condition": {"act_min": 0, "required_flags": {"chose_tease": True}}},
    {"id": "mdz_end_rumor", "kind": "bad", "title": "流言四起", "trigger": "pressure",
     "text": "「夷陵老祖回来了」的流言比引魂灯烧得更快。镇民的眼神变了，仙门的信鹤一封接一封。"
             "你趁夜色收拾行李，笛子刚别上腰——门口立着个白衣人影，抱着剑，堵住了唯一的路。他还是什么都不说，但这一次，他不打算再让你一个人走。",
     "condition": {}},
]

PRESSURE = {"name": "流言", "hint": "夷陵老祖的传闻在镇上发酵——张扬招摇会让它烧得更快",
            "ending_id": "mdz_end_rumor",
            "levels": [{"at": 40, "note": "茶棚里有人压低声音：那笛声……像是当年乱葬岗的调子。"},
                       {"at": 70, "note": "客栈掌柜换了副面孔，说柜上没房了。门外有仙门的人在抄录画像。"}]}


def get_or_create_demo_user(db) -> User:
    u = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if u:
        return u
    u = User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_PW),
             dob=datetime(1990, 1, 1), accepted_tos=True, display_name="Demo 作者")
    db.add(u)
    db.commit()
    db.refresh(u)
    db.add(Persona(owner_id=u.id, name="我", pronouns="they", is_default=True))
    db.commit()
    return u


def wipe_existing(db, owner_id: str) -> None:
    for s in db.query(Story).filter(Story.owner_id == owner_id, Story.title == TITLE).all():
        db.query(Run).filter(Run.story_id == s.id).delete()
        db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).delete()
        db.delete(s)
    db.commit()


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        user = get_or_create_demo_user(db)
        wipe_existing(db, user.id)

        story = Story(
            owner_id=user.id, title=TITLE, language="zh",
            one_liner="问灵十三载。这一次夜猎，灯要引的是「没等到的人」。",
            synopsis="山下小镇接连有人提着白灯笼梦游上山。你扮演重生归来的魏无羡，与蓝忘机并肩追查"
            "旧祠里那盏「引魂灯」——一对殉情乐师留下的执念。案子越查越深，你发现这盏灯照出的，"
            "不止是别人咽回去的话。（同人致敬 · 案件剧情原创 · 可开上帝模式旁观）",
            world_long="修真世界，云深不知处山下的小镇。深夜，白灯笼，梦游的人。"
            "客栈、官道、半塌的乐神祠，以及山上那间冷香不改的静室。",
            world_facts="可去四处：山下客栈（起点）通上山官道；官道通山腰旧祠与静室。"
            "旧祠需先问出乐师旧事才寻得到；静室要到第四幕才进得去。魏无羡随身带着陈情笛。"
            "梦游人手中的白灯笼与旧祠梁上的引魂灯同源。",
            relations_overview="魏无羡（你）与蓝忘机彼此心照不宣；蓝思追由蓝忘机带大，"
            "对魏无羡莫名亲近；金凌嘴硬心软处处别扭；温宁藏在暗处远远护着。",
            trope_tags=["耽美", "BL", "仙侠", "悬疑", "双向暗恋", "同人"],
            characters=CHARACTERS, acts=ACTS, endings=ENDINGS, locations=LOCATIONS,
            pressure=PRESSURE, phone={"enabled": True, "device": "传讯符"},
            tuning={"golden_chance": 6, "rom_taper_den": 100},
            visibility="public",
        )
        db.add(story)
        db.flush()

        for title, char_id, sens, known_by, frags in SECRETS:
            sec = Secret(story_id=story.id, character_id=char_id, title=title, sensitivity=sens)
            sec.fragments = [
                Fragment(id=fid, layer=l, content=c, retrieval_key=r,
                         known_by_character_ids=known_by, unlock=u, cover=cov)
                for (fid, l, c, r, u, cov) in frags
            ]
            db.add(sec)
        db.flush()
        db.refresh(story)

        content = {"story": _to_story(story).model_dump(),
                   "secrets": [_to_secret(s).model_dump() for s in story.secrets]}
        content["story"]["version"] = 1
        db.add(StorySnapshot(story_id=story.id, version=1, content=content))
        story.version = 1
        story.status = "published"
        db.commit()

        n_frag = sum(len(f) for *_, f in SECRETS)
        print(f"OK seeded 《{TITLE}》 story_id={story.id} secrets={len(SECRETS)} fragments={n_frag}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
