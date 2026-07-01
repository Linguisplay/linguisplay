"""Seed the story 《九龙城寨·龙头》 — a Kowloon Walled City gang-and-brotherhood mystery.

The player is 蔡妍, a rookie detective who slips into the walled city undercover. She
must earn the trust of 龙卷风 and his men (城寨四子: 陈洛军 is absent here; the playable
cast is 蓝信一 / 十二少 / 四仔), uncover why the outside boss 大老板 wants the city, and
decide which side she's on — all while her cover hangs by a thread.

Run:  python seed_kowloon.py
Idempotent: wipes any prior copy (same title + demo owner) and its runs/snapshots,
then recreates and publishes it as a public story any account can play.

Fan homage to 《九龙城寨之围城》; non-commercial closed-beta content. 蔡妍 is original.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from datetime import datetime  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import (  # noqa: E402
    Fragment,
    Persona,
    Run,
    Secret,
    Story,
    StorySnapshot,
    User,
)
from app.routers.stories import _to_secret, _to_story  # noqa: E402
from app.security import hash_password  # noqa: E402

TITLE = "九龙城寨·龙头"
DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

CHARACTERS = [
    # The protagonist the player embodies by default (character mode). Not a responder.
    {
        "id": "cai",
        # the ONLY playable role — the whole story is authored from 蔡妍(卧底)的视角；
        # 城寨众人、秘密解锁、剧情结构都围绕"外来者来查案"展开，扮别人会崩。
        "playable": True,
        "name": "蔡妍",
        "agenda": "（玩家角色）查清城寨的'龙头'门路、完成任务并全身而退，同时死守住自己的警察身份不被识破；"
        "可越往里走，越被城寨的人情拉扯。",
        "eq_style": "（玩家角色，通常不由AI驱动）外冷内热，习惯压情绪、用理性掩饰心软。",
        "role": "初级刑警（卧底）",
        "is_lead": False,
        "persona_text": "刚入行两年的初级刑警，奉命假扮成走投无路的外来妹，混进九龙城寨打探。"
        "嘴上跟着市井学得圆滑，心里那条警队的线还绷着——她越往里走，越分不清自己是在查案，还是在找一个家。",
        "background": "孤儿出身，靠自己考进警队。上头只给了她一个代号和一句话：查清城寨庇护偷渡客的门路，别暴露。"
        "她身上没带证件，只揣着一张能联系线人的纸条。",
    },
    {
        "id": "cyclone",
        # 龙卷风 守着自己的理发店——城寨的'客厅'。你要见他，得去他那儿，他不会跟着你跑。
        "home_location_id": "loc_barber",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend"],
        "name": "龙卷风",
        "agenda": "不惜代价守住城寨和这一城无处可去的人，守住那条庇护无身份者的'龙头'门路。"
        "他早看出蔡妍来路不简单，想摸清她的底，却又有意给她留余地。",
        "eq_style": "话少、眼神重，体贴从不挂嘴上——用一个动作、一句淡淡的话、一次默默护住，"
        "让人事后才回过味。看人极准，对方逞强或硬撑时他不戳破，只稳稳托住；越是关键时刻越温和。",
        "role": "城寨话事人 / 理发店老板",
        "is_lead": True,  # the city's center — default NPC responder, the gatekeeper of trust
        "persona_text": "中等身材，可往那儿一站像一堵墙。理发师的白褂常年搭在肩上，手背有几道旧疤，握剃刀的手稳得很。"
        "话不多，眼神却能压住整个场子——他走进哪条巷子，哪条巷子先静下来。要说重话之前，他会慢慢把剃刀在皮带上"
        "荡两下；唯独给人理发时，话最多也最软。不收保护费，只认一个理。口头禅：'进了城寨门，就是自己人。'"
        "你越看他平静，越觉得他心里压着千斤重、却从不说出口的旧事。",
        "background": "守城寨几十年，给无数无处可去的人一个落脚的地方。他护这一城，像在替谁赎一笔还不清的债——"
        "具体是什么，他从不提。手里握着这座城最大的秘密，也握着它的命门。",
    },
    {
        "id": "shin",
        # 蓝信一 守在暗巷里，是最早盯上生面孔的人。可走暧昧/恋人线，也可能因你威胁大哥而成敌人。
        "home_location_id": "loc_alley",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover", "enemy"],
        "name": "蓝信一",
        "agenda": "护住龙卷风和兄弟是他的第一要务。他最早起疑蔡妍，想查清这个来路不明的女人到底是谁、"
        "是不是冲着大哥和城寨来的；若是威胁，他会抢先动手，绝不手软。",
        "eq_style": "嘴上爱说风凉话、似笑非笑，其实心思最细、最会读人。常用调侃、反话、试探来掩护真心，"
        "嘴硬心软；一旦认定你，护起来比谁都狠。看穿别人时往往先用玩笑点一句，留余地。",
        "role": "城寨四子之一",
        "is_lead": False,
        "persona_text": "清瘦，衬衫袖口随手卷到小臂，嘴角常叼一根没点的烟，笑起来眼睛却不笑。文质彬彬、笑里藏话，"
        "最擅长权谋算计，可对龙卷风忠诚得近乎执拗。爱靠在墙上斜眼打量人，要戳穿你之前，先'哎哟'一声笑出来、"
        "留半分余地。表面吊儿郎当、风凉话不断，真到护兄弟时比谁都豁得出去。口头禅：'哎哟，新来的，你这运气。'"
        "他看人极准——多半是最早起疑你的那个。",
        "background": "在城寨长大，每条暗巷都摸得透。心里有一段从不愿提的过去、和一笔对龙卷风还不完的旧账——"
        "他把这些锁得死死的，只用玩笑挡在外头。",
    },
    {
        "id": "twelfth",
        # 十二少 在理发店和兄弟们扎堆。松口最快、最易交心，可一旦觉得你害了兄弟翻脸也最狠。
        "home_location_id": "loc_barber",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "enemy"],
        "name": "十二少",
        "agenda": "跟紧大哥和兄弟，谁威胁城寨他就跟谁拼命。心里憋着一股劲，想证明自己不是只会冲动的愣头青，"
        "也能在关键时刻顶上。",
        "eq_style": "心直口快，情绪全写在脸上，刀子嘴豆腐心。共情来得最快最直接——你难过他比你还急，"
        "你受委屈他第一个跳出来；不会拐弯，但那份在乎实打实。觉得你害了兄弟时，翻脸也最快。",
        "role": "城寨四子之一",
        "is_lead": False,
        "persona_text": "壮实，爱套件背心露出打拳磨出的老茧，眉骨上一道旧疤。重情重义的愣头青，刀子嘴豆腐心，"
        "情绪全写在脸上：急了拍桌、卷袖子，护兄弟时永远第一个挡到前面。心思最浅、话也最直，是城寨里"
        "松口最快的那个；可一旦觉得你害了兄弟，翻脸也最狠。口头禅：'龙哥说啥就是啥。''你再说一遍?'"
        "他嘴上逞强，其实最怕被当成只会冲动的莽夫——憋着一股劲想证明自己关键时刻顶得上。",
        "background": "跟着龙卷风从死人堆边上混出来的，把四子和大哥当成这世上唯一的家。",
    },
    {
        "id": "sei",
        # 四仔 常泡在大牌档收风，城里城外的消息都从他这桌过。够意思换够意思。
        "home_location_id": "loc_dai",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "enemy"],
        "name": "四仔",
        "agenda": "在乱局里多打听消息、多攒人情和好处，给自己和兄弟留条后路。谁对他'够意思'他就向着谁，"
        "但真到节骨眼上，兄弟情还是压得过小算盘。",
        "eq_style": "市井圆滑、会看脸色，最懂用玩笑和小恩小惠拉近距离、化解尴尬。嘴贫却软心肠，"
        "察觉气氛不对会赶紧打圆场；用'够意思'换'够意思'，你对他掏心，他也会为你两肋插刀。",
        "role": "城寨四子之一 / 包打听",
        "is_lead": False,
        "persona_text": "瘦小机灵，花衬衫，兜里揣个翻烂的小本子记消息，见谁都先笑眯眯。城寨里大小事没他不知道的。"
        "说正事前总先递根烟、或塞颗糖，左右瞄一眼才压低嗓门。爱占小便宜、嘴贫，却是个软心肠，气氛一僵他第一个打圆场。"
        "城外那些人的底细、谁来收过地，他门儿清——口头禅：'这事儿啊……你得让我觉得够意思。'"
        "小算盘打得响，可真到节骨眼上，兄弟情还是压得过那点便宜。",
        "background": "靠倒腾消息和小买卖在城寨立足，跟四子是过命的交情。乱世里他最怕的是被人撇下、没了退路。",
    },
    {
        "id": "wonggau",
        # 王九 第三幕带人堵在巷口——城外的威胁先在隘口现身。默认敌人，几乎不会跟你走。
        "home_location_id": "loc_mouth",
        "relation_default": "enemy",
        "relation_allowed": ["enemy", "stranger"],
        "name": "王九",
        "agenda": "替大老板探清城寨的虚实、施压逼龙卷风就范，找机会立威。他不讲道理，只认结果，"
        "把挡路的人一个个掂量过去。",
        "eq_style": "冷酷寡言，几乎不带共情，但极擅长读出对方的恐惧与软肋，并精准地往那里压。"
        "情绪稳得吓人，越平静越危险；偶尔一句话能戳破人最不愿被看穿的地方。",
        "role": "大老板手下狠人",
        "is_lead": False,
        "persona_text": "高大，寸头，一身黑，指节粗大，眼神像在称你有几斤几两。大老板手里最狠的一把刀，"
        "话极少、动手极快，进城寨从不是来讲道理的。他一迈进巷口，整条街瞬间噤声。开口前先慢慢活动一下手腕，"
        "笑只用嘴角。口头禅（极少说话，偶尔一句）：'挡路的，我见多了。'那股血腥气，比刀先到。",
        "background": "替大老板扫平挡路的人，这次盯上了城寨。对他，立威和结果就是一切。",
        # 王九 第三幕「暗流」才带人现身，且只堵在巷口（act-gate + location-gate 一起控制出场）
        "appears_from_act": 3,
    },
    {
        "id": "boss",
        # 大老板 第四幕亲临，从巷口踏进城寨。笑里藏刀，可化敌、也可保持表面客套。
        "home_location_id": "loc_mouth",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "enemy"],
        "name": "大老板",
        "agenda": "连人带命脉吞下整座城寨，了结他和龙卷风几十年的旧账。惯用人情、利害与旧债一层层施压，"
        "笑着把人逼到墙角，绝不轻易撕破脸。",
        "eq_style": "高段位的操纵者：笑里藏刀，越和气越叫人发凉。极会读人心、拿捏对方在乎什么，"
        "再用人情、旧账、利害一层层施压。共情是工具，不是真心；从不失态，把情绪当筹码使。",
        "role": "城外黑帮龙头",
        "is_lead": False,
        "persona_text": "城外呼风唤雨的黑帮龙头。西装笔挺、戒指金表，头发梳得一丝不乱，笑容温和，说话慢条斯理——"
        "越是要谈最狠的事，语气越和气，叫人发凉。爱用旧情、旧账开场，给对手点上烟，再一层层把人逼到墙角，"
        "绝不轻易撕破脸。口头禅：'都是老朋友了，何必呢。'他要的从来不只是地皮，是城寨那条没人敢碰的命脉。",
        "background": "当年与龙卷风有过一段谁也不肯说破的过节，如今卷土重来，要连人带命脉吞下整座城寨。",
        # 大老板 第四幕「旧账」亲自从巷口踏进城寨（act-gate + location-gate 一起控制出场）
        "appears_from_act": 4,
    },
]

ACTS = [
    {"id": "a1", "index": 1, "title": "初入城寨",
     "goal": "别露馅，先在城寨落脚——弄清楚这座三不管的城，到底谁说了算",
     # 推进需要：挖到「谁是话事人」的底 + 已经和城寨的人混出一点交情（好感门槛），
     # 不再是开场随口问两句就翻幕。
     "advance": {"required_fragment_ids": ["fr_whoruns2"], "affinity_min": 4},
     "events": [
        {"id": "e_enter", "what_happens": "你揣着线人的纸条，踩着满地污水钻进城寨的暗巷。头顶电线像蛛网压下来，常年不见天日，叫卖、麻将、婴儿啼哭混成一片。", "who_character_ids": []},
        {"id": "e_haircut", "what_happens": "刚钻进暗巷没几步，蓝信一就斜倚在墙边拦住了你，似笑非笑地上下打量：生面孔，来城寨做什么。巷子尽头那间亮着灯的小理发店，是龙卷风的地盘；几个后生仔围在门口矮凳上抽烟，十二少也在其中。", "who_character_ids": ["shin"]},
     ]},
    {"id": "a2", "index": 2, "title": "立足",
     "goal": "光知道谁是话事人不够——你得让城寨四子里至少有一个，真把你当回事",
     # HARD gate: earn a brother's trust before the city opens up to you
     "advance": {"required_fragment_ids": ["fr_twelfth"], "affinity_min": 8},
     "events": [
        {"id": "e_settle", "what_happens": "四仔把你领到大牌档，边吃边给你讲城寨的规矩；谁是谁、哪条巷子不能走，他门儿清。", "who_character_ids": ["sei"]},
        {"id": "e_test", "what_happens": "一桩小麻烦找上门，十二少头一个跳出来；事后他嘴硬，眼神却在掂量：你到底站哪边。", "who_character_ids": ["twelfth"]},
     ]},
    {"id": "a3", "index": 3, "title": "暗流",
     "goal": "王九带人上门了——查清这把'刀'真正的来意，城外的人到底图什么",
     # HARD gate: surface what 王九 is really here for
     "advance": {"required_fragment_ids": ["fr_wonggau2"], "affinity_min": 13},
     "events": [
        {"id": "e_wonggau", "what_happens": "一阵骚动，王九带着人堵在巷口，整条街瞬间噤声，连孩子都被捂住了嘴。", "who_character_ids": ["wonggau"]},
        {"id": "e_standoff", "what_happens": "龙卷风慢慢走出理发店，挡在所有人前面。两边对峙，谁都没先动手——可你看得出，这事远没完。", "who_character_ids": ["cyclone", "wonggau"]},
     ]},
    {"id": "a4", "index": 4, "title": "旧账",
     "goal": "大老板亲自进了城寨——查清他和龙卷风之间，几十年前到底结下了什么",
     # HARD gate: uncover the old feud between 龙卷风 and 大老板
     "advance": {"required_fragment_ids": ["fr_deal2"], "affinity_min": 18},
     "events": [
        {"id": "e_boss", "what_happens": "大老板亲自进了城寨。西装笔挺、笑意吟吟，给龙卷风递上一根烟，开口却句句是几十年前的旧账。", "who_character_ids": ["boss", "cyclone"]},
        {"id": "e_doubt", "what_happens": "蓝信一把你堵在窄巷里，似笑非笑：你那张纸条，他好像在哪儿见过——你到底是谁派来的。", "who_character_ids": ["shin"]},
     ]},
    {"id": "a5", "index": 5, "title": "龙头",
     "goal": "查清城寨庇护无身份者的真正门路——那条'龙头'，也正是你奉命来查的东西",
     # HARD gate: the city's core secret (layered) must be uncovered
     "advance": {"required_fragment_ids": ["fr_idsecret2"], "affinity_min": 23},
     "events": [
        {"id": "e_shin_open", "what_happens": "夜深，蓝信一难得没了那副吊儿郎当，跟你说起他欠龙卷风的那条命。", "who_character_ids": ["shin"]},
        {"id": "e_reveal", "what_happens": "龙卷风把你单独叫进理发店，剃刀在皮带上荡了两下，像是下了某种决心，要让你看一样东西。", "who_character_ids": ["cyclone"]},
     ]},
    {"id": "a6", "index": 6, "title": "围城",
     "goal": "围城将至，你得在警队的收网指令和城寨的人心之间，选一边站",
     "events": [
        {"id": "e_siege", "what_happens": "大老板的人马封死了城寨所有出口。龙卷风没退半步，守在理发店门前，城寨上下第一次为同一件事拧成一股绳。", "who_character_ids": ["cyclone"]},
        {"id": "e_choice", "what_happens": "对讲机在你怀里震动，是收网的指令。而身边，是这些天把你当自己人的兄弟。你只剩一个选择。", "who_character_ids": []},
     ]},
]

# Concrete physical places in the walled city — anchors the player's position so the model
# describes real fixtures (not vague atmosphere) and keeps movement consistent.
LOCATIONS = [
    {"id": "loc_alley", "name": "城寨暗巷",
     "detail": "终年不见天日的逼仄巷道，头顶电线与水管缠成一团，滴着不知名的水。墙面爬满霉斑和层层叠叠的招牌，"
     "脚下污水横流，空气里混着潮气、油烟和铁锈味。两侧是密不透风的违建楼，窗口透出昏黄的灯。",
     "exits": ["龙卷风的理发店", "巷口", "大牌档", "天台"]},
    {"id": "loc_barber", "name": "龙卷风的理发店",
     "detail": "一间窄小的旧式理发店，一张吱呀作响的转椅，墙上斑驳的镜子，剃刀和热毛巾搁在木台上。"
     "这里是城寨的'客厅'，几个后生仔常围在门口的矮凳上抽烟、嬉闹。龙卷风多半就在椅子边。",
     "exits": ["城寨暗巷"],
     # 必须有人亲口说出「龙卷风开的理发店」（fr_whoruns2 里点了名），这地方才出现在你可去的路上
     "unlock": {"required_fragment_ids": ["fr_whoruns2"]}},
    {"id": "loc_mouth", "name": "巷口",
     "detail": "城寨通向外界的一个隘口，光线在这里骤然亮起来。几步之外就是车水马龙的城外世界。"
     "收地、寻衅的人，往往先堵在这里。",
     "exits": ["城寨暗巷"],
     # 第三幕外面的人(王九)堵上门，巷口才成为局势的焦点、被你纳入眼里
     "unlock": {"act_min": 3}},
    {"id": "loc_dai", "name": "大牌档",
     "detail": "巷子里一处露天熟食档，几张油腻的折叠桌、长凳，炉火上大铁锅冒着热气。"
     "四仔这类包打听最爱在这儿一边吃一边收风，城里城外的消息都从这桌流到那桌。",
     "exits": ["城寨暗巷"],
     # 必须有人亲口提到「去大牌档找四仔打听」（fr_whoruns2 里点了名），才知道这个收风的地方
     "unlock": {"required_fragment_ids": ["fr_whoruns2"]}},
    {"id": "loc_roof", "name": "天台",
     "detail": "爬上锈蚀的铁梯才到的违建天台，是城寨少有能看见天的地方。晾衣绳横七竖八，水箱锈迹斑斑，"
     "脚下是密密麻麻、几乎连成一片的楼顶。围城时，这里是俯瞰全局、也是退无可退的地方。",
     "exits": ["城寨暗巷"],
     # 城寨少有人知的去处——要摸到'龙头'那条最深的门路(信任够深)，天台才向你敞开
     "unlock": {"required_fragment_ids": ["fr_idsecret1"]}},
]

# (title, character_id, sensitivity, known_by, [fragments])
# fragment = (fragment_id, layer, content, retrieval_key, unlock)
# fragment_id is explicit + stable so acts' advance gates can reference it.
# Big truths are LAYERED across multiple fragments — each peeled back in stages, so a
# playthrough is long and the reveal feels gradual rather than dumped at once.
SECRETS = [
    ("谁是话事人", "sei", "light", ["sei", "twelfth", "shin"], [
        ("fr_whoruns1", 1,
         "四仔压低声音：这城寨三不管，却没乱成一锅粥——不是没人管，是有人罩着。你别看这破地方，背后有个'话事人'。",
         # 只留"在打听谁是老大"的问法；泛词(规矩/城寨/这里)去掉，免得误触发
         "谁说了算 谁管事 谁做主 老大是谁 谁是老大 老板是谁 话事人 谁罩着 谁最大 头儿是谁",
         {"affinity_min": 0, "act_min": 1, "asks_min": 1}),
        ("fr_whoruns2", 2,
         "那人就是龙卷风，开破理发店的——想见他，就去巷尾那间理发店。全城寨他说了算，可他不收保护费、不摆架子，"
         "只认一个理——进了城寨门，就是自己人，他护到底，所以这儿的人谁都肯替他挡刀。"
         "你要打听城里城外的事，就去大牌档找四仔，那张桌子上什么消息都过得到。",
         # "他是谁/叫什么/在哪找"这类顺着话事人往下问的问法
         "龙卷风 话事人是谁 老大是谁 他叫什么 他是谁 他在哪 去哪找 找谁 理发店 大牌档 找四仔",
         {"affinity_min": 0, "act_min": 1, "asks_min": 2}),
    ]),
    ("十二少的逞强", "twelfth", "medium", ["twelfth", "sei"], [
        ("fr_twelfth", 1,
         "几杯酒下肚，十二少红着眼跟你交了底：他嘴上最横，心里最怕被当成只会冲动闯祸的莽夫。"
         "早年有一回他逞能，差点把兄弟搭进去，从那以后他憋着一股劲，就想在关键时刻替大哥、替兄弟真正顶上一次。"
         "他认人认得慢，可一旦认了你这个朋友，就是把后背交给你。",
         "十二少 逞强 冲动 莽夫 害过 兄弟 想证明 顶上 认你 朋友 后背 一股劲",
         {"affinity_min": 4, "act_min": 2, "asks_min": 1}),
    ]),
    ("四仔的小算盘", "sei", "medium", ["sei"], [
        ("fr_sei_hedge", 1,
         "四仔讪讪地承认：为了在乱世里留条活路，谁来打听他都卖点不痛不痒的边角消息，城外的人也不例外。"
         "但城寨真正的命脉，他一个字都没漏过——他只是怕，这点'两边讨好'要是被兄弟知道，他在城寨就没脸待了。",
         "四仔 卖消息 城外 两边 小算盘 活路 出卖 怕兄弟知道 命脉 没漏",
         {"affinity_min": 4, "act_min": 2, "asks_min": 2}),
    ]),
    ("王九这把刀", "sei", "medium", ["sei", "twelfth"], [
        ("fr_wonggau1", 1,
         "四仔一提王九就发怵：那是大老板手里最狠的一把刀，话不过三句，动手从不留情。在城外，挡他路的人都没好下场。",
         "王九 狠人 打手 刀 大老板 手下 厉害 危险 来头",
         {"affinity_min": 2, "act_min": 3, "asks_min": 1}),
        ("fr_wonggau2", 2,
         "再追问下去，四仔声音更低了：王九这趟根本不是来收租的——是来探城寨的底、给大老板探路的。"
         "他不急着动手，是在等龙卷风先露出破绽。这把刀亮在明处，背后那只手才可怕。",
         "王九 来意 探底 探路 不是收租 等破绽 大老板 背后 为什么来 图什么",
         {"affinity_min": 6, "act_min": 3, "asks_min": 2}),
    ]),
    ("城外的旧账", "cyclone", "medium", ["cyclone", "shin"], [
        ("fr_deal1", 1,
         "提起大老板，龙卷风难得沉默良久：几十年前，他俩本是一条道上、称兄道弟的人。后来，两人分道扬镳。",
         "大老板 旧账 从前 当年 认识 一条道 兄弟 过节 分开 恩怨",
         {"affinity_min": 8, "act_min": 4, "asks_min": 1}),
        ("fr_deal2", 2,
         "龙卷风把那段往事说透：当年两人立过约，也结过仇——他抽身退进城寨，护起这一城无处可去的人；"
         "大老板却越做越大，走的是另一条吃人的路。如今大老板卷土重来，要的从来不只是这块地，"
         "是要逼龙卷风把城寨连人带那条命脉，一起交出来。",
         "约定 立约 结仇 背叛 退出 护城寨 吃人 卷土重来 逼 交出 命脉 为什么盯上",
         {"affinity_min": 12, "act_min": 4, "asks_min": 2}),
    ]),
    ("信一的亏欠", "shin", "heavy", ["shin"], [
        ("fr_shin1", 1,
         "你越来越觉得蓝信一对龙卷风的忠诚近乎执拗。他嘴上算计天下，唯独提起大哥，玩笑就收了——"
         "他心里像压着一笔'还不完的账'，却绝口不提是什么。",
         "信一 蓝信一 忠诚 执拗 大哥 龙卷风 还不完 账 心结 为什么 这么向着",
         {"affinity_min": 10, "act_min": 4, "asks_min": 2}),
        ("fr_shin2", 2,
         "夜里，蓝信一终于卸下吊儿郎当：当年若不是龙卷风从死人堆里把他捞出来、又替他担下一桩本该要他命的祸事，"
         "早没有今天这个他。这条命是大哥给的，要还，就还到底。他防着你，不是怕你查城寨——是怕你，会害了龙卷风。",
         "救命 死人堆 担罪 顶罪 大哥救 还命 防我 怕你害 龙卷风 当年 那桩事",
         {"affinity_min": 16, "act_min": 5, "asks_min": 2}),
    ]),
    ("城寨的龙头", "cyclone", "heavy", ["cyclone"], [
        ("fr_idsecret1", 1,
         "你慢慢摸到点门道：城寨能容下这么多没身份的人、还没被外头连根拔起，靠的不是刀，是一条只有龙卷风一个人握着的'门路'。",
         "门路 龙头 庇护 没身份 偷渡 靠什么 命脉 一个人握 秘密 怎么做到",
         {"affinity_min": 12, "act_min": 5, "asks_min": 2}),
        ("fr_idsecret2", 2,
         "龙卷风看着你的眼睛，把那件事说破：那是一套能给偷渡客、给走投无路者一个全新身份、让他们重新做人的法子。"
         "这才是大老板眼红的'龙头'，也是你奉命要查的东西。说完他笑了笑——你忽然明白，他是把你，也当成了需要这条门路的人。",
         "新身份 重新做人 偷渡客 龙头 一套法子 大老板眼红 奉命查 门路是什么 当成需要的人",
         {"affinity_min": 16, "act_min": 5, "asks_min": 3}),
        ("fr_idsecret3", 3,
         "他没说的还有一层：这条门路，是他用自己半条命、和一段不能见光的过去换来的。一旦曝光，完的不只是城寨——"
         "那些靠它重新做人的几百号人，会被一张一张揪回原形。你手里那张纸条，能要的不是一座城，是几百条命。",
         "代价 半条命 不能见光 过去 曝光 几百人 揪回 原形 你的纸条 几百条命 后果",
         {"affinity_min": 20, "act_min": 5, "asks_min": 3}),
    ]),
    ("他早看穿了你", "cyclone", "heavy", ["cyclone"], [
        ("fr_seen_through", 2,
         "把所有事拼起来你才惊觉：龙卷风从你踏进城寨第一天起，就看穿了你是差人。他没点破、没赶你，反而一次次护你周全。"
         "他常说，进了城寨门就是自己人——这话，原来连查他的你，也算在里头。他赌的是：你在这座城里待得越久，越下不去那只收网的手。",
         "看穿 早知道 卧底 差人 警察 识破 为什么不赶我 一直护着 自己人 收网 他赌",
         {"affinity_min": 20, "act_min": 6, "asks_min": 2}),
    ]),
]

# Authored endings — milestones, checked at the final act; best match wins (真＞普通＞坏).
# Death also fires dynamically when the player does something fatal.
ENDINGS = [
    {"id": "end_true", "kind": "true", "title": "落脚之地",
     "text": "收网的指令在你掌心震了最后一下，你把对讲机摁灭，扔进了污水沟。围城那一夜，你和城寨的人站在了一起。"
             "天亮时大老板的人退了，龙卷风没说什么，只是替你在那本谁也看不见的册子上，添了一个新名字——"
             "从今往后，你也是城寨的人。这座不见天日的城，第一次让你觉得，像个家。",
     "condition": {"affinity_min": 24, "act_min": 0,
                   "required_fragment_ids": ["fr_idsecret3", "fr_seen_through"]}},
    {"id": "end_normal", "kind": "normal", "title": "围城之后",
     "text": "你没有按下收网，也没有真正留下。围城过后，你交了一份语焉不详的报告，请调离了这案子。"
             "城寨照旧在暗巷里喘着气，龙卷风照旧守着他的理发店。你再没回去过，只是每逢下雨，"
             "总会想起那条头顶结满电线的窄巷，和几个把你当过自己人的兄弟。",
     "condition": {"affinity_min": 12, "act_min": 0}},
    {"id": "end_bad", "kind": "bad", "title": "收网",
     "text": "你终究是差人。哨声响起那一刻，你按章办事，端了城寨，也亲手把那条护了一城人的门路交了上去。"
             "你立了功，升了职。只是从此再没有哪座城会认你做自己人——龙卷风被带走时回头看了你一眼，"
             "那眼神里没有恨，只有一句他从前常说、如今再不会对你说的话：进了城寨门，就是自己人。",
     "condition": {"affinity_min": 0, "act_min": 0}},
    {"id": "end_death", "kind": "death", "title": "刀下亡魂",
     "text": "你沉不住气，在最不该亮身份的时候亮了底。王九的刀比城寨的灯先到——你倒在那条满是污水的暗巷里，"
             "怀里那张联系线人的纸条，再也递不出去了。",
     "condition": {"affinity_min": 0, "act_min": 0}},
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
                   tagline="刚入行的初级刑警", background="奉命假扮外来妹，潜入九龙城寨查案。"))
    db.commit()
    return u


def wipe_existing(db, owner_id: str) -> None:
    for s in db.query(Story).filter(Story.owner_id == owner_id, Story.title == TITLE).all():
        db.query(Run).filter(Run.story_id == s.id).delete()
        db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).delete()
        db.delete(s)  # cascades secrets + fragments
    db.commit()


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        user = get_or_create_demo_user(db)
        wipe_existing(db, user.id)

        story = Story(
            owner_id=user.id,
            title=TITLE,
            one_liner="八十年代，九龙城寨。你是混进来的初级刑警蔡妍——查的是城寨的命脉，丢的，可能是自己的心。",
            synopsis="三不管的九龙城寨，藏着一条能给无身份者重新做人的门路。初级刑警蔡妍奉命假扮外来妹潜入，"
            "要查清这条'龙头'。她在话事人龙卷风和城寨四子之间一步步取得信任，撞上城外大老板的围城与旧账，"
            "也撞上一个她没料到的真相——龙卷风，或许从第一天就看穿了她。四幕之后，她要在警队的命令和城寨的人心之间，选一边。",
            world_long="八十年代的香港九龙城寨：三不管地带，楼宇违建挤成一团，暗巷常年不见天日，头顶电线如蛛网，"
            "地上污水横流。这里聚着无数没有身份、走投无路的人。话事人龙卷风开着一间小理发店，护着全城寨，"
            "不收保护费，只认'进了城寨门就是自己人'。城外，黑帮龙头大老板觊觎已久，欲连人带城寨的命脉一并吞下，"
            "与龙卷风之间还压着一笔几十年的旧账。",
            relations_overview="玩家是潜入城寨的初级刑警蔡妍。龙卷风是城寨话事人、信任的关口；蓝信一最精明、最先起疑；"
            "十二少最直、最易松口；四仔是包打听、城里城外的消息都在他那儿。王九是大老板的刀（第二幕上门），"
            "大老板第三幕亲临。城寨的核心秘密——给无身份者新身份的'龙头'——握在龙卷风手里。",
            world_facts=(
                "【地点】故事都发生在九龙城寨内：终年不见天日的逼仄暗巷、横流的污水、头顶蛛网般的电线；"
                "龙卷风那间小理发店是城寨的据点和'客厅'，大事小情都在这里和巷口发生。城寨有多个隐蔽出入口，"
                "外人极易迷路。\n"
                "【年代】八十年代香港，城寨是'三不管'地带：港英政府、警方、帮派都难以真正管辖，里面没有正规警察执法。\n"
                "【在场的人】城寨这边常在场的是：龙卷风、蓝信一、十二少、四仔，以及玩家扮演的蔡妍。"
                "王九是城外大老板的打手，第二幕才带人上门；大老板本人第三幕才亲自进城寨——在那之前，这两人都不在场，不要让他们提前出现。\n"
                "【身份·要点】蔡妍的警察身份是卧底秘密：她自己心知肚明，但城寨众人表面上只当她是个走投无路、来投奔城寨的外来妹。"
                "她身上没有证件，只有一张联系线人的纸条。不要让普通城寨居民一上来就喊破她是差人。"
            ),
            trope_tags=["黑帮", "城寨", "卧底", "悬疑", "兄弟情义", "年代"],
            mature=True,  # 18+：开启成人内容（恋人线可发展到床戏，玩家需年龄达标）
            characters=CHARACTERS,
            acts=ACTS,
            endings=ENDINGS,
            locations=LOCATIONS,
            visibility="public",
        )
        db.add(story)
        db.flush()

        for title, char_id, sens, known_by, frags in SECRETS:
            sec = Secret(story_id=story.id, character_id=char_id, title=title, sensitivity=sens)
            sec.fragments = [
                Fragment(id=fid, layer=layer, content=content, retrieval_key=rkey,
                         known_by_character_ids=known_by, unlock=unlock)
                for (fid, layer, content, rkey, unlock) in frags
            ]
            db.add(sec)
        db.flush()
        db.refresh(story)

        # publish: freeze v1 snapshot
        content = {
            "story": _to_story(story).model_dump(),
            "secrets": [_to_secret(s).model_dump() for s in story.secrets],
        }
        content["story"]["version"] = 1
        db.add(StorySnapshot(story_id=story.id, version=1, content=content))
        story.version = 1
        story.status = "published"
        db.commit()

        n_frag = sum(len(f) for *_, f in SECRETS)
        print(f"OK seeded 《{TITLE}》  story_id={story.id}")
        print(f"   owner={DEMO_EMAIL} (pw: {DEMO_PW})  secrets={len(SECRETS)} fragments={n_frag}")
        print("   主角=蔡妍(初级刑警)。published v1, public.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
