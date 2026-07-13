export type NovelTypeOption = {
  id: string;
  label: string;
  description: string;
};

export const DEFAULT_NOVEL_TYPE_ID = "generic_webnovel";

export const NOVEL_TYPE_OPTIONS: NovelTypeOption[] = [
  {
    id: "generic_webnovel",
    label: "通用网文",
    description: "不绑定具体题材规则，只保留章节推进、钩子、人物动机和连续性要求。",
  },
  {
    id: "game_webnovel",
    label: "网游升级",
    description: "加载等级、面板、背包、任务、货币、掉落、玩家生态和NPC服务规则。",
  },
  {
    id: "urban",
    label: "都市现代",
    description: "加载职场、商业、舆论、人际关系、现实利益和身份反差规则。",
  },
  {
    id: "xuanhuan",
    label: "东方玄幻",
    description: "自创力量、异物机缘、资源成长和世界秘密。",
  },
  {
    id: "xianxia",
    label: "修仙仙侠",
    description: "灵根修炼、道法因果、渡劫飞升和长生求道。",
  },
  {
    id: "suspense",
    label: "悬疑推理",
    description: "加载线索、证据链、嫌疑人、调查推进和公平反转规则。",
  },
  {
    id: "romance",
    label: "言情关系",
    description: "加载关系拉扯、情绪递进、误会、靠近和外部阻碍规则。",
  },
  {
    id: "rules_mystery",
    label: "规则怪谈",
    description: "加载规则验证、禁忌代价、污染递进和异常逻辑规则。",
  },
];

export function novelTypeLabel(id: string | undefined): string {
  return NOVEL_TYPE_OPTIONS.find((item) => item.id === id)?.label ?? "通用网文";
}
