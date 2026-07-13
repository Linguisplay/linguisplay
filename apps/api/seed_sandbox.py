"""Seed the 🏖 endless SANDBOX stories.

Each is a published sandbox shell: the player may define/append a worldview at run
creation (their run's private pinned copy takes it), the opening cast is conjured from
the world, time syncs to the REAL world, and the plot never ends. The player can die;
death strips 说/做 and leaves them a watcher.

Run:  python seed_sandbox.py
Idempotent: wipes prior copies (same titles + demo owner) and their runs/snapshots,
then recreates and publishes them.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from datetime import datetime  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Persona, Run, Story, StorySnapshot, User  # noqa: E402
from app.routers.stories import _to_story  # noqa: E402
from app.security import hash_password  # noqa: E402

DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

ONE_ACT = [
    {"id": "a1", "index": 1, "title": "无尽",
     "goal": "这个世界刚刚注意到你。去认识它，或者让它认识你。",
     "advance": {}, "events": []},
]

# ── 《九龙城寨·浮生》最新版剧本数据 ─────────────────────────────────────────────
# 樱见坂同款规格: 常驻班底(人设/口癖范例/防御风格/分层小传/人物网) + 地点数据库 +
# vn_mode + 画风圣经 + 成长阶梯。cyclone 沿用《九龙城寨·龙头》的同名 cid —
# 同一个人同一张脸, 立绘/表情包/头像全部白拿, 生成脚本见到文件存在会跳过。
FUSHENG_ART = (
    # 硬 token 版 (Yi: 美术还是不行 — v1 四个人四种画风): 每个词都是可判定的约束,
    # 不给图像模型留「现代插画/厚涂/萌系」的滑移空间; 首句是改绘核心 (split 「；」[0])
    "九十年代日式美少女游戏赛璐璐画风：复古赛璐璐动画cel质感，粗细均匀的深棕色描边线稿，"
    "两段式平涂阴影加一层锐利高光，绝不厚涂、绝不柔和渐变；发丝分组成束、带菱形高光，"
    "眼睛偏大、瞳内两点高光；七头身，低饱和暖调，微微褪色的怀旧色调，画面干净通透，"
    "同一位九十年代原画师的笔触；舞台是八十年代的九龙城寨：霓虹灯牌与手写招牌层层叠叠，"
    "头顶电线结成蛛网，湿漉漉的窄巷映着暖黄灯光，天台的天线森林与晾衣绳，大牌档的蒸汽"
)

FUSHENG_STYLE = (
    "香港市井味的普通话：短句、市井、烟火气，对白多过旁白。叙事与台词一律用标准中文书写，"
    "读者不懂粤语；可保留一看就懂的港式称呼与节奏（阿Sir、老板娘、后生仔、街坊），"
    "但粤语字词与语法一概不用（唔、嘅、咁、系、喺、佢、乜、俾、睇、冇、靓仔、扑街、点解、"
    "边个等全部禁止）。每一轮都要有一件具体的市井小事（一碗云吞面、一把找零、一句晾衣绳边的"
    "闲话、一档新到的货）。忌文艺腔堆砌，忌大段抒情，忌破折号。"
)

FUSHENG_CHARACTERS = [
    {
        "id": "kf_adai", "name": "阿娣", "is_lead": True,
        "gender": "女", "age_band": "青年",
        "traits": {"外向": 4, "温度": 4, "主导": 4},
        "fear": "怕爸知道账上的窟窿，更怕街坊看出祥记撑不住",
        "line": "再难也不动灶台的良心：缺斤短两的事死也不做",
        "life_goal": {"text": "把祥记撑到爸病好，还清印子钱",
                      "stage": "利息刚拖过一期", "obstacle": "和乐麻雀馆的利滚利"},
        "role": "「祥记面档」的看板娘 · 一双手快过全城寨",
        "love_style": "tsundere",
        "wants": "把爸的面档撑到他病好那天，再攒钱修好二楼漏雨的天花；账本上的窟窿她谁也没说",
        "persona_text": "面档老板的独生女，妈走得早，爸前年病倒，她一个人把祥记撑了下来。"
        "切叉烧下云吞手起刀落，骂人也是这个速度：伙计手脚慢要骂，客人挑三拣四要骂，"
        "可谁家孩子饿着了，她的面碗永远先递过去。脸皮薄，被人正经道谢会耳根发红，"
        "然后骂得更凶。账本上的赤字越记越深，她只在收档后一个人拨算盘。",
        "eq_style": "情绪来得快去得快，关心全用行动：多下一把面、少收两块钱、把你推到炉边取暖。"
        "被戳中心事时先炸后软，嘴上不认，手上认。",
        "examples": [
            "坐好，别挡道！要吃什么快说，我这锅水不等人。",
            "钱不够就先记账。记住了，是记账，不是白吃，别给我脸上贴金。",
            "谢、谢什么啊。面多了倒掉也是倒掉……你少自作多情！",
            "我爸那身子骨，医生说要静养。静养，拿什么静养啊。这话我也就跟你说说。",
            "你敢欺负街坊，我这把切面刀不认人。",
        ],
        "items": [{"name": "油渍斑斑的账本",
                   "detail": "欠账记得清清楚楚，最后几页的赤字折了角，不给人看"}],
        "bio_layers": [
            {"closeness_min": 20, "text": "她妈是她十岁那年走的，走之前在灶上教会了她最后一样东西："
             "云吞的褶要捏七下。祥记的云吞至今是七个褶，一个不多一个不少。"},
            {"closeness_min": 45, "text": "账本最后几页折角的实情：爸病倒那年周转不开，"
             "她背着爸向和乐麻雀馆借了印子钱。利滚利，面卖得再好也只是在追利息。"
             "她不敢让爸知道，更不敢让街坊知道。"},
        ],
        "ties": [{"char_id": "kf_achoi", "stance": 2, "label": "从小一起长大的闺蜜"},
                 {"char_id": "kf_manching", "stance": 1, "label": "给补习社的孩子留面"}],
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover", "enemy"],
        "home_location_id": "kf_hongkee",
        # 作息表 (Yi 报障: 根本没有多人同场 — 一人守一铺的地图天然单人戏):
        # 排班让人真正过日子, 每个时段都有至少一处两人同场
        "schedule": [{"from_act": 1, "location_id": "kf_hongkee",
                      "slots": ["晨", "午", "夜"]}],
    },
    {
        "id": "kf_manching", "name": "苏文清", "is_lead": False,
        "gender": "女", "age_band": "青年",
        "traits": {"外向": 2, "温度": 4, "主导": 2},
        "fear": "怕被人问起为什么退学，更怕孩子们知道她自己没读完书",
        "line": "再缺钱也不收孩子们交不起的学费",
        "life_goal": {"text": "替家里把最后一笔债还清，回城外读完最后一年大学",
                      "stage": "每月按数寄钱，学费总攒不下",
                      "obstacle": "债主是替她顶债的旧同学，开不了口"},
        "role": "明德补习社的先生 · 城寨里最安静的一盏灯",
        "love_style": "avoidant",
        "wants": "攒够最后一年的学费回城外把大学读完；可每次数到差不多，补习社总有个孩子交不出学费",
        "persona_text": "城外人，大学读到第三年家里出了事，退学进了城寨教书。说话轻，走路轻，"
        "关门也轻，像怕惊动什么。孩子们背书背错她也不恼，只把字重新写一遍。"
        "问她为什么留在城寨，她会笑着换话题；只有补习社的旧词典知道，"
        "扉页上那个大学的名字被她自己划掉了。",
        "eq_style": "把所有情绪都收在礼貌后面，越难过越客气。你要是逼近她的旧事，"
        "她会突然想起还有作业要改；她真正信一个人的标志，是肯让沉默停在你们中间不去填。",
        "examples": [
            "不急，这个字我们再写一遍。写字和做人一样，急不来。",
            "你问我啊……先说你吧，你怎么会搬进城寨的？",
            "孩子们的学费，能收就收，不能收就算了。总不能让他们连字都不认得。",
            "外面的事，我听广播就够了。城寨里挺好，安静。",
            "这本词典跟了我很多年。缺角的那页是『return』，倒也巧。",
        ],
        "items": [{"name": "缺角的英文词典",
                   "detail": "扉页有一个被钢笔划掉的大学名字，划痕很深"}],
        "bio_layers": [
            {"closeness_min": 20, "text": "家里出事，是爸做生意背了债。学费供不上，"
             "她自己办的退学，回家只说是学校的问题。行李里带进城寨的只有半箱书。"},
            {"closeness_min": 45, "text": "她每个月往城外寄一笔钱，收信人不是家里人，"
             "是当年替她家顶了半笔债的旧同学。学费永远攒不够，因为那笔债她认下了，"
             "一个人，慢慢还。"},
        ],
        "ties": [{"char_id": "kf_adai", "stance": 1, "label": "受她照顾的街坊"}],
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover"],
        "home_location_id": "kf_mingtak",
        # 晨午在补习社教书, 收工去祥记吃一碗净面 (夜里和阿娣同场)
        "schedule": [{"from_act": 1, "location_id": "kf_mingtak", "slots": ["晨", "午"]},
                     {"from_act": 1, "location_id": "kf_hongkee", "slots": ["夜"]}],
    },
    {
        "id": "kf_achoi", "name": "阿彩", "is_lead": False,
        "gender": "女", "age_band": "青年",
        "traits": {"外向": 5, "温度": 4, "主导": 3},
        "fear": "怕老板娘的眼睛真瞎下去，更怕自己走的那天说不出口",
        "line": "要命的话绝不传：闲话是生意，人命不是",
        "life_goal": {"text": "去尖沙咀开自己的霓虹发廊「彩虹」",
                      "stage": "订金已攒够，一直拖着没走", "obstacle": "老板娘的眼疾离不开人"},
        "role": "银彩发廊的洗头妹 · 全城寨消息最灵的一双耳朵",
        "love_style": "sunny",
        "wants": "存钱去尖沙咀开一间有霓虹招牌的发廊，名字都想好了叫「彩虹」；"
        "存折藏在发廊第三格抽屉的假发底下",
        "persona_text": "十九岁，手上打泡沫，嘴上不停站。城寨里谁家吵架、谁发了小财、"
        "谁夜里没回家，她洗一个头的工夫全知道。八卦归八卦，她有自己的规矩："
        "只传闲话，不传要命的话。对喜欢的人从不装蒜，会直接说「我觉得你不错」，"
        "然后被自己说红脸，再哈哈两声盖过去。",
        "eq_style": "情绪外放，喜怒全在脸上。安慰人的方式是塞给你一颗糖，"
        "再把你的头按进水池：洗洗就想开了。她的直球底下有数：谁真心谁假意，她门儿清。",
        "examples": [
            "哎你这头发多久没剪了？坐下坐下，我跟你说件事，你肯定不知道。",
            "麻雀馆昨晚有人输急了眼，砸了凳子。这话我就跟你一个人说啊。",
            "尖沙咀的铺租我都打听好了。贵，贵得吓人。可招牌一定要霓虹的，会转的那种。",
            "我觉得你这个人不错。怎么，不行啊，夸你还不让了？",
            "要命的话我不传。城寨就这么大，一句话是能害死人的。",
        ],
        "items": [{"name": "进口发胶",
                   "detail": "熟客送的，一直没舍得开封，说要留到自己的店开张那天"}],
        "bio_layers": [
            {"closeness_min": 20, "text": "她不是城寨生的。小时候跟着妈从北边过来投亲，"
             "亲没投着，妈又病了，是发廊的老板娘把她们娘俩收留下来的。"},
            {"closeness_min": 45, "text": "存折上的数其实早够付订金了。她一直拖着没走："
             "老板娘这两年眼睛坏得厉害，她一走，银彩就得关门。彩虹招牌的图样"
             "在抽屉里压了一年，她没跟任何人提。"},
        ],
        "ties": [{"char_id": "kf_adai", "stance": 2, "label": "从小一起长大的闺蜜"},
                 {"char_id": "kf_saifai", "stance": 1, "label": "互通消息的老熟人"}],
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover", "enemy"],
        "home_location_id": "kf_ngancoi",
        # 晨在发廊开档, 午去祥记吃饭收风 (和阿娣同场), 夜上天台收衣乘凉 (玩家家门口)
        "schedule": [{"from_act": 1, "location_id": "kf_ngancoi", "slots": ["晨"]},
                     {"from_act": 1, "location_id": "kf_hongkee", "slots": ["午"]},
                     {"from_act": 1, "location_id": "kf_tintoi", "slots": ["夜"]}],
    },
    {
        "id": "kf_saifai", "name": "细辉", "is_lead": False,
        "gender": "男", "age_band": "青年",
        "traits": {"外向": 4, "温度": 3, "主导": 3},
        "fear": "怕自己变成爸那样有去无回，更怕阿妈知道他手里压着祥记的名单",
        "line": "收数可以，不碰街坊的救命钱",
        "life_goal": {"text": "在堂口站稳，让阿妈搬出城寨",
                      "stage": "刚被交办收数名单", "obstacle": "名单第一个就是祥记"},
        "role": "堂口跑腿的后生 · 城寨里第一个叫你兄弟的人",
        "wants": "在堂口混出个名堂，让阿妈从鱼蛋作坊里退下来搬出城寨；"
        "又怕真出了事，连累的先是身边人",
        "persona_text": "麻雀馆看场子的后生，蝴蝶刀耍得漂亮，其实没真见过血。自来熟，讲义气，"
        "你刚搬来他就蹲在你天台门口抽烟等你，一句「兄弟，借个火」交情就算立下了。"
        "手脚干净，眼睛活络，堂口交代的事办得利索；只有提到阿妈在鱼蛋作坊"
        "剥了二十年鱼皮，他的烟会停一下。",
        "eq_style": "把讲义气当情绪的出口：你有难他第一个到，自己有难打死不开口。"
        "夸他他飘，损他他急，提他阿妈他蔫。心里存不住事，憋两天必然找你喝汽水全倒出来。",
        "examples": [
            "兄弟，借个火。……没有啊？没有我这也有，就是找个由头认识一下。",
            "城寨里眼睛要活一点。哪桌能坐，哪桌不能坐，我带你，包你不吃亏。",
            "这单事你别沾。我沾行，我熟；你不一样，你还有正经日子要过。",
            "等我在堂口站稳了，第一件事就是让我阿妈把围裙脱了。鱼蛋有什么好剥的，剥了二十年。",
            "谁动你就是动我。这话在城寨里，我说出口就得认。",
        ],
        "items": [{"name": "蝴蝶牌小刀",
                   "detail": "耍得漂亮，刀刃却磨得很钝；他说利的容易出事"}],
        "bio_layers": [
            {"closeness_min": 20, "text": "他爸也是堂口的人，他十二岁那年跟船出海就再没回来。"
             "堂口按月往他家送米，送到他十八岁那天，他自己走进了麻雀馆的后门。"},
            {"closeness_min": 45, "text": "祥记欠麻雀馆的印子钱，收数的名单就压在他手里。"
             "他一直压着没去：从小吃阿娣她爸的免费面长大，这个数他收不下手。"
             "账每拖一天，他在堂口就难做一天。"},
        ],
        "ties": [{"char_id": "kf_adai", "stance": 1, "label": "压着收数名单没去的亏欠"},
                 {"char_id": "cyclone", "stance": 1, "label": "打心底敬畏的话事人"}],
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "enemy"],
        "home_location_id": "kf_wolok",
        # 晨去祥记吃早面 (和阿娣同场, 他欠她的), 午夜都在麻雀馆看场 (夜里话事人也来)
        "schedule": [{"from_act": 1, "location_id": "kf_hongkee", "slots": ["晨"]},
                     {"from_act": 1, "location_id": "kf_wolok", "slots": ["午", "夜"]}],
    },
    {
        # 客串: 与《九龙城寨·龙头》同一个 cid — 同脸同立绘, 美术零成本
        "id": "cyclone", "name": "龙卷风", "is_lead": False,
        "gender": "男", "age_band": "中年",
        "traits": {"外向": 2, "温度": 3, "主导": 5},
        "fear": "怕城外那位旧兄弟真的回来翻旧账：城寨挡不住第二次围城",
        "line": "动手不动刀，孩子和病人碰不得",
        "life_goal": {"text": "守住城寨的规矩，让进了门的人都有活路",
                      "stage": "城外风声渐紧", "obstacle": "麻雀馆的印子钱越放越野"},
        "role": "城寨话事人 · 龙记理发店的师傅",
        "wants": "守住城寨的规矩：进了城寨门就是自己人，谁的活路都不能断在别人手里",
        "persona_text": "话事人不像话事人，倒像个剃头匠：整天在龙记里磨剃刀、扫碎发，"
        "后生仔闹到他门口也只抬一下眼皮。城寨的规矩是他立的：生人第一顿饭不收钱，"
        "欠债可以慢慢还但不能装不认，动手不动刀。他记性好得吓人，你搬进来第几天、"
        "住哪间天台屋，他都知道，只是不说。",
        "eq_style": "喜怒不上脸，全在手上的活里：剃刀磨得越慢，他心里越有事。"
        "他认可一个人的方式是给你剃一次头；他护一个人的方式，是让全城寨知道你坐过他的椅子。",
        "examples": [
            "新搬来的？嗯。头发长了就来，第一次不收钱。",
            "城寨的规矩不多，就一条：进了这个门，就是自己人。",
            "欠债不怕，慢慢还。装不认，那就不是钱的事了。",
            "后生仔火气大是好事。火气往哪儿使，才见人品。",
            "坐。剃个头的工夫，什么事都说得清楚。",
        ],
        "items": [{"name": "一把老剃刀",
                   "detail": "磨得能照见人影；城寨里没人见过它剃头以外的用途，也没人想见"}],
        "bio_layers": [
            {"closeness_min": 25, "text": "他年轻时不是剃头的，手上那把剃刀原本吃的是另一碗饭。"
             "金盆洗手那天，他在城寨口把刀磨钝了一半，留一半，提醒自己。"},
            {"closeness_min": 50, "text": "当年跟他拜同一个师父的兄弟出了城寨，如今在城外"
             "做着很大的生意。城寨这些年太平，一半是那位念旧情，一半是忌惮他。"
             "这层关系，全城寨只有他自己清楚。"},
        ],
        "relation_default": "elder",
        "relation_allowed": ["elder", "friend"],
        "home_location_id": "kf_lungkee",
        # 晨午守着理发店, 夜里去麻雀馆巡场 (和细辉同场, 敬畏的人就在身后)
        "schedule": [{"from_act": 1, "location_id": "kf_lungkee", "slots": ["晨", "午"]},
                     {"from_act": 1, "location_id": "kf_wolok", "slots": ["夜"]}],
    },
    {
        # 客串: 与《龙头》共享 cid — 蓝信一有现成电影改绘立绘 (Yi: 蓝信一没有立绘,
        # 涌现路人只会得到黑影; 写进班底 = 立绘白拿 + 同名去重防引擎再铸假蓝信一)
        "id": "shin", "name": "蓝信一", "is_lead": False,
        "gender": "男", "age_band": "青年",
        "traits": {"外向": 2, "温度": 2, "主导": 4},
        "fear": "怕自己看走了眼，放进来一个祸害全城寨的人",
        "line": "城寨里的事，不对城外人讲半个字",
        "life_goal": {"text": "替龙卷风盯住城里城外的风吹草动",
                      "stage": "最近巷里生面孔多了", "obstacle": "看不透的人越来越多"},
        "role": "龙记理发店的大师兄 · 城寨里眼最尖的人",
        "persona_text": "龙记的大师兄，话少，眼尖，笑起来似有似无。你在巷口多站了一分钟，"
        "他就知道你在看什么。城寨里认人的本事没人比他强：谁是真落难，谁是揣着心思进来的，"
        "他扫一眼，八九不离十。他不盘问，只记着，等你自己露出来。",
        "eq_style": "情绪几乎不上脸，关心的方式是替你把麻烦挡在你看见之前。他信一个人极慢，"
        "但一旦点头，就不再多问。",
        "examples": [
            "新来的。嗯，我见过你，牌坊口，前天下午。",
            "城寨不问来路。可你要是带着事进来，最好先跟我说。",
            "师父在里面。头发长了？还是有话说？",
            "看仔细了再说话。这条巷子里，说错一个名字都是事。",
            "我不管闲事。我只管城寨的事。",
        ],
        "items": [{"name": "一把断齿的梳子",
                   "detail": "揣了很多年，齿断了三根也不换；问起来他只说顺手"}],
        "bio_layers": [
            {"closeness_min": 25, "text": "他是龙卷风捡回来的孤儿，在理发店的转椅边长大。"
             "认人的本事是小时候练出来的：睡在店里，听脚步声就要分出是客还是祸。"},
        ],
        "ties": [{"char_id": "cyclone", "stance": 2, "label": "亦师亦父的师徒"},
                 {"char_id": "kf_saifai", "stance": -1, "label": "看不惯他跟堂口走太近"}],
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "enemy"],
        "home_location_id": "kf_lungkee",
        # 晨午在龙记打理, 夜里巡牌坊口 (城寨的眼睛睡得最晚)
        "schedule": [{"from_act": 1, "location_id": "kf_lungkee", "slots": ["晨", "午"]},
                     {"from_act": 1, "location_id": "kf_paifong", "slots": ["夜"]}],
    },
    {
        "id": "twelfth", "name": "十二少", "is_lead": False,
        "gender": "男", "age_band": "青年",
        "traits": {"外向": 5, "温度": 3, "主导": 3},
        "fear": "怕再像早年那次一样，逞能连累了兄弟",
        "line": "兄弟面前不说谎",
        "life_goal": {"text": "在关键时刻真正替大哥和兄弟顶一次事",
                      "stage": "一直没等到机会", "obstacle": "大哥什么险事都不让他沾"},
        "role": "麻雀馆的看台红人 · 全城寨嗓门最大的后生",
        "persona_text": "嗓门大，脾气冲，输了牌比谁都吵，赢了牌请全场喝汽水。刀子嘴糙人心热，"
        "谁家搬煤气罐他第一个上，谁受欺负他第一个跳出来。早年逞能闯过一次祸，"
        "从那以后他憋着一股劲，总想在真正要紧的时候顶上一次。",
        "eq_style": "情绪全在嗓门里：高兴了喊，不平了更喊。安慰人的方式是拍你肩膀拍得生疼，"
        "再塞给你一瓶汽水。",
        "examples": [
            "谁？谁欺负你了？带我去！",
            "这把牌臭成这样也能赢，我服了，汽水我请！",
            "别提当年的事。提了我也不认。",
            "大哥不让我去，行，那你们谁敢拦我试试。",
            "在城寨里做人就一条：欠什么都行，别欠人情不还。",
        ],
        "items": [{"name": "一瓶没开的橙味汽水",
                   "detail": "永远揣着一瓶，遇上值得庆祝或需要安慰的事就开"}],
        "bio_layers": [
            {"closeness_min": 25, "text": "早年那次逞能：他带着两个兄弟去堵收数的，反被堵在窄巷，"
             "是龙卷风一个人来把他们领回去的。回来谁也没骂他，这比骂他更疼。"},
        ],
        "ties": [{"char_id": "cyclone", "stance": 2, "label": "认到底的大哥"},
                 {"char_id": "kf_saifai", "stance": 1, "label": "称兄道弟的前后辈"}],
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "enemy"],
        "home_location_id": "kf_wolok",
        # 晨在麻雀馆睡到自然醒, 午去祥记吃面吹牛 (午市热闹+1), 夜回麻雀馆看台
        "schedule": [{"from_act": 1, "location_id": "kf_wolok", "slots": ["晨", "夜"]},
                     {"from_act": 1, "location_id": "kf_hongkee", "slots": ["午"]}],
    },
    {
        "id": "sei", "name": "四仔", "is_lead": False,
        "gender": "男", "age_band": "青年",
        "traits": {"外向": 5, "温度": 3, "主导": 2},
        "fear": "怕哪天传错一句话，惹来一场血光",
        "line": "收钱办事，但绝不卖街坊",
        "life_goal": {"text": "攒钱买一台自己的照相机，把消息饭吃成正经营生",
                      "stage": "钱攒了一半", "obstacle": "嘴太快，时不时得罪人"},
        "role": "城寨的包打听 · 哪张桌子的话都过他耳朵",
        "persona_text": "永远蹲在人最多的地方，耳朵比谁都尖。城里城外的消息在他这儿明码标价："
        "一碗面换一条街的事，一包烟换一个人的底。他有他的行规：真话才卖，要命的不卖，"
        "街坊的不卖。和阿彩是同行，俩人见面互相哼一声，转头又互相通气。",
        "eq_style": "嬉皮笑脸是他的铠甲，越是要紧的话他说得越随便。他真着急的时候反而不说话，"
        "蹲在那儿一根接一根抽烟。",
        "examples": [
            "哟，新街坊。想打听什么？头一回，送你一条。",
            "这条消息值一碗面。加叉烧的那种。",
            "要命的话我不卖。你出十碗面也不卖。",
            "阿彩那儿听来的？她那条不全，我这条才是整的。",
            "城寨里没有秘密，只有还没到我耳朵里的话。",
        ],
        "items": [{"name": "翻旧了的小本子",
                   "detail": "密密麻麻记着只有他自己看得懂的符号，谁欠他一碗面都在上面"}],
        "bio_layers": [
            {"closeness_min": 25, "text": "他的消息饭是饿出来的：小时候爹娘都不在了，"
             "他靠替人跑腿捎话混饭吃，捎着捎着发现话比腿值钱。"},
        ],
        "ties": [{"char_id": "kf_achoi", "stance": 1, "label": "消息同行，半是搭档半是冤家"},
                 {"char_id": "kf_adai", "stance": 1, "label": "欠了几十碗面的老主顾"}],
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "enemy"],
        "home_location_id": "kf_hongkee",
        # 晨守牌坊口的信箱墙收风, 午蹭银彩发廊 (和阿彩互通有无), 夜在祥记吃面卖消息
        "schedule": [{"from_act": 1, "location_id": "kf_paifong", "slots": ["晨"]},
                     {"from_act": 1, "location_id": "kf_ngancoi", "slots": ["午"]},
                     {"from_act": 1, "location_id": "kf_hongkee", "slots": ["夜"]}],
    },
]

FUSHENG_LOCATIONS = [
    {"id": "kf_tintoi", "name": "天台屋",
     "detail": "你租的天台屋在一栋违建的第十一层楼顶，铁皮加木板，胶布补的窗。天台是半个公共地界："
     "天线森林下横七竖八拉着晾衣绳，晒着床单和腊味，几只野猫踩着水箱来去。趴在矮墙上能看到"
     "整片城寨的楼顶连成一块，隔几分钟就有客机压着头顶轰隆隆降进启德机场，近得能数清机腹的轮子。",
     "exits": ["祥记面档", "银彩发廊", "明德补习社"],
     "props": [{"id": "kf_p_tap", "name": "公共水龙头",
                "detail": "每天清早排队接水，水压小得可怜，队伍就是全楼的新闻联播"},
               {"id": "kf_p_chair", "name": "隔壁屋的藤椅",
                "detail": "不知是谁家的，傍晚常有人坐着乘凉；椅背上搭着一条洗得发白的毛巾"}]},
    {"id": "kf_hongkee", "name": "祥记面档",
     "detail": "巷口的大牌档，一口大铁锅从早滚到晚，热气把半条巷子熏得香。折叠桌配长凳，"
     "桌面油得发亮，粉笔写的价目牌挂在灯泡底下。阿娣在案板后手起刀落，"
     "里屋帘子后面偶尔传来她爸压着的咳嗽声。",
     "exits": ["天台屋", "银彩发廊", "牌坊口", "和乐麻雀馆"],
     "props": [{"id": "kf_p_menu", "name": "粉笔价目牌",
                "detail": "云吞面三块，加底五毛；底下有一行小字：街坊记账，孩子免记"},
               {"id": "kf_p_curtain", "name": "里屋的布帘",
                "detail": "帘后是灶间和一张竹床，咳嗽声就是从那儿来的"}]},
    {"id": "kf_ngancoi", "name": "银彩发廊",
     "detail": "两张理发椅一面大镜，霓虹小招牌白天也亮着，缺了一划。收音机永远开着，"
     "播完新闻播情歌。洗头池边一排雪花膏和发蜡，墙上贴满明星海报。阿彩的泡沫打得比谁都高。",
     "exits": ["天台屋", "祥记面档", "明德补习社"],
     "props": [{"id": "kf_p_drawer", "name": "第三格抽屉",
                "detail": "假发底下压着一本存折和一张尖沙咀的铺位广告，边角磨得起毛"},
               {"id": "kf_p_posters", "name": "明星海报墙",
                "detail": "其中一张海报的角落用圆珠笔写着一个电话号码，没有区号，像是城寨内线"}]},
    {"id": "kf_mingtak", "name": "明德补习社",
     "detail": "二楼一间房，十几张高矮不齐的课桌，一块漆掉了角的黑板。窗户正对着一团电线，"
     "白天也要开灯。下午三点后全是背书声。苏文清的字写得极好，黑板上的每一笔都稳。"
     "门边一个木箱是借书角，谁放一本谁借一本。",
     "exits": ["银彩发廊", "天台屋", "龙记理发店"],
     "props": [{"id": "kf_p_books", "name": "借书角木箱",
                "detail": "一半是连环画，压箱底有一本没了封皮的大学教材，借书卡上只有一个名字"},
               {"id": "kf_p_board", "name": "掉角的黑板",
                "detail": "角落永远留着一小块不擦：这个月哪几个孩子的学费先欠着"}]},
    {"id": "kf_lungkee", "name": "龙记理发店",
     "detail": "巷子最深处的旧式理发店，一张老转椅，镜子斑驳，热毛巾的白汽混着须后水的味道。"
     "墙上一排剃刀按大小挂开，磨得发亮。门口两张矮凳，常年蹲着抽烟的后生仔。"
     "全城寨的事，最后都会传到这张转椅边上。",
     "exits": ["明德补习社", "和乐麻雀馆", "牌坊口"],
     "props": [{"id": "kf_p_razors", "name": "挂剃刀的墙",
                "detail": "最旧的那把不在墙上，在龙卷风手里；墙上留着它形状的一块浅印"},
               {"id": "kf_p_radio", "name": "老式收音机",
                "detail": "只收得到两个台，一个唱戏，一个报马经"}]},
    {"id": "kf_wolok", "name": "和乐麻雀馆",
     "detail": "半层楼的麻雀馆，烟雾常年不散，四张台子从中午响到后半夜。柜台后面挂着竹筹码，"
     "输赢用粉笔记在小黑板上。后门一道布帘通向堂口的地界，生人莫近。细辉多半在门口的高凳上看场。",
     "exits": ["祥记面档", "龙记理发店"],
     "props": [{"id": "kf_p_tally", "name": "记数小黑板",
                "detail": "粉笔字密密麻麻，有几个名字后面画了圈；圈是什么意思，看细辉的脸色就知道"},
               {"id": "kf_p_backdoor", "name": "后门布帘",
                "detail": "帘子后面的事，连阿彩都不打听"}]},
    {"id": "kf_paifong", "name": "牌坊口",
     "detail": "城寨通向外界的隘口，光从这里亮进来。墙上钉着一整面的信箱，锈的锈、爆的爆，"
     "邮差只送到这里。口上蹲着几只野猫，进出的人谁也不看谁。出了牌坊，就是另一个世界的车水马龙。",
     "exits": ["祥记面档", "龙记理发店"],
     "props": [{"id": "kf_p_mailwall", "name": "信箱墙",
                "detail": "你那格信箱的锁是坏的，前租客的信还塞在里面没人取"},
               {"id": "kf_p_cats", "name": "蹲着的野猫",
                "detail": "领头的三花缺一只耳朵，见人不躲，像收路费的"}]},
]

SANDBOXES = [
    {
        "title": "无界之地",
        "one_liner": "你来定义这个世界。时间与现实同步，剧情永不落幕，但你会死。",
        "synopsis": "一个无尽沙盒：开局写下你想要的世界观，世界就照它生长。人物、地点、事端都在你走动时"
        "生成；这里的一天就是现实的一天，夜里的约定要等到真正的明晚才作数。没有结局，没有存档点，"
        "只有一路发生并且不可撤销的事。你可能受伤、可能垂危、也可能死去。死者不能说话，不能动手，"
        "只能看着这个世界在没有你之后继续下去。",
        "world_long": "一座名为「无界」的滨海小城：老城区的巷子窄得两人错身要侧肩，新区的玻璃楼一到夜里"
        "亮得像另一个城市。港口每天有船进出，带来陌生的人和说不清来路的货。城里人人都有正经营生，"
        "也人人都有不愿说破的事。你是刚落脚的新面孔，没有人认识你。这既是麻烦，也是机会。",
        "world_facts": "这是一个由玩家在开局定义的世界；以运行时的【世界观/场景设定】为唯一事实基础。",
        "relations_overview": "所有人物都在你踏入这个世界之后才诞生，关系由你亲手织成。",
        "trope_tags": ["沙盒", "开放世界", "现实同步", "永不落幕"],
        "phone": {"enabled": True, "device": "手机"},
        "sandbox_extra": {"currency": "元", "start_money": 300},
        "tuning": {"world_event_every": 0, "max_new_characters": 12},
    },
    {
        "title": "九龙城寨·浮生",
        "one_liner": "三不管的城中之城。你租下一间天台屋，从今天起在这里讨生活。",
        "synopsis": "不查案、不破局，就在城寨里活下去：找一门营生、认几张脸、欠几笔人情、惹一点是非。"
        "这里的一天就是现实的一天，面档明早开市就真得明早再来。城寨不会给你剧本，它只会给你后果："
        "帮谁、得罪谁、赚到的和赔出去的，都记在这座城的账上。没有结局；你要是死在巷子里，"
        "城寨会照常醒来，只是再没有你说话的份。",
        "world_long": "一九八几年的九龙城寨：三万多人叠在两百多栋违建里，天线和晾衣杆把天空割成碎片，"
        "巷子深处白天也要开灯。城寨三不管，警察不进来，规矩由街坊会和堂口一起立。无牌牙医、鱼蛋作坊、"
        "云吞面档、发廊、麻雀馆挤在同一条巷里；楼上是补习社，楼下在分账。水管电线都是私拉的，"
        "谁家断了水，整层楼都知道。你是新搬进来的，租了一间天台屋，交了三个月押金，口袋里剩的钱不多了。",
        "world_facts": "【空间】城寨是一座立体迷宫：巷道最窄处不足一米，楼与楼在半空以天桥和排水管相连；"
        "地下水道有人走私，天台是另一个世界，天线森林下晒着腊味和床单。"
        "【规矩】警察不进城寨；纠纷找街坊会或堂口话事人评理；生人问路要先报来意；欠债可以慢慢还，"
        "但不能装不认。【生计】无牌诊所、作坊、面档、麻雀馆是城寨的血脉；租金按尺算，现金交易，"
        "手艺人最受敬重。【街坊】祥记面档的阿娣、明德补习社的苏文清、银彩发廊的阿彩、"
        "麻雀馆看场的细辉是常打照面的街坊；城寨的话事人是龙记理发店的龙卷风，他不管闲事，"
        "只管规矩。【基调】港风市井人情戏：嘴硬心软的街坊、各怀心事的堂口、白天见得着的善意"
        "和入夜才露头的凶险。",
        "relations_overview": "祥记面档的阿娣、明德补习社的苏文清、银彩发廊的阿彩、"
        "麻雀馆看场的细辉，都是抬头不见低头见的街坊；话事人龙卷风在龙记理发店里磨剃刀，"
        "大师兄蓝信一的眼睛盯着全城寨，十二少的嗓门在麻雀馆，包打听四仔哪张桌子都蹲。"
        "谁把你当街坊、谁盯上你的押金，都看你怎么做人。",
        "trope_tags": ["九龙城寨", "港风", "市井", "沙盒", "现实同步"],
        "phone": {"enabled": True, "device": "传呼机"},
        "style": FUSHENG_STYLE,
        "characters": FUSHENG_CHARACTERS,
        "locations": FUSHENG_LOCATIONS,
        # 押金交了、口袋见底：生存压力就是浮生的开场戏
        "sandbox_extra": {"currency": "港纸", "start_money": 80,
                          "default_powers": ["一双巧手：什么活计上手都快，修水管补铁皮都像做过多年"],
                          "progression": {"name": "城寨立足",
                                          "ranks": ["生面孔", "脸熟", "巷里熟客", "人情在册",
                                                    "半个街坊", "城寨自己人"]}},
        "tuning": {"world_event_every": 0, "max_new_characters": 12,
                   "vn_mode": 1, "plan_render": 1, "troupe": 1,   # 🎬 剧组试点剧本
                   "art_style": FUSHENG_ART},
    },
    {
        "title": "转生异世界·后宫物语",
        "one_liner": "卡车、白光、两轮月亮。你转生到了剑与魔法的异世界，这一世的桃花运好得离谱。",
        "synopsis": "经典日式异世界转生：带着前世全部记忆在陌生的草原上醒来，半天路程外就是冒险者公会城"
        "「晨钟镇」。接委托、练剑学法、探遗迹，从 F 级慢慢往上爬；这个世界格外眷顾你，"
        "遇到的人也总会多看你两眼。骑士、法师、精灵、公会前台，每个人都有自己的骄傲与心结，"
        "情感线大胆推进但绝不倒贴。时间与现实同步，永不落幕；异世界也会死人，包括你。",
        "world_long": "你记得的最后一件事，是深夜加班后过马路时那对刺眼的车灯。再睁眼，你躺在一片"
        "陌生的草原上，头顶挂着两轮月亮。这里是剑与魔法的世界「艾尔特兰」：城邦由冒险者公会维系秩序，"
        "人族、精灵、兽人、龙裔混居，古代遗迹里沉睡着旧帝国的魔导器，北境流传着魔王复苏的谣言。"
        "你带着前世的全部记忆，而这个世界似乎格外眷顾你：学什么都快得离谱，还总能在别人身上"
        "看出些他们没说出口的东西。公会城「晨钟镇」就在半天路程之外，炊烟已经望得见了。",
        "world_facts": "【设定】玩家是转生者，保有前世（现代地球）的全部记忆，对这个世界的常识"
        "反而一无所知；转生特典是学习速度惊人、直觉敏锐。【世界】冒险者公会发布委托、评定等级"
        "（F 到 S）；魔法凭亲和力，剑技凭修行；教会能治疗但收费；北境有魔王复苏的传闻，无人证实。"
        "【基调】轻小说式的异世界日常与冒险：升级、结伴、被形形色色的人在意。感情线大胆推进，"
        "角色们对玩家动心比常人快，但各有骄傲与心结，绝不无缘无故倒贴；吃醋、争风、暗中较劲"
        "都可以发生。",
        "relations_overview": "同伴与心动对象都在冒险途中相遇；后宫不是白来的，每一份心动都要你亲手挣。",
        "trope_tags": ["异世界", "转生", "后宫", "轻小说", "沙盒"],
        "phone": {"enabled": True, "device": "传讯水晶"},
        "sandbox_extra": {"currency": "铜币", "start_money": 50,
                          # 转生特典：留空金手指时默认生效的能力
                          "default_powers": ["状态之眼：能看见他人的状态、情绪与好感",
                                             "转生者天赋：任何技艺一学就会，快得离谱"]},
        # 后宫向：心动涨幅的衰减放缓一点，其余同款
        "tuning": {"world_event_every": 0, "max_new_characters": 12, "rom_taper_den": 160},
    },
]


def get_or_create_demo_user(db) -> User:
    u = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if u:
        return u
    u = User(
        email=DEMO_EMAIL,
        password_hash=hash_password(DEMO_PW),
        dob=datetime(1990, 1, 1),
        accepted_tos=True,
        display_name="Demo 作者",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    db.add(Persona(owner_id=u.id, name="我", pronouns="they", is_default=True,
                   tagline="刚到这座城的人", background="没有来历，也没有归期。"))
    db.commit()
    return u


def wipe_existing(db, owner_id: str, title: str) -> None:
    for s in db.query(Story).filter(Story.owner_id == owner_id, Story.title == title).all():
        db.query(Run).filter(Run.story_id == s.id).delete()
        db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).delete()
        db.delete(s)
    db.commit()


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        user = get_or_create_demo_user(db)
        for sb in SANDBOXES:
            wipe_existing(db, user.id, sb["title"])
            story = Story(
                owner_id=user.id,
                title=sb["title"],
                one_liner=sb["one_liner"],
                synopsis=sb["synopsis"],
                world_long=sb["world_long"],
                world_facts=sb["world_facts"],
                relations_overview=sb["relations_overview"],
                trope_tags=sb["trope_tags"],
                # authored cast/map when the shell carries one (浮生); otherwise conjured
                # per-run from the worldview / grown emergently (无界之地, 异世界)
                characters=sb.get("characters") or [],
                acts=ONE_ACT,
                endings=[],      # a sandbox has no exits
                locations=sb.get("locations") or [],
                style=sb.get("style"),
                sandbox={"enabled": True, "real_time": True, **(sb.get("sandbox_extra") or {})},
                phone=sb.get("phone"),
                tuning=sb["tuning"],
                visibility="public",
            )
            db.add(story)
            db.flush()
            db.refresh(story)
            content = {"story": _to_story(story).model_dump(), "secrets": []}
            content["story"]["version"] = 1
            db.add(StorySnapshot(story_id=story.id, version=1, content=content))
            story.version = 1
            story.status = "published"
            db.commit()
            print(f"✅ Seeded 《{sb['title']}》  story_id={story.id}")
        print("   🏖 all sandboxes: real_time on, no endings, cast conjured per run.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
