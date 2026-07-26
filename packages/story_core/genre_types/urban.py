from __future__ import annotations

from packages.story_core.genre_types.base import GenrePlugin
from packages.story_core.power_system_templates import copy_power_system_template


URBAN = GenrePlugin(
    plugin_id="urban",
    name="都市现代",
    keywords=("都市", "职场", "豪门", "商业", "娱乐圈", "直播", "校园", "现代", "公司", "资本"),
    core_promises=(
        "读者期待现实压力下的资源翻盘、人际博弈、身份反差和阶段性打脸兑现。",
    ),
    ledger_fields=("金钱", "人脉", "事业阶段", "舆论", "身份秘密", "对手压力"),
    rulebook={
        "progression_rules": (
            "事业、财富、人脉和名声的提升必须有事件来源和现实阻力。",
        ),
        "economy_rules": (
            "合同、资金、流量、资源置换和商业利益必须符合现实逻辑。",
        ),
        "quest_rules": (
            "每个阶段目标要能落在项目、比赛、合同、舆论或关系节点上。",
        ),
        "faction_rules": (
            "公司、家族、平台、媒体和竞争者要对主角行动产生真实反馈。",
        ),
        "panel_rules": (
            "现实题材少用说明书旁白，优先通过对话、信息差和现场压力展示规则。",
        ),
        "chapter_formula": (
            "用现实困境开场，通过选择和博弈制造反转，结尾留下更高层对手或更大机会。",
        ),
        "forbidden_breaks": (
            "禁止无逻辑暴富，禁止所有人突然配合主角，禁止现实系统失真。",
        ),
    },
    quality_checks=("现实逻辑", "利益闭环", "反转可信", "人际压力", "舆论反馈"),
    power_system_template=copy_power_system_template("urban"),
    trope_templates=(
        {
            "id": "shenhao_system_spend",
            "name": "神豪系统消费反转",
            "trigger": "主角被现实经济压力、分手、羞辱或阶层差压住，需要用财富优势制造爽点。",
            "beats": ["现实羞辱", "财富/系统到账", "小额验证", "消费或投资选择", "对手误判后反转"],
            "payoff": "财富优势转化为地位变化或资源入口。",
            "avoid": ["不要无逻辑撒钱", "不要只堆金额", "不要忽略平台、合同和税务等现实摩擦"],
        },
        {
            "id": "professional_save_the_day",
            "name": "专业能力救场",
            "trigger": "项目、手术、谈判、比赛、直播或公关现场出现危机。",
            "beats": ["危机公开化", "普通方案失败", "主角识别关键变量", "专业操作", "成果引出新机会和新对手"],
            "payoff": "打脸来自能力证据，而不是嘴炮身份。",
            "avoid": ["不要让专业流程失真", "不要全员突然配合", "不要解决危机后没有利益归属"],
        },
        {
            "id": "hidden_identity_reveal",
            "name": "隐藏身份揭一层",
            "trigger": "主角被低估到影响目标推进，需要暴露一部分身份、资源或履历。",
            "beats": ["被低估", "保留底牌", "拿出可验证证据", "局部身份反转", "更高层势力注意"],
            "payoff": "身份爽点兑现一层，同时保留后续空间。",
            "avoid": ["不要一次揭完全部马甲", "不要只靠名头压人", "不要让敌人无脑跪服"],
        },
        {
            "id": "public_opinion_turnaround",
            "name": "舆论翻盘",
            "trigger": "主角被网暴、污蔑、资本压制或同行抢功。",
            "beats": ["负面舆论", "证据收集", "选择发布时间/渠道", "舆论反转", "平台或资本二次反应"],
            "payoff": "现实压力通过信息和利益链条翻盘。",
            "avoid": ["不要证据凭空出现", "不要网友全体同一种声音", "不要忽略反噬和公关成本"],
        },
    ),
)
