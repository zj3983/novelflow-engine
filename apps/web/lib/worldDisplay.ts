import type {
  CharacterPortrait,
  CharacterStateLayer,
  GamePanel,
  ImportedCharacterProfile,
  ProjectResponse,
  StoryCharacter,
} from "./api";

export type GroupedWorldFacts = {
  projectFacts: string[];
  chapters: Array<{ chapterNumber: number; facts: string[] }>;
};

const NOVEL_TYPE_DISPLAY_NAMES: Record<string, string> = {
  generic_webnovel: "通用网文",
  game_webnovel: "网游升级流",
  urban: "都市现代",
  xuanhuan: "东方玄幻",
  xianxia: "修仙仙侠",
  suspense: "悬疑推理",
  romance: "言情关系流",
  rules_mystery: "规则怪谈",
};

export function displayNovelTypeMetadata(value: string): string {
  return value.replace(/小说类型[：:]\s*([a-z][a-z0-9_-]*)/gi, (source, rawTypeId: string) => {
    const typeId = rawTypeId.toLowerCase();
    const displayName = NOVEL_TYPE_DISPLAY_NAMES[typeId];
    return displayName ? `小说类型：${displayName}` : source;
  });
}

export function groupWorldFacts(facts: string[] | undefined): GroupedWorldFacts {
  const projectFacts: string[] = [];
  const chapters = new Map<number, string[]>();
  const chapterPrefix = /^第\s*(\d+)\s*章事实[：:]\s*(.*)$/;

  for (const value of facts ?? []) {
    const fact = typeof value === "string" ? value.trim() : "";
    if (!fact) continue;
    const match = fact.match(chapterPrefix);
    if (!match) {
      projectFacts.push(displayNovelTypeMetadata(fact));
      continue;
    }
    const content = match[2].trim();
    if (!content) continue;
    const chapterNumber = Number(match[1]);
    chapters.set(chapterNumber, [...(chapters.get(chapterNumber) ?? []), displayNovelTypeMetadata(content)]);
  }

  return {
    projectFacts,
    chapters: Array.from(chapters, ([chapterNumber, chapterFacts]) => ({
      chapterNumber,
      facts: chapterFacts,
    })).sort((left, right) => left.chapterNumber - right.chapterNumber),
  };
}

type ProfileWithRuntime = ImportedCharacterProfile & {
  game_panel?: GamePanel;
  current_state?: CharacterStateLayer | string;
  real_state?: CharacterStateLayer;
  game_state?: CharacterStateLayer;
  memory?: string[];
  current_emotion?: string;
  current_location?: string;
  location?: string;
  lifecycle_state?: string;
  personality_portrait?: CharacterPortrait;
  latest_chapter?: number;
};

export type DisplayCharacter = ProfileWithRuntime & {
  game_panel?: GamePanel;
  current_state?: CharacterStateLayer | string;
  real_state?: CharacterStateLayer;
  game_state?: CharacterStateLayer;
  character_type?: string;
  core_motivation?: string;
  behavior_logic?: string;
  interaction_mode?: string;
  poison_points?: string[];
  social_profile?: Record<string, unknown>;
  psychological_profile?: Record<string, unknown>;
  moral_profile?: Record<string, unknown>;
  story_function?: string;
  chapter_role?: string;
  memory?: string[];
  goals?: string[];
  secrets?: string[];
  location?: string;
  lifecycle_state?: string;
};

function cleanText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

const NON_CHARACTER_ROLES = new Set(["信息源", "玩家群体", "市场机制", "任务线", "服务设施", "系统机制", "收购方NPC"]);
const NON_CHARACTER_NAMES = new Set(["论坛", "公共频道", "交易行告示牌", "清道夫委托", "系统公告", "白河仓库收购方"]);

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

const IDENTITY_ALIAS_PATTERN = /(?:现实身份|本名|真名|原名|现实姓名|游戏ID|游戏名|网名|化名)\s*[：:]?\s*([A-Za-z0-9_\-\u4e00-\u9fff]{2,24})/g;

function characterIdentityTokens(character: ProfileWithRuntime): Set<string> {
  const tokens = new Set<string>();
  const add = (value: unknown) => {
    const text = cleanText(value);
    if (text) tokens.add(text.toLocaleLowerCase());
  };
  add(character.name);
  add(character.game_id);
  add(character.game_panel?.game_id);
  add(character.game_state?.current?.game_id);
  const identity = character.identity_profile as Record<string, unknown> | undefined;
  for (const alias of Array.isArray(identity?.aliases) ? identity.aliases : []) add(alias);
  for (const value of [character.role, identity?.current_identity]) {
    const text = cleanText(value);
    for (const match of text.matchAll(IDENTITY_ALIAS_PATTERN)) add(match[1]);
  }
  return tokens;
}

function characterPreference(character: ProfileWithRuntime): number {
  const name = cleanText(character.name);
  const gameId = cleanText(character.game_id);
  const role = cleanText(character.role).toLocaleLowerCase();
  const tier = cleanText(character.character_tier).toLocaleLowerCase();
  return (gameId && gameId !== name ? 4 : 0)
    + (role === "protagonist" || role === "主角" || tier === "protagonist" || tier === "主角" ? 2 : 0);
}

function mergeDisplayCharacter(previous: DisplayCharacter, character: ProfileWithRuntime): DisplayCharacter {
  const preferred = characterPreference(character) > characterPreference(previous) ? character : previous;
  const name = cleanText(preferred.name) || cleanText(character.name) || cleanText(previous.name);
  return {
    ...previous,
    ...character,
    name,
    role: character.role || previous.role,
    game_id: character.game_id || previous.game_id,
    character_tier: character.character_tier || previous.character_tier,
    importance: character.importance || previous.importance,
    narrative_function: character.narrative_function || previous.narrative_function,
    profile_status: character.profile_status || previous.profile_status,
    profile_completeness: character.profile_completeness ?? previous.profile_completeness,
    identity_profile: character.identity_profile ?? previous.identity_profile,
    background_profile: character.background_profile ?? previous.background_profile,
    current_life_profile: character.current_life_profile ?? previous.current_life_profile,
    story_drive: character.story_drive ?? previous.story_drive,
    performance_profile: character.performance_profile ?? previous.performance_profile,
    dialogue_examples: character.dialogue_examples?.length ? character.dialogue_examples : previous.dialogue_examples,
    relationship_notes: character.relationship_notes?.length ? character.relationship_notes : previous.relationship_notes,
    character_type: character.character_type || previous.character_type,
    core_motivation: character.core_motivation || previous.core_motivation,
    behavior_logic: character.behavior_logic || previous.behavior_logic,
    interaction_mode: character.interaction_mode || previous.interaction_mode,
    poison_points: character.poison_points?.length ? character.poison_points : previous.poison_points,
    social_profile: character.social_profile ?? previous.social_profile,
    psychological_profile: character.psychological_profile ?? previous.psychological_profile,
    moral_profile: character.moral_profile ?? previous.moral_profile,
    story_function: character.story_function || previous.story_function,
    chapter_role: character.chapter_role || previous.chapter_role,
    goals: character.goals?.length ? character.goals : previous.goals,
    memory: character.memory?.length ? character.memory : previous.memory,
    secrets: character.secrets?.length ? character.secrets : previous.secrets,
    location: character.location || previous.location || previous.current_location,
    game_panel: character.game_panel ?? previous.game_panel,
    current_state: character.current_state ?? previous.current_state,
    real_state: character.real_state ?? previous.real_state,
    game_state: character.game_state ?? previous.game_state,
    lifecycle_state: character.lifecycle_state || previous.lifecycle_state,
    personality_portrait: character.personality_portrait ?? previous.personality_portrait,
  };
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
  storyCharacters: Array<Partial<StoryCharacter> & Pick<StoryCharacter, "name">> | undefined,
): DisplayCharacter[] {
  const byName = new Map<string, DisplayCharacter>();
  const tokensByName = new Map<string, Set<string>>();

  const addCharacter = (raw: ProfileWithRuntime) => {
    if (!isCharacterLike(raw)) return;
    const name = canonicalCharacterName(raw.name);
    const tokens = characterIdentityTokens(raw);
    const existingName = Array.from(tokensByName.entries()).find(([, existingTokens]) => (
      Array.from(tokens).some((token) => existingTokens.has(token))
    ))?.[0];
    if (!existingName) {
      byName.set(name, { ...raw, name });
      tokensByName.set(name, tokens);
      return;
    }
    const previous = byName.get(existingName) ?? { name: existingName };
    const merged = mergeDisplayCharacter(previous, { ...raw, name });
    byName.delete(existingName);
    byName.set(merged.name, merged);
    const mergedTokens = tokensByName.get(existingName) ?? new Set<string>();
    tokensByName.delete(existingName);
    tokensByName.set(merged.name, new Set([...mergedTokens, ...tokens]));
  };

  for (const profile of (profiles ?? []) as ProfileWithRuntime[]) {
    addCharacter(profile);
  }

  for (const character of storyCharacters ?? []) {
    addCharacter(character as ProfileWithRuntime);
  }

  return Array.from(byName.values());
}

export function shortStatus(character: DisplayCharacter): string {
  const explicitState = typeof character.current_state === "string"
    ? character.current_state
    : String(character.current_state?.current?.summary ?? "");
  const status = (
    explicitState ||
    character.motivation ||
    character.location ||
    character.current_location ||
    character.memory?.[0] ||
    "暂无状态。"
  );
  const identity = status.match(/\*\*(?:身份|角色定位)\*\*[：:]\s*([^；\n]+)/)?.[1];
  if (identity?.trim()) return identity.trim();
  return status
    .replace(/^#+\s*[^；\n]*[；\n]?\s*/, "")
    .replace(/(?:^|[；\n])\s*-\s*/g, "；")
    .replace(/\*\*/g, "")
    .replace(/^；+|；+$/g, "")
    .trim() || "暂无状态。";
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
  return Object.entries(value).map(([key, item]) => `${key}: ${formatDisplayValue(item)}`).filter(isReadableLine);
}

export function formatDisplayValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(formatDisplayValue).filter(Boolean).join("、");
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, nestedValue]) => [key, formatDisplayValue(nestedValue)] as const)
      .filter(([, nestedValue]) => Boolean(nestedValue))
      .map(([key, nestedValue]) => `${key}：${nestedValue}`)
      .join("；");
  }
  return String(value ?? "").trim();
}

function formatStateValue(value: unknown): string {
  return formatDisplayValue(value);
}

const STATE_LABELS: Record<string, string> = {
  identity: "身份",
  current_identity: "当前身份",
  occupation: "职业",
  income: "收入",
  residence: "住处",
  livelihood: "生计",
  class_pressure: "现实压力",
  realm: "修为境界",
  cultivation: "修为境界",
  cultivation_realm: "修为境界",
  game_id: "游戏ID",
  level: "等级",
  class_path: "职业",
  exp: "经验",
  hp: "生命",
  mp: "法力",
  attributes: "属性",
  skills: "技能",
  equipment: "装备",
  inventory: "背包",
  currency: "货币",
  quests: "任务",
  risk: "风险",
};

function stateLabel(key: string): string {
  return STATE_LABELS[key] ?? (/[^\x00-\x7F]/.test(key) ? key : "其他状态");
}

const PROFILE_STATE_KEYS = new Set(["identity_profile", "background_profile", "current_life_profile", "story_drive"]);

export function isGameWebnovel(project: ProjectResponse | null | undefined): boolean {
  return (project?.world_blueprint?.genre_plugin_ids ?? []).some((id) => String(id).trim().toLowerCase() === "game_webnovel");
}

export function stateRows(layer: CharacterStateLayer | undefined): Array<[string, string]> {
  if (!layer?.current) return [];
  return Object.entries(layer.current)
    .map(([key, value]): [string, string] | null => {
      if (PROFILE_STATE_KEYS.has(key)) return null;
      return [stateLabel(key), formatStateValue(value)];
    })
    .filter((entry): entry is [string, string] => Boolean(entry && isReadableLine(entry[1])));
}

export function richProfileEntries(value: Record<string, unknown> | undefined): Array<[string, string]> {
  if (!value) return [];
  const labels: Record<string, string> = {
    class_pressure: "现实压力",
    work_history: "经历习惯",
    equipment_reality: "手头条件",
    desire: "想要什么",
    fear: "怕什么",
    defense: "自我保护",
    bottom_line: "底线",
    gray_zone: "灰度选择",
  };
  return Object.entries(value)
    .map(([key, item]): [string, string] | null => {
      const label = labels[key] ?? key;
      if (Array.isArray(item)) return [label, item.map(String).filter(Boolean).join(" / ")];
      if (item && typeof item === "object") {
        return [
          label,
          Object.entries(item as Record<string, unknown>)
            .map(([innerKey, innerValue]) => `${innerKey}: ${String(innerValue)}`)
            .join("；"),
        ];
      }
      return [label, String(item ?? "")];
    })
    .filter((entry): entry is [string, string] => Boolean(entry && isReadableLine(entry[1])));
}
