import type { ChapterBundle } from "./api";
import { cleanLines } from "./worldDisplay";

export type RuleCard = {
  id: string;
  category: string;
  title: string;
  rule: string;
  firstChapter: number;
};

type RuleSpec = {
  id: string;
  category: string;
  title: string;
  rule: string;
  triggers: string[];
};

const RULE_SPECS: RuleSpec[] = [
  {
    id: "currency-no-rmt",
    category: "经济",
    title: "货币封闭",
    rule: "开服初期没有官方现实货币兑换，游戏币只能在游戏内流通。",
    triggers: ["现实货币兑换", "游戏币还只能在游戏里流通"],
  },
  {
    id: "information-gap",
    category: "经济",
    title: "信息差价值",
    rule: "开服前几天的信息差比单次材料收益更值钱。",
    triggers: ["信息差最值钱"],
  },
  {
    id: "small-flow-noise",
    category: "风险",
    title: "小额流水噪音",
    rule: "小额低级材料交易会被新手市场吞掉，不会立刻引发商人、公会或系统注意。",
    triggers: ["小额流水", "新手市场吞掉", "普通新手噪音"],
  },
  {
    id: "forum-baseline",
    category: "情报",
    title: "论坛基准",
    rule: "论坛是掉率、价格、坐标和玩家抱怨的低成本情报源。",
    triggers: ["论坛", "帖子", "材料贴"],
  },
  {
    id: "gray-wolf-drop-rate",
    category: "掉落",
    title: "灰狼掉率基准",
    rule: "灰狼毒腺基准掉率约20%-30%，粗糙狼皮约40%。",
    triggers: ["灰狼毒腺掉率", "两成到三成", "粗糙狼皮大概四成"],
  },
  {
    id: "scavenger-batch",
    category: "任务",
    title: "清道夫委托批量",
    rule: "清道夫委托按十份灰狼毒腺一批结算，奖励三十铜。",
    triggers: ["十份毒腺一批", "奖励三十铜", "提交十份灰狼毒腺"],
  },
  {
    id: "npc-no-buffer",
    category: "任务",
    title: "NPC不记账",
    rule: "服务NPC不做缓冲，不够十份不能先记，凑齐才结算。",
    triggers: ["九份毒腺能不能先记着", "不给缓冲", "十份就是十份"],
  },
  {
    id: "single-material-market",
    category: "交易",
    title: "单份走交易木牌",
    rule: "药剂铺不零收毒腺，单份材料要走交易木牌。",
    triggers: ["不零收", "交易木牌"],
  },
  {
    id: "repair-cost",
    category: "补给",
    title: "修理价格",
    rule: "新手法杖修理起步三铜，耐久低于五点多收一铜，断了重铸十铜。",
    triggers: ["修理新手法杖起步三铜", "耐久低于五点多收一铜", "断了重铸，十铜"],
  },
  {
    id: "mana-potion-cost",
    category: "补给",
    title: "蓝药价格",
    rule: "小型蓝药八铜一瓶，是前期续航成本锚点。",
    triggers: ["小型蓝药八铜", "小蓝药八铜"],
  },
  {
    id: "mage-cost-profile",
    category: "职业",
    title: "法师轻资产",
    rule: "战士修盾、游侠买箭，法师主要管理法杖和蓝量，适合低成本单刷。",
    triggers: ["战士前期要修盾", "游侠要买箭", "蓝量管理"],
  },
  {
    id: "element-corridor",
    category: "职业",
    title: "十级前置",
    rule: "元素法师十级有元素回廊试炼线索，升级路线要服务这个前置。",
    triggers: ["十级还有元素回廊试炼线索", "元素回廊"],
  },
  {
    id: "combat-distance",
    category: "战斗",
    title: "拉距离战斗",
    rule: "元素学徒依靠火球、走位和拉距离击杀灰狼，不能硬吃贴脸。",
    triggers: ["拉开五米距离", "基础火球术", "卡距离"],
  },
  {
    id: "gray-wolf-refresh",
    category: "战斗",
    title: "刷新点压力",
    rule: "灰狼刷新快，但玩家密度会推高抢怪、带怪和路线成本。",
    triggers: ["刷新快", "抢怪", "刷新点"],
  },
  {
    id: "bag-stack",
    category: "背包",
    title: "材料分格",
    rule: "背包格有限；同类低级材料可叠加，不同材料分格，补给、耐久和格子才是前期限制。",
    triggers: ["背包只有十格", "低级材料可以叠加", "不同材料会分开"],
  },
  {
    id: "panel-ledger",
    category: "面板",
    title: "面板回写",
    rule: "经验、生命、法力、货币、装备耐久和背包必须持续回写，后续收益从账本变化而来。",
    triggers: ["经验：30/100", "生命：46/100", "法力：0/60", "耐久4/10", "背包：灰狼毒腺"],
  },
  {
    id: "sample-isolation",
    category: "主角行为",
    title: "异常隔离",
    rule: "发现异常先当风险隔离样本，不立刻当福利冲收益。",
    triggers: ["先把异常当成风险", "隔离样本"],
  },
  {
    id: "no-early-cashout",
    category: "主角行为",
    title: "第一章不变现",
    rule: "第一章目标是确认边界，不是赚钱；不急着上架变现。",
    triggers: ["第一章的目标不是赚钱", "确认边界"],
  },
  {
    id: "cost-before-profit",
    category: "主角行为",
    title: "成本先到",
    rule: "每次收益前先算修理、药水、血量、法力、耐久、背包和死亡亏损。",
    triggers: ["成本已经先到了", "必要成本", "可选成本", "死一次就亏"],
  },
  {
    id: "goldfinger-no-name",
    category: "主角行为",
    title: "不急着命名金手指",
    rule: "异常未稳定前不急着命名，避免替结果找理由。",
    triggers: ["异常一旦被自己命名", "最后一个样本"],
  },
];

function chapterText(bundle: ChapterBundle): string {
  return [
    bundle.chapter_title || "",
    bundle.body || "",
    bundle.chapter_summary?.summary || "",
    ...(bundle.chapter_summary?.facts ?? []),
    bundle.next_outline || "",
  ].join("\n");
}

export function buildRuleCards(history: ChapterBundle[] | undefined, worldFacts: string[] | undefined): RuleCard[] {
  const factsText = cleanLines(worldFacts).join("\n");
  const cards: RuleCard[] = [];
  const seen = new Set<string>();

  for (const spec of RULE_SPECS) {
    let firstChapter = 0;
    for (const bundle of history ?? []) {
      const text = chapterText(bundle);
      if (spec.triggers.some((trigger) => text.includes(trigger))) {
        firstChapter = bundle.chapter_number;
        break;
      }
    }

    if (!firstChapter && spec.triggers.some((trigger) => factsText.includes(trigger))) {
      firstChapter = 1;
    }

    if (!firstChapter || seen.has(spec.id)) continue;
    seen.add(spec.id);
    cards.push({
      id: spec.id,
      category: spec.category,
      title: spec.title,
      rule: spec.rule,
      firstChapter,
    });
  }

  return cards.sort((a, b) => a.firstChapter - b.firstChapter || a.category.localeCompare(b.category, "zh-CN"));
}
