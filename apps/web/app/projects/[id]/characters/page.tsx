"use client";

import { useMemo, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import {
  completeFileProjectCharacterPortrait,
  updateFileProjectCharacter,
  type CharacterStateLayer,
  type GamePanel,
  type ImportedRelationshipEdge,
} from "../../../../lib/api";
import { isGameWebnovel, mergeCharacters, stateRows, type DisplayCharacter } from "../../../../lib/worldDisplay";
import { CharacterGroupSection, CharacterSummaryCard, type CharacterGroup } from "../../../../components/ws/CharacterWorkspaceCards";

function characterCardBadge(state: string | undefined): string {
  if (state === "proposed") return "待出场卡";
  if (state === "active") return "确定性角色卡";
  return "记录卡";
}

import { userFacingErrorMessage } from "../../../../lib/user-facing-error";

function cloneCharacter(character: DisplayCharacter): DisplayCharacter {
  return JSON.parse(JSON.stringify(character)) as DisplayCharacter;
}

function characterRoleLabel(role: string | undefined): string {
  const normalized = String(role ?? "").trim().toLowerCase().replaceAll("_", " ");
  const labels: Record<string, string> = {
    protagonist: "主角",
    supporting: "配角",
    recurring: "常驻配角",
    "recurring npc": "常驻配角",
    "stage antagonist": "阶段反派",
    "long term antagonist": "长期反派",
  };
  return labels[normalized] ?? String(role ?? "");
}

type ImportanceGroup = "core" | "major" | "supporting" | "minor" | "unknown";

const IMPORTANCE_LABELS: Record<ImportanceGroup, string> = {
  core: "核心角色",
  major: "重要角色",
  supporting: "配角",
  minor: "次要角色",
  unknown: "其他角色",
};

const NARRATIVE_FUNCTION_LABELS: Record<string, string> = {
  protagonist: "主角",
  ally: "盟友",
  rival: "对手",
  mentor: "导师",
  love_interest: "感情线角色",
  stage_antagonist: "阶段反派",
  long_term_antagonist: "长期反派",
  resource_contact: "资源联系人",
  other: "其他叙事角色",
};

const NARRATIVE_FUNCTION_TOKENS = new Set([
  "protagonist",
  "ally",
  "rival",
  "mentor",
  "love_interest",
  "stage_antagonist",
  "long_term_antagonist",
  "resource_contact",
  "other",
]);

function enumToken(value: unknown): string {
  const token = String(value ?? "").trim().toLowerCase().replaceAll("-", "_").replaceAll(" ", "_");
  const aliases: Record<string, string> = {
    主角: "protagonist",
    核心: "core",
    核心角色: "core",
    重要: "major",
    重要角色: "major",
    配角: "supporting",
    次要: "minor",
    次要角色: "minor",
    盟友: "ally",
    对手: "rival",
    导师: "mentor",
    阶段反派: "stage_antagonist",
    长期反派: "long_term_antagonist",
    资源联系人: "resource_contact",
  };
  return aliases[token] ?? token;
}

function narrativeFunctionOf(character: DisplayCharacter): string {
  const explicitRaw = String(character.narrative_function ?? "").trim();
  if (explicitRaw) {
    const explicit = enumToken(explicitRaw);
    return NARRATIVE_FUNCTION_TOKENS.has(explicit) ? explicit : "other";
  }
  for (const legacyValue of [character.role, character.chapter_role, character.character_tier]) {
    const legacy = enumToken(legacyValue);
    if (NARRATIVE_FUNCTION_TOKENS.has(legacy)) return legacy;
  }
  return "other";
}

function isProtagonist(character: DisplayCharacter): boolean {
  return narrativeFunctionOf(character) === "protagonist";
}

function importanceGroupOf(character: DisplayCharacter): ImportanceGroup {
  const explicit = enumToken(character.importance);
  if (["core", "major", "supporting", "minor"].includes(explicit)) return explicit as ImportanceGroup;
  if (explicit) return "unknown";
  if (isProtagonist(character)) return "core";
  const legacy = enumToken(character.character_tier || character.role);
  if (["core", "major", "supporting", "minor"].includes(legacy)) return legacy as ImportanceGroup;
  if (["stage_antagonist", "mentor", "love_interest"].includes(legacy)) return "major";
  if (legacy === "long_term_antagonist") return "core";
  return "unknown";
}

function matchesCharacterSearch(character: DisplayCharacter, query: string): boolean {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return true;
  const identity = character.identity_profile ?? {};
  return [character.name, identity.current_identity, identity.occupation]
    .some((value) => String(value ?? "").toLocaleLowerCase().includes(needle));
}

function characterFilterLabel(value: string): string {
  return NARRATIVE_FUNCTION_LABELS[value] ?? ({ supporting: "配角", minor: "次要角色", recurring: "常驻配角", recurring_npc: "常驻配角" }[value] || "其他");
}

type StateNamespace = "current_state" | "real_state" | "game_state";

const STATE_TITLES: Record<StateNamespace, string> = {
  current_state: "当前状态",
  real_state: "现实状态",
  game_state: "游戏状态",
};

function stateJson(layer: CharacterStateLayer | undefined): string {
  return JSON.stringify(layer ?? {}, null, 2);
}

function currentStateLayer(value: CharacterStateLayer | string | undefined): CharacterStateLayer | undefined {
  if (typeof value === "string") {
    const summary = value.trim();
    return summary ? { current: { summary }, recent_changes: [] } : undefined;
  }
  return value;
}

const GAME_PANEL_FIELDS: Array<keyof GamePanel> = ["game_id", "level", "class_path", "exp", "hp", "mp", "attributes", "skills", "equipment", "inventory", "currency", "quests", "risk"];

function mirrorGamePanel(panel: GamePanel, layer: CharacterStateLayer): GamePanel {
  const next = { ...panel } as GamePanel & Record<string, unknown>;
  for (const field of GAME_PANEL_FIELDS) {
    if (layer.current && field in layer.current) (next as Record<string, unknown>)[field] = layer.current[field];
  }
  return next;
}

type DisplayRow = [string, string];

type CharacterTemplateKind = "protagonist" | "supporting" | "minor";

type TemplateField = {
  label: string;
  path?: string[];
  list?: boolean;
  number?: boolean;
  relation?: boolean;
};

type TemplateSection = {
  title: string;
  fields: TemplateField[];
};

// Stable-profile templates. Dynamic fields (current_goal, immediate_problem,
// current relations) live in the 当前状态 section, not here, so the workbench
// can clearly separate what the chapter generator is allowed to rewrite from
// the long-term identity of the character.
const CHARACTER_TEMPLATES: Record<CharacterTemplateKind, TemplateSection[]> = {
  protagonist: [
    { title: "基本身份", fields: [
      { label: "年龄", path: ["identity_profile", "age"], number: true },
      { label: "身份", path: ["identity_profile", "current_identity"] },
      { label: "职业", path: ["identity_profile", "occupation"] },
      { label: "出身 / 来历", path: ["identity_profile", "origin"] },
    ] },
    { title: "性格与动机", fields: [
      { label: "性格标签", path: ["personality_portrait", "temperament", "core_traits"], list: true },
      { label: "长期目标", path: ["story_drive", "long_term_goal"] },
      { label: "核心动机", path: ["story_drive", "motivation"] },
      { label: "软肋 / 顾虑", path: ["personality_portrait", "psychology", "fear"] },
      { label: "说话参考", path: ["dialogue_examples"], list: true },
      { label: "表达方式", path: ["performance_profile", "speech_style"] },
    ] },
    { title: "当前剧情", fields: [
      { label: "重要人际关系", relation: true },
      { label: "失败代价", path: ["story_drive", "failure_stakes"] },
      { label: "主要冲突", path: ["story_drive", "main_conflict_reason"] },
      { label: "隐藏信息", path: ["story_drive", "hidden_matters"], list: true },
      { label: "剧情作用", path: ["story_function"] },
    ] },
  ],
  supporting: [
    { title: "基本身份", fields: [
      { label: "身份 / 职业", path: ["identity_profile", "current_identity"] },
      { label: "职业补充", path: ["identity_profile", "occupation"] },
    ] },
    { title: "性格与动机", fields: [
      { label: "性格标签", path: ["personality_portrait", "temperament", "core_traits"], list: true },
      { label: "长期目标", path: ["story_drive", "long_term_goal"] },
      { label: "核心动机", path: ["story_drive", "motivation"] },
      { label: "软肋 / 顾虑", path: ["personality_portrait", "psychology", "fear"] },
      { label: "说话参考", path: ["dialogue_examples"], list: true },
      { label: "表达方式", path: ["performance_profile", "speech_style"] },
    ] },
    { title: "关系与作用", fields: [
      { label: "主要冲突", path: ["story_drive", "main_conflict_reason"] },
      { label: "隐藏信息", path: ["story_drive", "hidden_matters"], list: true },
      { label: "剧情作用", path: ["story_function"] },
    ] },
  ],
  minor: [
    { title: "角色摘要", fields: [
      { label: "身份 / 职业", path: ["identity_profile", "current_identity"] },
      { label: "长期目标", path: ["story_drive", "long_term_goal"] },
      { label: "剧情作用", path: ["story_function"] },
      { label: "表达方式", path: ["performance_profile", "speech_style"] },
    ] },
  ],
};

function characterTemplateKind(character: DisplayCharacter): CharacterTemplateKind {
  const tier = String(character.character_tier || character.role || "").trim().toLowerCase().replaceAll("_", " ");
  if (tier === "protagonist" || tier === "主角") return "protagonist";
  if (["supporting", "recurring", "recurring npc", "stage antagonist", "long term antagonist", "配角", "重要配角"].includes(tier)) return "supporting";
  return "minor";
}

function templateKindLabel(kind: CharacterTemplateKind): string {
  return kind === "protagonist" ? "主角详卡" : kind === "supporting" ? "重要配角卡" : "普通配角卡";
}

function nestedValue(character: DisplayCharacter, path: string[]): string | string[] {
  let value: unknown = character;
  for (const key of path) {
    if (!value || typeof value !== "object") return "";
    value = (value as Record<string, unknown>)[key];
  }
  if (Array.isArray(value)) return value.map(String);
  return value === undefined || value === null ? "" : String(value);
}

function updateNestedValue(character: DisplayCharacter, field: TemplateField, value: string): DisplayCharacter {
  if (!field.path?.length) return character;
  const next = cloneCharacter(character) as DisplayCharacter & Record<string, unknown>;
  let target = next as Record<string, unknown>;
  field.path.slice(0, -1).forEach((key) => {
    const current = target[key];
    target[key] = current && typeof current === "object" && !Array.isArray(current) ? { ...(current as Record<string, unknown>) } : {};
    target = target[key] as Record<string, unknown>;
  });
  target[field.path[field.path.length - 1]] = field.list
    ? value.split("\n").map((line) => line.trim()).filter(Boolean)
    : field.number
      ? (value.trim() ? Number(value) : null)
      : value;
  return next;
}

function relationshipSummary(characterName: string, relations: ImportedRelationshipEdge[]): string {
  const items = relations.flatMap((relation) => {
    if (relation.source !== characterName && relation.target !== characterName) return [];
    const other = relation.source === characterName ? relation.target : relation.source;
    const detail = [relation.relation_type ?? relation.bond, relation.current_state].filter(Boolean).join("，");
    return [`${other}${detail ? `：${detail}` : ""}`];
  });
  return items.join("；");
}

const CURRENT_STATE_FIELD_LABELS: Record<string, string> = {
  location: "当前位置",
  current_location: "当前位置",
  emotion: "当前情绪",
  current_emotion: "当前情绪",
  goals: "当前目标",
  immediate_goal: "当前目标",
  memory: "近期记忆与证据",
  recent_evidence: "近期记忆与证据",
  realm: "修为境界",
  occupation: "营生",
  identity_profile: "身份",
  identity: "身份",
  level: "等级",
  game_id: "角色编号",
  class_path: "职业路径",
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

function structuredStateRows(layer: CharacterStateLayer | undefined): DisplayRow[] {
  return Object.entries(layer?.current ?? {}).flatMap(([key, value]) => {
    // The "当前目标" field is already rendered as a dedicated input in the
    // 当前状态 section, so re-rendering it here would just duplicate the same
    // value (and break the "去重" assertion in the test).
    if (key === "immediate_goal") return [];
    const formatted = stateRows({ current: { [key]: value } })[0];
    return formatted ? [[CURRENT_STATE_FIELD_LABELS[key] ?? formatted[0], formatted[1]]] : [];
  });
}

function recentStateChanges(layer: CharacterStateLayer | undefined): string[] {
  return (layer?.recent_changes ?? [])
    .map((change) => `${change.chapter ? `第 ${change.chapter} 章：` : ""}${change.fact}`)
    .filter(Boolean);
}

// Stable-profile display: identity, background, long-term motivation, and the
// long-running history of each relationship. Chapter generator must NOT touch
// any of this without an explicit user edit.
function StableProfileSection({
  character,
  relations,
  isEditing,
  draft,
  onChangeNested,
  onUpdateRelationField,
  relationsText,
}: {
  character: DisplayCharacter;
  relations: ImportedRelationshipEdge[];
  isEditing: boolean;
  draft: DisplayCharacter | null;
  onChangeNested: (field: TemplateField, value: string) => void;
  onUpdateRelationField: (edge: ImportedRelationshipEdge, key: "history" | "shared_interest_or_conflict", value: string) => void;
  relationsText: string;
}) {
  const shown = isEditing && draft ? draft : character;
  const templateKind = characterTemplateKind(shown as DisplayCharacter);
  const templateSections = CHARACTER_TEMPLATES[templateKind];
  const relatedEdges = relations.filter((edge) => edge.source === shown?.name || edge.target === shown?.name);
  const hasRelations = relatedEdges.length > 0;
  const hasStableTemplate = templateSections.some((section) => section.fields.some((field) => {
    if (isEditing) return true;
    if (field.relation) return Boolean(relationsText.trim());
    const raw = nestedValue(shown as DisplayCharacter, field.path ?? []);
    return Array.isArray(raw) ? raw.length > 0 : Boolean(String(raw).trim());
  }));

  if (!isEditing && !hasRelations && !hasStableTemplate) {
    return null;
  }

  return (
    <section aria-label="稳定档案" className="ws-character-stable">
      <h2>稳定档案</h2>
      <p className="ws-card__hint">不随章节自动改写</p>
      <div className={`ws-character-template ws-character-template--${templateKind}`}>
        {templateSections.map((section) => {
          const fields = section.fields.filter((field) => {
            if (isEditing) return true;
            if (field.relation) return Boolean(relationsText.trim());
            const rawValue = nestedValue(shown as DisplayCharacter, field.path ?? []);
            return (Array.isArray(rawValue) ? rawValue.length > 0 : Boolean(String(rawValue).trim()));
          });
          if (!isEditing && fields.length === 0) return null;
          return (
            <section className="ws-character-template__section" key={section.title}>
              <h3>{section.title}</h3>
              <div className="ws-character-template__fields">
                {fields.map((field) => {
                  if (field.relation) {
                    return isEditing ? (
                      <div className="ws-character-template__field" key={field.label}>
                        <span>{field.label}</span>
                        <p className="is-empty">关系通过项目设置维护。</p>
                      </div>
                    ) : (
                      <div className="ws-character-template__field" key={field.label}>
                        <span>{field.label}</span>
                        <p className={relationsText ? "" : "is-empty"}>{relationsText || "待补充"}</p>
                      </div>
                    );
                  }
                  const rawValue = nestedValue(shown as DisplayCharacter, field.path ?? []);
                  const text = Array.isArray(rawValue) ? rawValue.join(isEditing ? "\n" : "；") : rawValue;
                  const displayValue = field.number && text ? `${text}${field.label.includes("年龄") ? "岁" : "章"}` : text;
                  return isEditing && field.path ? (
                    <label className="ws-character-template__field" key={field.label}>
                      <span>{field.label}</span>
                      {field.number ? (
                        <input aria-label={field.label} type="number" min={0} value={text} onChange={(event) => onChangeNested(field, event.target.value)} />
                      ) : (
                        <textarea aria-label={field.label} rows={field.list ? 3 : 2} value={text} onChange={(event) => onChangeNested(field, event.target.value)} />
                      )}
                    </label>
                  ) : (
                    <div className="ws-character-template__field" key={field.label}>
                      <span>{field.label}</span>
                      <p className={displayValue ? "" : "is-empty"}>{displayValue || "待补充"}</p>
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
      {hasRelations ? (
        <section className="ws-character-template__section">
          <h4>关系背景</h4>
          <ul>
            {relatedEdges.map((edge) => {
              const other = edge.source === shown?.name ? edge.target : edge.source;
              const history = edge.history;
              const shared = edge.shared_interest_or_conflict;
              if (!isEditing && !history && !shared) return null;
              return (
                <li key={edge.id ?? `${edge.source}-${edge.target}`}>
                  <p><strong>{other}</strong>{edge.relation_type ? ` · ${edge.relation_type}` : ""}</p>
                  {isEditing ? (
                    <>
                      <label><span>历史</span><textarea aria-label={`${other} 历史`} rows={2} value={history ?? ""} onChange={(event) => onUpdateRelationField(edge, "history", event.target.value)} /></label>
                      <label><span>利害</span><textarea aria-label={`${other} 利害`} rows={2} value={shared ?? ""} onChange={(event) => onUpdateRelationField(edge, "shared_interest_or_conflict", event.target.value)} /></label>
                    </>
                  ) : (
                    <>
                      {history ? <p>{history}</p> : null}
                      {shared ? <p>{shared}</p> : null}
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
    </section>
  );
}

// 当前状态 section: everything that the chapter generator may rewrite after
// each chapter — current trouble, current goal, residence, livelihood, the
// state-layer JSON, and the live relationship state.
function CurrentStateSection({
  shown,
  gameStory,
  isEditing,
  draft,
  stateLayers,
  stateDrafts,
  relations,
  onStateDraftChange,
  onChangeNested,
}: {
  shown: DisplayCharacter | null;
  gameStory: boolean;
  isEditing: boolean;
  draft: DisplayCharacter | null;
  stateLayers: Array<[StateNamespace, CharacterStateLayer]>;
  stateDrafts: Partial<Record<StateNamespace, string>>;
  relations: ImportedRelationshipEdge[];
  onStateDraftChange: (namespace: StateNamespace, value: string) => void;
  onChangeNested: (field: TemplateField, value: string) => void;
}) {
  if (!shown) return null;
  const life = (shown.current_life_profile ?? {}) as Record<string, unknown>;
  const lifeEntries: Array<[string, string]> = [];
  if (life.residence) lifeEntries.push(["当前居住", String(life.residence)]);
  if (life.livelihood) lifeEntries.push(["营生", String(life.livelihood)]);
  if (life.economic_state) lifeEntries.push(["经济", String(life.economic_state)]);
  if (life.resources_and_ability) lifeEntries.push(["技能", String(life.resources_and_ability)]);
  if (life.authority_scope) lifeEntries.push(["权限", String(life.authority_scope)]);
  const dynamicRelations = relations.filter((edge) => edge.source === shown.name || edge.target === shown.name);

  const goalField: TemplateField = { label: "当前目标", path: ["story_drive", "immediate_goal"] };
  const troubleField: TemplateField = { label: "眼前麻烦", path: ["current_life_profile", "immediate_problem"] };
  const goalValue = nestedValue(shown, goalField.path ?? []);
  const troubleValue = nestedValue(shown, troubleField.path ?? []);

  return (
    <section aria-label="当前状态" className="ws-character-current">
      <h2>当前状态</h2>
      <p className="ws-card__hint">章后只更新出场证据和明确状态事件</p>
      <div className="ws-character-template__fields">
        <div className="ws-character-template__field">
          <span>眼前麻烦</span>
          {isEditing ? (
            <textarea
              aria-label="眼前麻烦"
              rows={2}
              value={Array.isArray(troubleValue) ? troubleValue.join("\n") : String(troubleValue ?? "")}
              onChange={(event) => draft && onChangeNested(troubleField, event.target.value)}
            />
          ) : (
            <p className={troubleValue ? "" : "is-empty"}>{troubleValue || "待补充"}</p>
          )}
        </div>
        <div className="ws-character-template__field">
          <span>当前目标</span>
          {isEditing ? (
            <textarea
              aria-label="当前目标"
              rows={2}
              value={Array.isArray(goalValue) ? goalValue.join("\n") : String(goalValue ?? "")}
              onChange={(event) => draft && onChangeNested(goalField, event.target.value)}
            />
          ) : (
            <p className={goalValue ? "" : "is-empty"}>{goalValue || "待补充"}</p>
          )}
        </div>
      </div>
      {lifeEntries.length > 0 ? (
        <dl className="ws-panel-grid">
          {lifeEntries.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
        </dl>
      ) : null}
      {stateLayers.length > 0 ? (
        <div className="ws-character-state-layers">
          {stateLayers.map(([namespace, layer]) => {
            const showLayerHeading = STATE_TITLES[namespace] !== "当前状态";
            return isEditing ? (
              <section key={namespace} aria-label={STATE_TITLES[namespace]}>
                {showLayerHeading ? <h4>{STATE_TITLES[namespace]}</h4> : null}
                <label><span>{STATE_TITLES[namespace]} JSON</span><textarea aria-label={`${STATE_TITLES[namespace]} JSON`} rows={8} value={stateDrafts[namespace] ?? stateJson(layer)} onChange={(event) => onStateDraftChange(namespace, event.target.value)} /></label>
              </section>
            ) : (
              <section key={namespace} aria-label={STATE_TITLES[namespace]}>
                {showLayerHeading ? <h4>{STATE_TITLES[namespace]}</h4> : null}
                <dl className="ws-panel-grid">{structuredStateRows(layer).map(([label, value]) => <div key={`${namespace}-${label}`}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
                {recentStateChanges(layer).map((change) => <p key={`${namespace}-${change}`}>{change}</p>)}
              </section>
            );
          })}
        </div>
      ) : null}
      {dynamicRelations.length > 0 ? (
        <section className="ws-character-template__section">
          <h4>关系动态</h4>
          <ul>
            {dynamicRelations.map((edge) => {
              const other = edge.source === shown.name ? edge.target : edge.source;
              const hasContent = edge.current_state || (edge.changes ?? []).some((change) => change.summary);
              if (!hasContent) return null;
              return (
                <li key={edge.id ?? `${edge.source}-${edge.target}`}>
                  <p><strong>{other}</strong>{edge.relation_type ? ` · ${edge.relation_type}` : ""}</p>
                  {edge.current_state ? <p>{edge.current_state}</p> : null}
                  {(edge.changes ?? []).map((change, idx) => change.summary ? (
                    <p key={`change-${idx}`}>{change.summary}</p>
                  ) : null)}
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
      {gameStory ? null : null}
    </section>
  );
}

export default function CharactersPage() {
  const { project, story, error, encodedProjectId, projectId, refresh } = useProjectWorkspace();
  const characters = mergeCharacters(project?.character_profiles, story?.characters);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [draft, setDraft] = useState<DisplayCharacter | null>(null);
  const [stateDrafts, setStateDrafts] = useState<Partial<Record<StateNamespace, string>>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [importanceFilter, setImportanceFilter] = useState<ImportanceGroup | "all">("all");
  const [narrativeFunctionFilter, setNarrativeFunctionFilter] = useState("all");
  const [expandedNames, setExpandedNames] = useState<Set<string>>(new Set());

  const filteredCharacters = useMemo(() => characters.filter((character) => (
    matchesCharacterSearch(character, searchQuery)
    && (importanceFilter === "all" || importanceGroupOf(character) === importanceFilter)
    && (narrativeFunctionFilter === "all" || narrativeFunctionOf(character) === narrativeFunctionFilter)
  )), [characters, importanceFilter, narrativeFunctionFilter, searchQuery]);

  const characterGroups = useMemo<CharacterGroup[]>(() => {
    const protagonist = filteredCharacters.filter(isProtagonist);
    const grouped: CharacterGroup[] = protagonist.length > 0
      ? [{ key: "protagonist", title: "主角", characters: protagonist, protagonist: true }]
      : [];
    (['core', 'major', 'supporting', 'minor', 'unknown'] as ImportanceGroup[]).forEach((key) => {
      const groupCharacters = filteredCharacters.filter((character) => !isProtagonist(character) && importanceGroupOf(character) === key);
      if (groupCharacters.length > 0) grouped.push({ key, title: IMPORTANCE_LABELS[key], characters: groupCharacters });
    });
    return grouped;
  }, [filteredCharacters]);

  const beginEdit = (character: DisplayCharacter) => {
    const gameStory = isGameWebnovel(project);
    setEditingName(character.name);
    setDraft(cloneCharacter(character));
    const genericState = currentStateLayer(character.current_state) ?? character.real_state;
    setStateDrafts(gameStory ? {
      ...(character.real_state ? { real_state: stateJson(character.real_state) } : {}),
      ...((character.game_state || character.game_panel) ? { game_state: stateJson(character.game_state ?? { current: character.game_panel }) } : {}),
    } : {
      current_state: stateJson(genericState ?? { current: {}, recent_changes: [] }),
    });
    setMessage(null);
  };

  const save = async () => {
    if (!draft || !editingName) return;
    const statePatch: Partial<Record<StateNamespace, CharacterStateLayer>> = {};
    const namespaces: StateNamespace[] = isGameWebnovel(project)
      ? ["real_state", "game_state"]
      : ["current_state"];
    for (const namespace of namespaces) {
      const raw = stateDrafts[namespace];
      if (raw === undefined) continue;
      try {
        const parsed: unknown = JSON.parse(raw);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("object_required");
        statePatch[namespace] = parsed as CharacterStateLayer;
      } catch {
        setMessage(`${STATE_TITLES[namespace]} JSON 格式错误，请输入对象。`);
        return;
      }
    }
    setBusy(editingName);
    setMessage(null);
    try {
      await updateFileProjectCharacter(projectId, editingName, {
        character_tier: draft.character_tier,
        first_appearance: draft.first_appearance,
        identity_profile: draft.identity_profile,
        background_profile: draft.background_profile,
        current_life_profile: draft.current_life_profile,
        story_drive: draft.story_drive,
        dialogue_examples: draft.dialogue_examples,
        performance_profile: draft.performance_profile,
        personality_portrait: draft.personality_portrait,
        story_function: draft.story_function,
        ...statePatch,
        ...(statePatch.game_state && draft.game_panel ? { game_panel: mirrorGamePanel(draft.game_panel, statePatch.game_state) } : {}),
      });
      setEditingName(null);
      setDraft(null);
      setStateDrafts({});
      setMessage("角色卡已保存。");
      void refresh().catch(() => undefined);
    } catch (saveError) {
      setMessage(`保存失败：${saveError instanceof Error ? saveError.message : String(saveError)}`);
    } finally {
      setBusy(null);
    }
  };

  const complete = async (character: DisplayCharacter) => {
    setBusy(character.name);
    setMessage(null);
    try {
      await completeFileProjectCharacterPortrait(projectId, character.name);
      setMessage(`${character.name} 的基础侧写已补全。`);
      void refresh().catch(() => undefined);
    } catch (completeError) {
      setMessage(`补全失败：${completeError instanceof Error ? completeError.message : String(completeError)}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[{ label: "我的作品", href: "/projects" }, { label: project?.title || "作品", href: `/projects/${encodedProjectId}` }]}
        title="角色卡"
        subtitle="只显示正文需要的关键信息。"
      />
      {error ? <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}><p className="ws-error-text">加载失败：{userFacingErrorMessage(error)}</p></div> : null}
      {message ? <p className="ws-inline-message">{message}</p> : null}

      <section className="ws-character-workspace" aria-labelledby="character-workspace-title">
        <div className="ws-section-head">
          <h2 className="ws-character-workspace__title" id="character-workspace-title">人物档案</h2>
        </div>
        {characters.length > 0 ? (
          <>
            <div className="ws-character-filters" aria-label="人物筛选">
              <label>
                <span>搜索人物</span>
                <input aria-label="搜索人物" type="search" placeholder="姓名、身份或职业" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} />
              </label>
              <label>
                <span>角色分类</span>
                <select aria-label="角色分类" value={importanceFilter} onChange={(event) => setImportanceFilter(event.target.value as ImportanceGroup | "all")}>
                  <option value="all">全部分类</option>
                  {(Object.keys(IMPORTANCE_LABELS) as ImportanceGroup[]).filter((key) => key !== "unknown").map((key) => <option key={key} value={key}>{IMPORTANCE_LABELS[key]}</option>)}
                  <option value="unknown">其他角色</option>
                </select>
              </label>
              <label>
                <span>叙事功能</span>
                <select aria-label="叙事功能" value={narrativeFunctionFilter} onChange={(event) => setNarrativeFunctionFilter(event.target.value)}>
                  <option value="all">全部功能</option>
                  {Array.from(new Set(characters.map(narrativeFunctionOf).filter(Boolean))).sort().map((value) => <option key={value} value={value}>{characterFilterLabel(value)}</option>)}
                </select>
              </label>
            </div>
            {characterGroups.length > 0 ? characterGroups.map((group) => (
              <CharacterGroupSection key={group.key} group={group}>
                {group.characters.map((character) => {
              const gameStory = isGameWebnovel(project);
              const isEditing = editingName === character.name && draft;
              const shown = isEditing ? draft : character;
              const isHero = group.key === "protagonist";
              const showDetails = isHero || Boolean(isEditing) || expandedNames.has(character.name);
              const effectiveGameState = shown?.game_state ?? (shown?.game_panel ? { current: shown.game_panel } : undefined);
              const showGameState = gameStory && Boolean(effectiveGameState);
              const panel = showGameState && !shown?.game_state ? shown?.game_panel : undefined;
              const displayedGameId = showGameState
                ? effectiveGameState?.current?.game_id ?? shown?.game_id ?? panel?.game_id
                : undefined;
              const graphRelations = (project?.relationship_graph ?? []).filter(
                (relation) => relation.source === shown?.name || relation.target === shown?.name,
              );
              const relationsText = relationshipSummary(shown?.name ?? "", graphRelations);
              const genericState = currentStateLayer(shown?.current_state) ?? shown?.real_state;
              const stateLayers = (gameStory ? [
                ["real_state", shown?.real_state],
                ["game_state", showGameState ? effectiveGameState : undefined],
              ] : [
                ["current_state", genericState],
              ] as Array<[StateNamespace, CharacterStateLayer | undefined]>).filter((entry): entry is [StateNamespace, CharacterStateLayer] => Boolean(entry[1]));

              if (!showDetails) {
                return <CharacterSummaryCard key={character.name} character={character} importanceLabel={IMPORTANCE_LABELS[importanceGroupOf(character)]} narrativeLabel={characterFilterLabel(narrativeFunctionOf(character))} expanded={false} busy={busy === character.name} onToggle={() => setExpandedNames((current) => new Set(current).add(character.name))} onEdit={() => beginEdit(character)} onComplete={() => void complete(character)} />;
              }

              return (
                <article className={`ws-character-card${isHero ? " ws-character-card--hero" : ""}`} data-testid={`character-card-${characterTemplateKind(shown as DisplayCharacter)}`} key={character.name}>
                  <div className="ws-character-card__head">
                    <div><h2>{shown?.name}</h2><p>{[IMPORTANCE_LABELS[importanceGroupOf(character)], characterFilterLabel(narrativeFunctionOf(character)), displayedGameId].filter(Boolean).join(" / ")}</p></div>
                    <div className="ws-character-card__actions">
                      <span>{characterCardBadge(shown?.lifecycle_state)}{panel?.updated_chapter ? ` · 第 ${panel.updated_chapter} 章更新` : ""}</span>
                      {isEditing ? (
                        <><button type="button" className="ws-button ws-button--primary" disabled={busy === character.name} onClick={save}>保存角色卡</button><button type="button" className="ws-button" disabled={busy === character.name} onClick={() => { setEditingName(null); setDraft(null); setStateDrafts({}); }}>取消</button></>
                      ) : (
                        <><button type="button" className="ws-button" onClick={() => beginEdit(character)} title="编辑人物侧写">编辑</button><button type="button" className="ws-button" disabled={busy === character.name} onClick={() => complete(character)} title="用本地规则补全空白侧写">补全基础侧写</button></>
                      )}
                    </div>
                  </div>
                  {isHero ? <dl className="ws-character-hero-facts">
                    {shown?.identity_profile?.current_identity ? <div><dt>当前身份</dt><dd>{shown.identity_profile.current_identity}</dd></div> : null}
                    {shown?.story_drive?.immediate_goal ? <div><dt>当前目标</dt><dd>{shown.story_drive.immediate_goal}</dd></div> : null}
                    {shown?.current_life_profile?.immediate_problem ? <div><dt>状态摘要</dt><dd>{shown.current_life_profile.immediate_problem}</dd></div> : null}
                    {shown?.profile_status ? <div><dt>侧写状态</dt><dd>{shown.profile_status === "ready" ? "已就绪" : shown.profile_status === "stub" ? "待补全" : "待确认"}</dd></div> : null}
                    {typeof shown?.profile_completeness === "number" ? <div><dt>侧写完整度</dt><dd>{Math.round(shown.profile_completeness <= 1 ? shown.profile_completeness * 100 : shown.profile_completeness)}%</dd></div> : null}
                  </dl> : null}
                  <StableProfileSection
                    character={character}
                    relations={graphRelations}
                    isEditing={Boolean(isEditing)}
                    draft={isEditing ? draft : null}
                    onChangeNested={(field, value) => draft && setDraft(updateNestedValue(draft, field, value))}
                    onUpdateRelationField={() => {
                      // Relationship graph is edited via the project API, not per-character.
                      // For the workbench this is read-only.
                    }}
                    relationsText={relationsText}
                  />
                  <CurrentStateSection
                    shown={shown}
                    gameStory={gameStory}
                    isEditing={Boolean(isEditing)}
                    draft={isEditing ? draft : null}
                    stateLayers={stateLayers}
                    stateDrafts={stateDrafts}
                    relations={graphRelations}
                    onStateDraftChange={(namespace, value) => setStateDrafts((current) => ({ ...current, [namespace]: value }))}
                    onChangeNested={(field, value) => draft && setDraft(updateNestedValue(draft, field, value))}
                  />
                  {!isHero && !isEditing ? <button type="button" className="ws-character-summary-card__toggle" aria-expanded="true" onClick={() => setExpandedNames((current) => { const next = new Set(current); next.delete(character.name); return next; })}>收起详情</button> : null}
                </article>
              );
                })}
              </CharacterGroupSection>
            )) : <p className="ws-card__hint">没有符合当前搜索或筛选条件的人物。</p>}
          </>
        ) : <p className="ws-card__hint">暂无角色档案。</p>}
      </section>
    </div>
  );
}
