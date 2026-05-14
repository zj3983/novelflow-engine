import type { GamePanel, ImportedCharacterProfile, StoryCharacter } from "./api";

type ProfileWithRuntime = ImportedCharacterProfile & {
  game_panel?: GamePanel;
  memory?: string[];
  current_emotion?: string;
  current_location?: string;
  location?: string;
  lifecycle_state?: string;
  latest_chapter?: number;
};

export type DisplayCharacter = ProfileWithRuntime & {
  game_panel?: GamePanel;
  memory?: string[];
  goals?: string[];
  secrets?: string[];
  location?: string;
  lifecycle_state?: string;
};

function cleanText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

const NON_CHARACTER_ROLES = new Set(["信息源", "玩家群体", "市场机制", "任务线", "服务设施", "系统机制"]);
const NON_CHARACTER_NAMES = new Set(["论坛", "公共频道", "交易行告示牌", "清道夫委托", "系统公告"]);

function canonicalCharacterName(name: unknown): string {
  const text = cleanText(name);
  const aliases: Record<string, string> = {
    药剂师NPC: "药剂师洛婶",
    药剂师: "药剂师洛婶",
    药剂铺老妇人: "药剂师洛婶",
    灰头巾老妇人: "药剂师洛婶",
    老妇人: "药剂师洛婶",
    洛婶: "药剂师洛婶",
    "补给商·铁栓": "仓库管理员铁栓",
    补给商铁栓: "仓库管理员铁栓",
    铁栓: "仓库管理员铁栓",
  };
  return aliases[text] ?? text;
}

function isCharacterLike(value: { name?: unknown; role?: unknown }): boolean {
  const name = canonicalCharacterName(value.name);
  const role = cleanText(value.role);
  if (!name) return false;
  if (NON_CHARACTER_NAMES.has(name)) return false;
  if (NON_CHARACTER_ROLES.has(role)) return false;
  return true;
}

export function isReadableLine(value: unknown): value is string {
  const text = cleanText(value);
  if (!text) return false;
  const questionMarks = (text.match(/\?/g) ?? []).length;
  if (questionMarks >= 3) return false;
  if (/codex hand-written|model draft|small-trade overreaction/i.test(text)) return false;
  return true;
}

export function cleanLines(values: unknown[] | undefined, limit?: number): string[] {
  const seen = new Set<string>();
  const lines: string[] = [];

  for (const value of values ?? []) {
    if (!isReadableLine(value)) continue;
    const text = cleanText(value);
    if (seen.has(text)) continue;
    seen.add(text);
    lines.push(text);
    if (limit && lines.length >= limit) break;
  }

  return lines;
}

export function mergeCharacters(
  profiles: ImportedCharacterProfile[] | undefined,
  storyCharacters: StoryCharacter[] | undefined,
): DisplayCharacter[] {
  const byName = new Map<string, DisplayCharacter>();

  for (const profile of (profiles ?? []) as ProfileWithRuntime[]) {
    if (!isCharacterLike(profile)) continue;
    const name = canonicalCharacterName(profile.name);
    byName.set(name, { ...profile, name });
  }

  for (const character of storyCharacters ?? []) {
    if (!isCharacterLike(character)) continue;
    const name = canonicalCharacterName(character.name);
    const previous = byName.get(name) ?? { name };
    byName.set(name, {
      ...previous,
      ...character,
      name,
      role: character.role || previous.role,
      game_id: character.game_id || previous.game_id,
      goals: character.goals?.length ? character.goals : previous.goals,
      memory: character.memory?.length ? character.memory : previous.memory,
      secrets: character.secrets?.length ? character.secrets : previous.secrets,
      location: character.location || previous.location || previous.current_location,
      game_panel: character.game_panel ?? previous.game_panel,
      lifecycle_state: character.lifecycle_state || previous.lifecycle_state,
    });
  }

  return Array.from(byName.values());
}

export function shortStatus(character: DisplayCharacter): string {
  return (
    character.current_state ||
    character.motivation ||
    character.location ||
    character.current_location ||
    character.memory?.[0] ||
    "暂无状态。"
  );
}

export function panelRows(panel: GamePanel | undefined): Array<[string, string]> {
  if (!panel) return [];
  const rows: Array<[string, string | number | null | undefined]> = [
    ["游戏ID", panel.game_id],
    ["等级", panel.level],
    ["职业", panel.class_path],
    ["经验", panel.exp],
    ["生命", panel.hp],
    ["法力", panel.mp],
    ["货币", panel.currency],
  ];

  return rows
    .filter(([, value]) => value !== undefined && value !== null && `${value}`.trim() !== "")
    .map(([label, value]) => [label, `${value}`]);
}

export function compactRecord(value: Record<string, unknown> | undefined): string[] {
  if (!value) return [];
  return Object.entries(value)
    .map(([key, item]) => {
      if (Array.isArray(item)) return `${key}: ${item.join("、")}`;
      if (item && typeof item === "object") return `${key}: ${Object.values(item).join("、")}`;
      return `${key}: ${item}`;
    })
    .filter(isReadableLine);
}
