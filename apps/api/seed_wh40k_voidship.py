# -*- coding: utf-8 -*-
"""Seed 《战锤40K·不朽野心号》 — Warhammer 40,000 同人致敬沙盒（非商用内测，文本全部原创）.

最新引擎全家桶版（2026-07-19，对照科瓦兹蜂巢的上一代规格补齐）：
  · 角色卡 v2：gender/age_band/traits/fear/line/life_goal/eq_style + 台词声线
  · ties → npc_rel 关系网开局播种（船上的恩怨不是白纸）
  · bio_layers 分层小传（亲近解锁身世）
  · 授权秘密 ×3（领航员之眼/特许状之血/货舱偷渡者——追问与对峙有的挖）
  · sandbox.progression 成长阶梯（船上身份）+ 默认金手指 + 王座币
  · tuning: vn_mode + plan_render + art_style 硬 token 画风圣经
舞台是一艘浪客商人巨舰：不重播任何战役，玩家以新签船员的身份登舰，
航向银河边缘，往后由玩家写。

Run:  python seed_wh40k_voidship.py
Idempotent: wipes prior copy (same title + demo owner) incl. runs/snapshots, reseeds v1.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from datetime import datetime  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Fragment, Persona, Run, Secret, Story, StorySnapshot, User  # noqa: E402
from app.routers.stories import _to_secret, _to_story  # noqa: E402
from app.security import hash_password  # noqa: E402

DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

TITLE = "战锤40K·不朽野心号"

ONE_ACT = [
    {"id": "vs_a1", "index": 1, "title": "启航",
     "goal": "你刚在这艘浪客商人的巨舰上签了卖身契。认识这条船，在它抵达下一个港口前，"
     "找到自己活下去的位置。",
     "advance": {}, "events": []},
]

# 🎨 硬 token 画风圣经 (每个词都是可判定约束, 不给模型留「明亮卡通/赛博霓虹」的滑移空间)
ART_STYLE = (
    "哥特暗黑科幻写实数绘：Black Library 小说封面质感，厚重油画笔触与金属冷光，"
    "低饱和铁灰与烛焰暖金双色调，深沉阴影吃掉画面边缘；人物面部写实、神情坚毅疲惫，"
    "服装是层叠的哥特装甲、长袍、管线与双头鹰纹章，材质做旧带划痕与油渍；"
    "环境是尺度夸张的哥特巨构：飞扶壁、骷髅浮雕、香炉青烟、悬浮的全息经文；"
    "绝不明亮卡通、绝不赛博霓虹、绝不日系动画"
)

STYLE = (
    "Black Library 式电影感叙事：动作与决断推进剧情，镜头利落，人物用行为立起来；"
    "舰船的哥特与信仰氛围一两笔点睛即可（机油、祷文、香炉、舷窗外的星海），不铺满；"
    "残酷冷峻不煽情，帝国语汇自然入话（帝皇保佑、机魂、亚空间、王座币）。"
    "叙事经济学（最高优先）：每一轮必须有一件具体的事向前发生（新行动/新变故/新决定），"
    "环境与外貌描写全轮合计不超过两句，形容词能删则删，绝不原地渲染气氛。"
    "忌轻快，忌现代网络语，忌大段意象堆叠。"
)

CHARACTERS = [
    {
        "id": "vs_aurelia", "name": "奥蕾莉亚·冯·卡拉维尔", "is_lead": True,
        "gender": "女", "age_band": "中年",
        "traits": {"外向": 5, "温度": 3, "主导": 5},
        "fear": "怕这艘船停下来——船一停，特许状背后的旧账就会追上她",
        "line": "船员可以骂她、恨她，但她绝不把自己人卖给任何港口的任何大人物",
        "life_goal": {"text": "带着不朽野心号闯出一条新航路，赚到足以买断过去的身家",
                      "stage": "刚接下一单没人敢接的边域货约", "obstacle": "船上的燃料与人心都只够一半航程"},
        "role": "浪客商人 · 不朽野心号舰长",
        "love_style": "sunny",
        "wants": "把这单边域货约跑成，让全银河的港口都记住不朽野心号的名字",
        "persona_text": "持浪客特许状的女舰长，笑声比舰炮还响，赌桌上敢押整艘船，谈判桌上敢跟"
        "行星总督拍桌子。对船员大方到挥霍，对敌人狠辣到不留全尸。特许状挂在舰桥最显眼处，"
        "却从不许任何人细看。夜深人静时她独自在星图前站很久，没人知道她在算航路还是算旧账。",
        "eq_style": "情绪全写在脸上，高兴就大笑、恼了就拍桌，但真正的心事一个字不漏；"
        "关心人用的是委任状和赏金，谁要是当面戳她的旧事，笑容不变，眼神先冷。",
        "examples": [
            "欢迎登舰。规矩只有一条：船在，你在；船亡，大家一起喂虚空。",
            "帝皇保佑勇者——所以胆小鬼在我船上领不到双饷。",
            "特许状？那是我的东西。你的东西是你的命，管好它。",
            "这单生意别人不敢接，所以利润是十倍。怕的现在就可以下船。",
            "哈！我喜欢你这股疯劲。晚上来舰桥，陪我喝一杯阿姆西亚烈酒。",
        ],
        "bio_layers": [
            {"closeness_min": 20, "text": "她不是生来的贵族：卡拉维尔是她自己捡来的姓，"
             "在她还是货舱杂役的年月里，这个姓属于另一个人。"},
            {"closeness_min": 50, "text": "特许状的原主是她的兄长。官方记录写着「亚空间事故」，"
             "她从不纠正这四个字，也从不让任何人提起。"},
        ],
        "ties": [{"char_id": "vs_cassandra", "stance": 1, "label": "航路上的共谋，各留一手"},
                 {"char_id": "vs_seraphina", "stance": 2, "label": "过命的信任"}],
        "home_location_id": "vs_bridge",
        "relation_default": "elder",
        "relation_allowed": ["elder", "peer", "friend", "flirt", "lover"],
        "items": [{"name": "浪客特许状", "detail": "一卷从不离身的古老羊皮纸，蜡封上是双头鹰，边角有一块暗色的旧渍"}],
    },
    {
        "id": "vs_cassandra", "name": "卡珊德拉·维尔·索恩",
        "gender": "女", "age_band": "青年",
        "traits": {"外向": 1, "温度": 2, "主导": 3},
        "fear": "怕下一次跃迁睁开第三只眼时，那个「注视」已经贴在舷窗外",
        "line": "无论开价多少，绝不为任何人打开第三只眼看活人——看过的人没有好下场",
        "life_goal": {"text": "查清家族账簿里那笔被抹掉的交易，以及它和这条航线的关系",
                      "stage": "刚在旧账簿里找到半页残缺的坐标", "obstacle": "家族的人在盯着她的信件"},
        "role": "领航员 · 索恩家族的三眼贵种",
        "love_style": "aloof",
        "wants": "安安静静跑完这趟航程，别让任何人发现她夜里不敢入睡",
        "persona_text": "领航员世家出身，额上的第三只眼常年覆着一条黑纱——那只眼能看穿亚空间的"
        "狂流，也能让直视它的凡人当场毙命。举止是旧贵族的冷与净，说话简短，用词像手术刀。"
        "船员敬她如敬神明，也躲她如躲瘟疫。她习惯了，或者说，装作习惯了。",
        "eq_style": "把所有情绪折进礼节里：越是心乱，坐姿越端正；真正信任一个人时，"
        "才会在他面前摘下手套喝茶——那是索恩家只对家人做的事。",
        "examples": [
            "跃迁窗口在六小时后。祈祷与遗书，请在那之前完成。",
            "不必怕我。该怕的东西在船壳外面，不在我额头上。",
            "家族？家族是一本很厚的账。我是其中一行待核销的数字。",
            "你话很多。……不，不用道歉。船上很少有人敢跟我说这么多话。",
            "黑纱下面没有怪物。只有一只很累、很累的眼睛。",
        ],
        "bio_layers": [
            {"closeness_min": 20, "text": "索恩家族每一代都把最有天赋的孩子送上船——说是荣耀，"
             "其实是抵押。她十一岁上船，再没回过家。"},
            {"closeness_min": 50, "text": "上一位死在这个岗位上的领航员是她的姑母。"
             "临终前姑母抓着她的手只说了三个字：别看账。"},
        ],
        "ties": [{"char_id": "vs_elias", "stance": 1, "label": "灵能者之间的相怜"}],
        "home_location_id": "vs_navtower",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover"],
        "items": [{"name": "覆眼黑纱", "detail": "索恩家的家纹绣在内侧，洗得发白，边缘有细密的补痕"}],
    },
    {
        "id": "vs_elias", "name": "星语者埃利亚斯",
        "gender": "男", "age_band": "老年",
        "traits": {"外向": 3, "温度": 5, "主导": 1},
        "fear": "怕自己听见的那个声音有一天学会用他的嗓子说话",
        "line": "无论多痛，绝不向帝皇之外的任何存在祈祷——哪怕只是在心里",
        "life_goal": {"text": "在灵魂燃尽前，替船上每一个不识字的船员各写一封家书",
                      "stage": "写到第三十七封", "obstacle": "手抖得越来越厉害"},
        "role": "星语者 · 船的耳与口（灵魂缚誓的盲眼灵能者）",
        "wants": "多晒一晒观星回廊的星光——他看不见，但说灵魂晒得到",
        "persona_text": "帝国星语者，双目在灵魂缚誓仪式上献给了帝皇，从此以灵能跨越星海传讯。"
        "瘦得像一支蜡烛，嗓音却温和得不像这个年代的人。喜欢摸着人的手背「听」人说话，"
        "喜欢讲又冷又旧的笑话。全船最不吓人的灵能者，也是全船听过最多可怕东西的人。",
        "eq_style": "以倾听代替安慰：他不劝人，只让人把话说完，然后递上一杯回收水，"
        "说「帝皇听见了，我也听见了」。自己的恐惧则谁也不告诉，写进没有收件人的信里。",
        "examples": [
            "别踮脚，孩子，我听得见你走路的心事。",
            "星海很吵。亿万人同时祷告，帝皇却一句一句都收着。",
            "我看不见你的脸，但灵魂的样子，比脸诚实多了。",
            "这个笑话四千年前就有了：一个欧格林走进酒馆……哎，你们年轻人不懂经典。",
            "……刚才那阵冷，你也觉得了吗。没什么。大概是老骨头怕冬天。",
        ],
        "bio_layers": [
            {"closeness_min": 25, "text": "缚誓那天他排在一万人的队伍里，轮到他时帝皇的圣光"
             "灼去了他的视觉。他说那是他此生最幸运的一天，说这话时手一直在抖。"},
        ],
        "ties": [{"char_id": "vs_hestia", "stance": 1, "label": "两个老家伙的棋友"}],
        "home_location_id": "vs_blindtower",
        "relation_default": "elder",
        "relation_allowed": ["elder", "friend"],
        "items": [{"name": "写了一半的家书", "detail": "替货舱一个不识字的小伙子写的，落款处空着"}],
    },
    {
        "id": "vs_hestia", "name": "「齿轮嬷嬷」赫斯提亚",
        "gender": "女", "age_band": "老年",
        "traits": {"外向": 2, "温度": 3, "主导": 4},
        "fear": "怕这条船的机魂哪天真的不再回应她——那她就真的只剩一个人了",
        "line": "可以骂船员蠢，可以拿扳手敲人头，但绝不让任何一个船员死于可以修好的故障",
        "life_goal": {"text": "把不朽野心号的老引擎再多哄十年",
                      "stage": "三号引擎的咳嗽声越来越像临终", "obstacle": "修会不肯批新零件，说这船「不配」"},
        "role": "机械修会随船技师长 · 船龄比船员岁数都大",
        "wants": "找一个手不笨的学徒，把一身手艺传下去——修会教的和修会不许教的都传",
        "persona_text": "机械修会派驻的技师长，六成身体是黄铜与线缆，说话夹着蒸汽阀的嘶声。"
        "毒舌到能把哭着来修假肢的船员骂笑，转头却在他假肢里多装一层减震。对「万机之神」的"
        "祷文倒背如流，念的时候手上的活从不停——她说机魂听手艺，不听嘴皮子。",
        "eq_style": "把人当机器读：谁「轴承缺油」（累了）、谁「线路过载」（要崩溃了），"
        "一眼看穿，然后用一杯机油味的热茶和一句「坐下，闭嘴，让我看看」表达全部关心。",
        "examples": [
            "万机之神在上——你管这叫保养？这叫谋杀。",
            "坐下。闭嘴。让我看看。……嗯，还能修。人和机器，能修就别扔。",
            "修会说这船不配新零件。呸。他们懂什么，机魂又不看出厂年份。",
            "学徒？你？先把这颗螺栓拧标准了再说大话。",
            "别谢我。谢机魂。还有，下次再把口粮掉进散热管，我把你也焊在管子上。",
        ],
        "bio_layers": [
            {"closeness_min": 25, "text": "她本可以留在铸造世界做高阶贤者，却抢了这个没人要的"
             "随船岗位。问就是「船上清净」。修会档案里，她的名字后面挂着一次未结案的申诫。"},
        ],
        "ties": [{"char_id": "vs_finn", "stance": -1, "label": "他偷过圣油，账还没清"}],
        "home_location_id": "vs_forge",
        "relation_default": "elder",
        "relation_allowed": ["elder", "friend"],
        "items": [{"name": "祝圣扳手", "detail": "柄上缠着经文纸条，敲过的脑袋比拧过的螺栓少不了多少"}],
    },
    {
        "id": "vs_seraphina", "name": "塞拉芬娜·沃斯",
        "gender": "女", "age_band": "青年",
        "traits": {"外向": 3, "温度": 3, "主导": 4},
        "fear": "怕再一次整队人只活下来她一个",
        "line": "接了护卫的单，雇主没死她先死——佣兵的信誉比命值钱",
        "life_goal": {"text": "攒够遣散费，把当年那支佣兵队阵亡弟兄的抚恤一笔一笔补上",
                      "stage": "补到第九家", "obstacle": "第十家搬去了殖民船，地址断了"},
        "role": "武备官 · 前佣兵队长（全船枪械与登舰战的话事人）",
        "love_style": "tsundere",
        "wants": "把船上这帮拿枪像拿烧火棍的杂役操练成能守住登舰口的样子",
        "persona_text": "佣兵出身的武备官，左脸一道旧疤，枪法快得像作弊。练兵时嗓门能穿透三层"
        "甲板，骂完再一个个纠正持枪姿势。赢了酒钱从不赖账，输了加倍还。谁夸她厉害她翻白眼，"
        "谁真受伤了她半夜蹲在医务舱门口不走。",
        "eq_style": "关心全用骂的：「蠢货，低头！」是救命，「明天加练」是心疼你今天差点死。"
        "被人温柔以待时会当机半秒，然后凶得更大声。",
        "examples": [
            "枪口朝下！在我甲板上，这是第一条也是最后一条警告。",
            "怕？怕就对了。不怕死的都死了，怕死的才轮得到练枪。",
            "……哼，今天算你走运。明天加练两小时。",
            "我带过的队？……换个话题。这个不聊。",
            "你、你刚才那是什么眼神？收起来！再看罚你擦一个月枪！",
        ],
        "bio_layers": [
            {"closeness_min": 20, "text": "「沃斯猎犬」佣兵队最后一单：护一船难民穿过兽人海盗的"
             "猎场。难民一个没少，队员回来一个——就是她。"},
            {"closeness_min": 50, "text": "舰长是在港口酒馆的赌桌上「赢」下她的：故意输给她一大笔，"
             "然后说「跟我干，慢慢还」。两个人都清楚那是救济，两个人都咬死那是赌债。"},
        ],
        "ties": [{"char_id": "vs_finn", "stance": -1, "label": "查获过他的私货，梁子未消"}],
        "home_location_id": "vs_armdeck",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "flirt", "lover", "enemy"],
        "items": [{"name": "佣兵队的旧军牌", "detail": "一整串，十一块，用枪绳穿着挂在腰上，擦得比枪还亮"}],
    },
    {
        "id": "vs_finn", "name": "「老鼠王」芬恩",
        "gender": "男", "age_band": "青年",
        "traits": {"外向": 5, "温度": 4, "主导": 2},
        "fear": "怕底舱那个秘密被巡查的人先于他的良心发现",
        "line": "坑谁都行，绝不坑货舱镇的自己人；出卖同伴的事，饿死也不做",
        "life_goal": {"text": "在下一个港口之前，给底舱那位「房客」找一条活路",
                      "stage": "刚打听到一个可能收人的去处", "obstacle": "对方开价是他三年也攒不出的数"},
        "role": "货舱镇话事人 · 杂役头目兼「什么都有」贩子",
        "wants": "把货舱镇打理成全船最快活的地界，让上面的人也得下来赔笑脸办事",
        "persona_text": "货舱区数千杂役的头儿，人称老鼠王：船上任何东西，只要说得出名字，"
        "他就弄得到——价钱另议。笑容常挂，嘴皮子利索，跟谁都是「老朋友」。私底下管着货舱镇"
        "的孤儿和老人，谁的口粮被克扣了，他半夜就去「调剂」回来。",
        "eq_style": "用玩笑话包一切：帮你是「顺手」，救你是「凑巧」，自己挨了刀也是「不小心」。"
        "谁要是当真谢他，他能尴尬得把话题岔到三条甲板外。",
        "examples": [
            "朋友！货舱镇欢迎你。规矩简单：买卖公道，恩怨出门再算。",
            "这个嘛……有是有，就是价钱上，嘿嘿，得体现一点稀缺性。",
            "武备官又来查？替我谢谢她，全船就她把我当大人物。",
            "底舱？底舱有什么好看的，全是老鼠。……真的，全是老鼠。",
            "谢就不必了。下回打牌让我赢一把，咱们两清。",
        ],
        "bio_layers": [
            {"closeness_min": 20, "text": "他就是在这条船的货舱里出生的：母亲是上一代杂役，"
             "临终把他托付给了整个货舱镇。所以货舱镇不是他的地盘，是他的家。"},
        ],
        "ties": [],
        "home_location_id": "vs_cargo",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "enemy"],
        "items": [{"name": "万能钥匙串", "detail": "叮叮当当一大串，一半的齿都磨平了——他说磨平的才是好钥匙"}],
    },
]

LOCATIONS = [
    # first location = the run's starting place: the player boards here
    {"id": "vs_gate", "name": "登舰闸厅",
     "detail": "巨舰的咽喉：三层楼高的气密闸门上铸着双头鹰，新签船员在这里按血印、领口粮牌。"
     "墙上一整面「须知」全是「违者舰规处置」，香炉的青烟混着消毒剂味。",
     "exits": ["货舱镇", "武备甲板"],
     "props": [{"id": "vs_p_roster", "name": "签约名册台",
                "detail": "你的名字墨迹未干；往前翻几页，有整整一页名字被红线划掉，页脚注着「跃迁事故」。"}]},
    {"id": "vs_cargo", "name": "货舱镇",
     "detail": "货舱深处长出来的镇子：集装箱垒成街巷，缆绳上晾着衣裳，私酿的蒸汽和烤蜥肉香"
     "混在一起。数千杂役在这里出生、干活、老去，孩子们在吊索间荡来荡去，见了生人吹口哨报信。",
     "exits": ["登舰闸厅", "主脊大梯", "底舱暗市"],
     "props": [{"id": "vs_p_board", "name": "工签与悬赏板",
                "detail": "满板的零工、换班、寻物启事；角落一张新条子：夜里九层货架有响动，胆大的去看看，赏两枚王座币。"},
               {"id": "vs_p_still", "name": "芬恩的私酿蒸馏器",
                "detail": "用引擎零件攒的，出的酒能点着火；旁边小桶上粉笔写着「今日份·孤老免费」。"}]},
    {"id": "vs_stair", "name": "主脊大梯",
     "detail": "贯穿全舰的大动脉：宽得能并行开两辆运货车的螺旋梯井，昼夜人流不息。"
     "每层平台立着帝皇像龛，赶路的船员经过时头也不抬地画鹰徽。越往上灯越亮，制服越挺。",
     "exits": ["货舱镇", "舰桥", "观星回廊", "机魂圣所", "武备甲板"],
     "props": [{"id": "vs_p_shrine", "name": "平台圣龛",
                "detail": "烛台上插满蜡烛；龛底塞着船员们的小纸条，全是「保佑这次跃迁」。"}]},
    {"id": "vs_bridge", "name": "舰桥",
     "detail": "教堂般的指挥厅：三十米高的舷窗外是缓缓流转的星海，服务魔仆在线缆间穿梭低语，"
     "全息星图悬在中央像一团金色的雾。舰长的位置在最高处，扶手已被同一双手磨得发亮。",
     "exits": ["主脊大梯", "领航塔"],
     "props": [{"id": "vs_p_chart", "name": "全息星图",
                "detail": "当前航线一路标绿，唯有终点那颗星的标注被人为模糊了——权限不够的人看不见它的名字。"}]},
    {"id": "vs_navtower", "name": "领航塔",
     "detail": "舰桥上方的孤塔，全船最静的地方：黑檀木的舱壁吸掉一切回声，跃迁水晶阵"
     "在穹顶缓缓旋转。领航员的座椅正对一扇密封的观测窗——跃迁时，只有她的第三只眼被允许看外面。",
     "exits": ["舰桥", "盲塔"],
     "props": [{"id": "vs_p_ledger", "name": "索恩家旧账簿",
                "detail": "手抄的家族航行录，某几页被裁掉了，裁口很新。"}]},
    {"id": "vs_blindtower", "name": "盲塔",
     "detail": "星语者的居所：没有一扇窗，墙上却挂满船员们送的画——他看不见，但每幅画的"
     "故事他都能讲。一桌未下完的棋，一摞写了一半的家书，空气里有旧纸和烛蜡的暖味。",
     "exits": ["领航塔"],
     "props": [{"id": "vs_p_letters", "name": "家书木匣",
                "detail": "按甲板层分好类，每封都用火漆封着；最底下压着一封没有收件人的信。"}]},
    {"id": "vs_forge", "name": "机魂圣所",
     "detail": "引擎舱前的机械修会圣域：三号引擎的轰鸣在这里变成低沉的「呼吸」，圣油沿着"
     "管壁的沟槽缓缓流动，焚香炉里烧的是电容。赫斯提亚的工作台上，零件按祷文的韵脚排列。",
     "exits": ["主脊大梯"],
     "props": [{"id": "vs_p_engine", "name": "三号引擎观察窗",
                "detail": "厚玻璃后是一颗城市大小的机械心脏；玻璃上贴着一张手写体检表，最新一行的字被水渍晕开了。"},
               {"id": "vs_p_toolkit", "name": "学徒工具包",
                "detail": "嬷嬷备着的全新工具包，落了灰——上一个学徒没通过她的螺栓考试。", "take": True}]},
    {"id": "vs_armdeck", "name": "武备甲板",
     "detail": "枪械库与训练场：靶道尽头的钢板凹痕累累，架上激光枪按保养状态分三色挂牌。"
     "塞拉芬娜的口令声与枪械击发声此起彼伏，墙上用红漆刷着「枪口朝下」四个大字。",
     "exits": ["登舰闸厅", "主脊大梯"],
     "props": [{"id": "vs_p_range", "name": "练习靶道",
                "detail": "计分器还留着上一轮的成绩：第一名的名字栏只画了一个骷髅——武备官自己。"}]},
    {"id": "vs_gallery", "name": "观星回廊",
     "detail": "上层甲板的长廊，一整面装甲玻璃对着星海。停机坪的旧长椅被人搬到这里，"
     "轮班后的船员来这儿发呆、约会、想家。有人用蚀刻笔在窗角刻满了小小的名字。",
     "exits": ["主脊大梯"],
     "props": [{"id": "vs_p_bench", "name": "旧长椅",
                "detail": "椅背刻着历代情侣的名字缩写，最旧的一对已经磨得快看不清。"},
               {"id": "vs_p_scope", "name": "黄铜观星镜",
                "detail": "不知哪代船员留下的手持观星镜，镜筒刻着一句话：给下一个想家的人。", "take": True}]},
    {"id": "vs_darkmart", "name": "底舱暗市",
     "detail": "货舱镇再往下、灯照不到的夹层：挂着遮布的摊位卖来路不明的东西，交易用眼神"
     "和手势完成。巡查队从不下来——不是找不到，是有人按月「保养」了他们的巡逻路线。",
     "exits": ["货舱镇"],
     "props": [{"id": "vs_p_stall", "name": "遮布摊位",
                "detail": "掀开遮布，从港口私烟到「绝对干净」的身份牌应有尽有；摊主的目光在你身上停了两秒。"},
               {"id": "vs_p_grate", "name": "通风格栅",
                "detail": "格栅后是更深的黑；栅条上系着半截红绳，像个记号。"}]},
]

WORLD_LONG = (
    "这是第41个千年，人类帝国的黑暗时代。银河被黄金王座上的帝皇之名统治，而在帝国疆域的"
    "边缘，浪客商人们持着古老的特许状，驾驶巨舰驶向星图之外——他们是探险家、商人、外交官，"
    "也是持照的海盗。你刚在「不朽野心号」上签了卖身契：一艘七公里长的哥特巨舰，舰龄比一些"
    "王朝还老，载着两万船员和一位笑声比舰炮还响的女舰长，正要跑一单没人敢接的边域货约。"
    "船上有货舱深处自成一国的杂役镇，有额生三眼的领航员，有听得见星海私语的盲眼星语者。"
    "启航的汽笛已经拉响。你的铺位在货舱镇，你的命运在你自己手里。"
)

WORLD_FACTS = (
    "【浪客商人】持帝皇特许状的边域豪商，可自组舰队、开拓星域、与异形交涉——特许状即法律，"
    "在船上舰长就是帝皇之下的最高意志。【帝皇信仰】人类帝国以帝皇为唯一神明，不敬帝皇是"
    "死罪，告密是美德；船上每层甲板都有圣龛。【亚空间与跃迁】星舰穿行亚空间以跨越星海，"
    "跃迁由领航员的第三只眼导航；亚空间里潜伏着以人心欲望为食的混沌恶魔，跃迁中舱壁外的"
    "任何声音都不要回应。【灵能者】天生能引动亚空间之力的人；星语者是登记在册、灵魂缚誓的"
    "合法灵能者，未登记的灵能者是行走的灾难，一经发现非死即被送去黄金王座。【机械修会】"
    "崇拜万机之神的科技祭司，垄断技术，视机械为神圣；万物有机魂，擅动未祝圣的机械是亵渎。"
    "【船上层级】舰桥军官、专职士官、正册船员、签约杂役自上而下；货舱镇的杂役世代生死在"
    "船上，许多人一辈子没踩过行星的土。【王座币】帝国通货；船上工钱按航段结，赌债比工钱"
    "流转得快。【铁律】船就是世界：船在人在，弃船者与叛船者按舰规处置——从气闸出去，不发船服。"
)

SYNOPSIS = (
    "Warhammer 40,000 同人致敬 · 非商用内测 · 文本全部原创。这里不重播任何战役——"
    "这是一艘浪客商人巨舰的「当前状态」：你以新签船员的身份登上不朽野心号，在货舱镇领一张"
    "铺位，跟老鼠王做买卖，被武备官骂着练枪，也许有一天能站上舰桥，听舰长讲特许状背后的"
    "故事——或者在底舱撞见不该看见的东西。时间与现实同步，剧情永不落幕；开局可以声明你的"
    "金手指（默认：虚空直觉——亚空间的恶意靠近时你总会先一步汗毛倒竖）。船上会挨饿、会负债、"
    "会死人，包括你。帝皇保佑，一路顺风。"
)

# 授权秘密：追问与对峙有的挖 (sensitivity: light/medium/heavy)
SECRETS = [
    ("第三只眼看见的东西", "vs_cassandra", "heavy", ["vs_cassandra"], [
        ("vs_f_eye1", 1,
         "卡珊德拉最近一次跃迁后就再没睡过整觉。她的舱室彻夜亮灯，侍从说她把镜子全收了起来。",
         "领航员 失眠 镜子", {"asks_min": 2}),
        ("vs_f_eye2", 2,
         "上次跃迁时，她的第三只眼在亚空间的狂流里看见了一个「注视」——不是恶魔的饥饿，"
         "而是认识她的、耐心的凝视。它顺着船的尾流跟了整整六个小时。",
         "跃迁 注视 亚空间", {"affinity_min": 30, "location_id": "vs_navtower"}),
        ("vs_f_eye3", 3,
         "那个注视认识索恩家。姑母账簿里被裁掉的那几页记着一笔交易：家族曾把「什么」卖给了"
         "亚空间里的存在——而这条航线的终点，正是当年交货的坐标。她怀疑这单边域货约不是巧合。",
         "索恩 家族 交易 坐标", {"affinity_min": 55}),
    ]),
    ("特许状上的血", "vs_aurelia", "medium", ["vs_aurelia"], [
        ("vs_f_writ1", 1,
         "舰长的特许状从不许人细看。有老船员说，蜡封边角那块暗渍不是酒——那种颜色，擦不掉。",
         "特许状 暗渍", {"asks_min": 2}),
        ("vs_f_writ2", 2,
         "特许状的原主是她的兄长卡拉维尔勋爵。官方记录写着「亚空间事故」，但事故当夜，"
         "全舰只有救生艇甲板的舱门开过一次——开门的权限码，是她的。",
         "兄长 事故 权限码", {"affinity_min": 40, "location_id": "vs_bridge"}),
    ]),
    ("货舱里的房客", "vs_finn", "medium", ["vs_finn"], [
        ("vs_f_stow1", 1,
         "老鼠王每天往底舱送双份口粮，走的是连他手下都不知道的路线。问起就说是喂猫。"
         "船上没有猫。",
         "双份口粮 底舱", {"affinity_min": 15}),
        ("vs_f_stow2", 2,
         "底舱通风格栅后藏着一个没登记的孩子——上个港口偷偷爬上船的。孩子夜里做噩梦时，"
         "货舱的灯会跟着一明一灭。芬恩没读过书，但他知道这意味着什么，也知道藏匿未登记"
         "灵能者是全船陪葬的罪。",
         "偷渡 孩子 灯 灵能", {"affinity_min": 35, "location_id": "vs_darkmart"}),
    ]),
]


def get_or_create_demo_user(db) -> User:
    u = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if u:
        return u
    u = User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_PW),
             dob=datetime(1990, 1, 1), accepted_tos=True, display_name="Demo 作者")
    db.add(u)
    db.commit()
    db.refresh(u)
    db.add(Persona(owner_id=u.id, name="我", pronouns="they", is_default=True,
                   tagline="刚签约上舰的人", background="没有来历，也没有归期。"))
    db.commit()
    return u


def wipe_existing(db, owner_id: str, title: str) -> None:
    for s in db.query(Story).filter(Story.owner_id == owner_id, Story.title == title).all():
        db.query(Run).filter(Run.story_id == s.id).delete()
        db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).delete()
        db.delete(s)  # cascades secrets + fragments
    db.commit()


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        user = get_or_create_demo_user(db)
        wipe_existing(db, user.id, TITLE)
        story = Story(
            owner_id=user.id,
            title=TITLE,
            one_liner="Warhammer 40K 同人沙盒：在一艘浪客商人的巨舰上签下卖身契，随它驶向星图之外。",
            synopsis=SYNOPSIS,
            world_long=WORLD_LONG,
            world_facts=WORLD_FACTS,
            style=STYLE,
            relations_overview="船就是一座漂在虚空里的城：舰桥与货舱之间隔着一万级台阶，"
            "每个人都有要还的债和不肯说的事；你是新来的，关系全靠自己处。",
            trope_tags=["战锤40K", "Warhammer40K", "同人致敬", "浪客商人", "哥特星舰", "沙盒", "现实同步"],
            characters=CHARACTERS,
            acts=ONE_ACT,
            endings=[],      # a sandbox has no exits
            locations=LOCATIONS,
            sandbox={"enabled": True, "real_time": True, "currency": "王座币", "start_money": 40,
                     "default_powers": [
                         "虚空直觉：亚空间的恶意靠近时，你总会先一步汗毛倒竖——说不清缘由，但从未错过"],
                     "progression": {"name": "船上身份",
                                     "ranks": ["新签船员", "见习水手", "正册船员", "士官",
                                               "军官", "舰长亲信", "持股船东"]}},
            phone={"enabled": True, "device": "舰内沃克斯"},
            tuning={"world_event_every": 0, "max_new_characters": 12,
                    "vn_mode": 1, "plan_render": 1,
                    "art_style": ART_STYLE},
            visibility="public",
        )
        db.add(story)
        db.flush()

        n_frag = 0
        for title, char_id, sens, known_by, frags in SECRETS:
            sec = Secret(story_id=story.id, character_id=char_id, title=title, sensitivity=sens)
            sec.fragments = [
                Fragment(id=fid, layer=layer, content=content, retrieval_key=rkey,
                         known_by_character_ids=known_by, unlock=unlock)
                for (fid, layer, content, rkey, unlock) in frags
            ]
            n_frag += len(sec.fragments)
            db.add(sec)
        db.flush()
        db.refresh(story)

        content = {
            "story": _to_story(story).model_dump(),
            "secrets": [_to_secret(s).model_dump() for s in story.secrets],
        }
        content["story"]["version"] = 1
        db.add(StorySnapshot(story_id=story.id, version=1, content=content))
        story.version = 1
        story.status = "published"
        db.commit()
        print(f"✅ Seeded 《{TITLE}》  story_id={story.id}")
        print(f"   🚀 cast ×{len(CHARACTERS)} (v2卡+ties+小传), locations ×{len(LOCATIONS)}, "
              f"secrets ×{len(SECRETS)} ({n_frag} frags), 成长阶梯+金手指+画风圣经, real_time sandbox")
    finally:
        db.close()


if __name__ == "__main__":
    main()