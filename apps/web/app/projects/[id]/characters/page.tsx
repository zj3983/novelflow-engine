"use client";

import { useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import {
  completeFileProjectCharacterPortrait,
  updateFileProjectCharacter,
  type CharacterImportance,
  type CharacterNarrativeFunction,
  type CharacterProfileStatus,
  type CharacterStateLayer,
  type GamePanel,
  type ImportedRelationshipEdge,
} from "../../../../lib/api";
import { isGameWebnovel, mergeCharacters, stateRows, type DisplayCharacter } from "../../../../lib/worldDisplay";

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

type CharacterFilter = "all" | CharacterImportance | CharacterProfileStatus;
type NarrativeFunctionFilter = "all" | CharacterNarrativeFunction;

const IMPORTANCE_LABELS: Record<CharacterImportance, string> = {
  core: "核心",
  major: "重要",
  supporting: "配角",
  minor: "次要",
};

const NARRATIVE_FUNCTION_LABELS: Record<CharacterNarrativeFunction, string> = {
  protagonist: "主角",
  ally: "盟友",
  rival: "竞争者",
  mentor: "导师",
  love_interest: "感情线",
  stage_antagonist: "阶段反派",
  long_term_antagonist: "长期反派",
  resource_contact: "资源联系人",
  other: "其他",
};

const PROFILE_STATUS_LABELS: Record<CharacterProfileStatus, string> = {
  stub: "待补全",
  ready: "已就绪",
};

const LEGACY_TAXONOMY: Record<string, { importance: CharacterImportance; narrativeFunction: CharacterNarrativeFunction }> = {
  protagonist: { importance: "core", narrativeFunction: "protagonist" },
  主角: { importance: "core", narrativeFunction: "protagonist" },
  stage_antagonist: { importance: "major", narrativeFunction: "stage_antagonist" },
  "stage antagonist": { importance: "major", narrativeFunction: "stage_antagonist" },
  阶段反派: { importance: "major", narrativeFunction: "stage_antagonist" },
  long_term_antagonist: { importance: "core", narrativeFunction: "long_term_antagonist" },
  "long term antagonist": { importance: "core", narrativeFunction: "long_term_antagonist" },
  长期反派: { importance: "core", narrativeFunction: "long_term_antagonist" },
  supporting: { importance: "supporting", narrativeFunction: "other" },
  配角: { importance: "supporting", narrativeFunction: "other" },
  recurring: { importance: "supporting", narrativeFunction: "other" },
  "recurring npc": { importance: "supporting", narrativeFunction: "other" },
};

function taxonomyToken(value: unknown): string {
  return String(value ?? "").trim().toLowerCase().replaceAll("-", "_").replaceAll(" ", "_");
}

function characterTaxonomy(character: DisplayCharacter): {
  importance?: CharacterImportance;
  narrativeFunction?: CharacterNarrativeFunction;
  status?: CharacterProfileStatus;
} {
  const legacyKey = taxonomyToken(character.character_tier || character.role).replaceAll("_", " ");
  const legacy = LEGACY_TAXONOMY[legacyKey] ?? LEGACY_TAXONOMY[taxonomyToken(character.character_tier || character.role)];
  const importance = IMPORTANCE_LABELS[character.importance as CharacterImportance]
    ? character.importance
    : legacy?.importance;
  const narrativeFunction = NARRATIVE_FUNCTION_LABELS[character.narrative_function as CharacterNarrativeFunction]
    ? character.narrative_function
    : legacy?.narrativeFunction;
  const status = character.profile_status === "stub" || character.profile_status === "ready"
    ? character.profile_status
    : undefined;
  return { importance, narrativeFunction, status };
}

function importanceLabel(value: CharacterImportance | undefined): string {
  return value ? `${IMPORTANCE_LABELS[value] ?? value} · ${value}` : "未标注分类";
}

function narrativeFunctionLabel(value: CharacterNarrativeFunction | undefined): string {
  return value ? `${NARRATIVE_FUNCTION_LABELS[value] ?? value} · ${value}` : "未标注功能";
}

function profileStatusLabel(value: CharacterProfileStatus | undefined): string {
  return value ? `${PROFILE_STATUS_LABELS[value]} · ${value}` : "未标注状态";
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

// This is a stable form/layout choice kept for existing test ids. It is not
// the character's narrative function; those two dimensions are rendered and
// selected independently below.
type CharacterFormKind =
  | "protagonist"
  | "stage_antagonist"
  | "long_term_antagonist"
  | "supporting"
  | "minor";

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
const CHARACTER_TEMPLATES: Record<CharacterFormKind, TemplateSection[]> = {
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
      { label: "说话方式", path: ["performance_profile", "speech_style"] },
      { label: "行动方式", path: ["performance_profile", "action_style"] },
      { label: "说话参考", path: ["dialogue_examples"], list: true },
    ] },
    { title: "当前剧情", fields: [
      { label: "重要人际关系", relation: true },
      { label: "失败代价", path: ["story_drive", "failure_stakes"] },
      { label: "主要冲突", path: ["story_drive", "main_conflict_reason"] },
      { label: "隐藏信息", path: ["story_drive", "hidden_matters"], list: true },
      { label: "剧情作用", path: ["story_function"] },
    ] },
  ],
  stage_antagonist: [
    { title: "基本身份", fields: [
      { label: "身份", path: ["identity_profile", "current_identity"] },
      { label: "职业", path: ["identity_profile", "occupation"] },
      { label: "出身 / 来历", path: ["identity_profile", "origin"] },
    ] },
    { title: "权限与当前压力", fields: [
      { label: "权限范围", path: ["current_life_profile", "authority_scope"] },
      { label: "眼前麻烦", path: ["current_life_profile", "immediate_problem"] },
    ] },
    { title: "性格与动机", fields: [
      { label: "性格标签", path: ["personality_portrait", "temperament", "core_traits"], list: true },
      { label: "长期目标", path: ["story_drive", "long_term_goal"] },
      { label: "核心动机", path: ["story_drive", "motivation"] },
      { label: "主要冲突", path: ["story_drive", "main_conflict_reason"] },
      { label: "失败代价", path: ["story_drive", "failure_stakes"] },
      { label: "说话方式", path: ["performance_profile", "speech_style"] },
      { label: "行动方式", path: ["performance_profile", "action_style"] },
      { label: "说话参考", path: ["dialogue_examples"], list: true },
    ] },
    { title: "关系与作用", fields: [
      { label: "隐藏信息", path: ["story_drive", "hidden_matters"], list: true },
      { label: "剧情作用", path: ["story_function"] },
      { label: "重要人际关系", relation: true },
    ] },
  ],
  long_term_antagonist: [
    { title: "基本身份", fields: [
      { label: "身份", path: ["identity_profile", "current_identity"] },
      { label: "职业", path: ["identity_profile", "occupation"] },
      { label: "出身 / 来历", path: ["identity_profile", "origin"] },
    ] },
    { title: "权限与幕后目标", fields: [
      { label: "权限范围", path: ["current_life_profile", "authority_scope"] },
      { label: "眼前麻烦", path: ["current_life_profile", "immediate_problem"] },
      { label: "长期目标", path: ["story_drive", "long_term_goal"] },
    ] },
    { title: "性格与动机", fields: [
      { label: "核心动机", path: ["story_drive", "motivation"] },
      { label: "主要冲突", path: ["story_drive", "main_conflict_reason"] },
      { label: "失败代价", path: ["story_drive", "failure_stakes"] },
      { label: "隐藏信息", path: ["story_drive", "hidden_matters"], list: true },
      { label: "说话方式", path: ["performance_profile", "speech_style"] },
      { label: "行动方式", path: ["performance_profile", "action_style"] },
      { label: "说话参考", path: ["dialogue_examples"], list: true },
    ] },
    { title: "关系与作用", fields: [
      { label: "剧情作用", path: ["story_function"] },
      { label: "重要人际关系", relation: true },
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
      { label: "说话方式", path: ["performance_profile", "speech_style"] },
      { label: "行动方式", path: ["performance_profile", "action_style"] },
      { label: "说话参考", path: ["dialogue_examples"], list: true },
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
      { label: "说话方式", path: ["performance_profile", "speech_style"] },
      { label: "行动方式", path: ["performance_profile", "action_style"] },
    ] },
  ],
};

function characterFormKind(character: DisplayCharacter): CharacterFormKind {
  const taxonomy = characterTaxonomy(character);
  if (taxonomy.narrativeFunction === "protagonist") return "protagonist";
  if (taxonomy.narrativeFunction === "stage_antagonist") return "stage_antagonist";
  if (taxonomy.narrativeFunction === "long_term_antagonist") return "long_term_antagonist";
  if (taxonomy.importance === "core" || taxonomy.importance === "major" || taxonomy.importance === "supporting") {
    return "supporting";
  }
  const tier = String(character.character_tier || character.role || "").trim().toLowerCase().replaceAll("_", " ");
  if (tier === "protagonist" || tier === "主角") return "protagonist";
  if (["supporting", "recurring", "recurring npc", "stage antagonist", "long term antagonist", "配角", "重要配角"].includes(tier)) return "supporting";
  return "minor";
}

type CharacterProfileDepth = "stub" | "light" | "full";

function characterProfileDepth(character: DisplayCharacter): CharacterProfileDepth {
  const taxonomy = characterTaxonomy(character);
  if (taxonomy.status === "stub") return "stub";
  if (taxonomy.importance === "core" || taxonomy.importance === "major") return "full";
  return "light";
}

function characterTemplateLabel(character: DisplayCharacter): string {
  const taxonomy = characterTaxonomy(character);
  const depth = characterProfileDepth(character);
  const functionLabel = taxonomy.narrativeFunction
    ? NARRATIVE_FUNCTION_LABELS[taxonomy.narrativeFunction]
    : undefined;
  if (functionLabel && taxonomy.narrativeFunction !== "other") {
    return `${functionLabel}${depth === "stub" ? "待补全卡" : depth === "full" ? "完整模板" : "轻量模板"}`;
  }
  if (depth === "stub") return "普通角色待补全卡";
  if (depth === "full") return `${importanceLabel(taxonomy.importance)}完整模板`;
  return "普通角色轻量模板";
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

function TaxonomyEditor({
  character,
  onChange,
}: {
  character: DisplayCharacter;
  onChange: (field: "importance" | "narrative_function", value: string) => void;
}) {
  const taxonomy = characterTaxonomy(character);
  return (
    <div className="ws-character-taxonomy-editor">
      <label>
        <span>重要级别</span>
        <select
          aria-label="重要级别"
          value={taxonomy.importance ?? ""}
          onChange={(event) => onChange("importance", event.target.value)}
        >
          <option value="">未标注</option>
          {(Object.keys(IMPORTANCE_LABELS) as CharacterImportance[]).map((value) => (
            <option key={value} value={value}>{importanceLabel(value)}</option>
          ))}
        </select>
      </label>
      <label>
        <span>叙事功能</span>
        <select
          aria-label="叙事功能"
          value={taxonomy.narrativeFunction ?? ""}
          onChange={(event) => onChange("narrative_function", event.target.value)}
        >
          <option value="">未标注</option>
          {(Object.keys(NARRATIVE_FUNCTION_LABELS) as CharacterNarrativeFunction[]).map((value) => (
            <option key={value} value={value}>{narrativeFunctionLabel(value)}</option>
          ))}
        </select>
      </label>
      <p className="ws-character-taxonomy-editor__hint">状态与完成度由档案内容自动计算，保存时不会覆盖。</p>
    </div>
  );
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
  onChangeTaxonomy,
  onUpdateRelationField,
  relationsText,
}: {
  character: DisplayCharacter;
  relations: ImportedRelationshipEdge[];
  isEditing: boolean;
  draft: DisplayCharacter | null;
  onChangeNested: (field: TemplateField, value: string) => void;
  onChangeTaxonomy: (field: "importance" | "narrative_function", value: string) => void;
  onUpdateRelationField: (edge: ImportedRelationshipEdge, key: "history" | "shared_interest_or_conflict", value: string) => void;
  relationsText: string;
}) {
  const shown = isEditing && draft ? draft : character;
  const formKind = characterFormKind(shown as DisplayCharacter);
  const templateSections = CHARACTER_TEMPLATES[formKind];
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
      {isEditing ? <TaxonomyEditor character={shown} onChange={onChangeTaxonomy} /> : null}
      <div className={`ws-character-template ws-character-template--${formKind}`}>
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
  const [characterFilter, setCharacterFilter] = useState<CharacterFilter>("all");
  const [narrativeFunctionFilter, setNarrativeFunctionFilter] = useState<NarrativeFunctionFilter>("all");
  const [editingName, setEditingName] = useState<string | null>(null);
  const [draft, setDraft] = useState<DisplayCharacter | null>(null);
  const [stateDrafts, setStateDrafts] = useState<Partial<Record<StateNamespace, string>>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const visibleCharacters = characters.filter((character) => {
    const taxonomy = characterTaxonomy(character);
    const matchesPrimary = characterFilter === "all"
      || taxonomy.importance === characterFilter
      || taxonomy.status === characterFilter;
    const matchesFunction = narrativeFunctionFilter === "all"
      || taxonomy.narrativeFunction === narrativeFunctionFilter;
    return matchesPrimary && matchesFunction;
  });

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
        importance: draft.importance,
        narrative_function: draft.narrative_function,
        first_appearance: draft.first_appearance,
        identity_profile: draft.identity_profile,
        background_profile: draft.background_profile,
        current_life_profile: draft.current_life_profile,
        story_drive: draft.story_drive,
        performance_profile: draft.performance_profile,
        dialogue_examples: draft.dialogue_examples,
        personality_portrait: draft.personality_portrait,
        story_function: draft.story_function,
        ...statePatch,
        ...(statePatch.game_state && draft.game_panel ? { game_panel: mirrorGamePanel(draft.game_panel, statePatch.game_state) } : {}),
      });
      setEditingName(null);
      setDraft(null);
      setStateDrafts({});
      setMessage("角色卡已保存。");
      await refresh();
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
      await refresh();
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
        <div className="ws-character-filters" aria-label="角色筛选">
          <label>
            <span>角色分类</span>
            <select
              aria-label="角色分类筛选"
              value={characterFilter}
              onChange={(event) => setCharacterFilter(event.target.value as CharacterFilter)}
            >
              <option value="all">全部</option>
              <option value="core">核心角色 · core</option>
              <option value="major">重要角色 · major</option>
              <option value="supporting">配角 · supporting</option>
              <option value="minor">次要角色 · minor</option>
              <option value="stub">待补全 · stub</option>
              <option value="ready">已就绪 · ready</option>
            </select>
          </label>
          <label>
            <span>叙事功能</span>
            <select
              aria-label="叙事功能筛选"
              value={narrativeFunctionFilter}
              onChange={(event) => setNarrativeFunctionFilter(event.target.value as NarrativeFunctionFilter)}
            >
              <option value="all">全部功能</option>
              <option value="protagonist">主角 · protagonist</option>
              <option value="stage_antagonist">阶段反派 · stage_antagonist</option>
              <option value="long_term_antagonist">长期反派 · long_term_antagonist</option>
              <option value="ally">盟友 · ally</option>
              <option value="rival">竞争者 · rival</option>
              <option value="mentor">导师 · mentor</option>
              <option value="love_interest">感情线 · love_interest</option>
              <option value="resource_contact">资源联系人 · resource_contact</option>
              <option value="other">其他 · other</option>
            </select>
          </label>
          <p role="status">显示 {visibleCharacters.length} / {characters.length} 张角色卡</p>
        </div>
        {visibleCharacters.length > 0 ? (
          <div className="ws-character-list">
            {visibleCharacters.map((character) => {
              const gameStory = isGameWebnovel(project);
              const isEditing = editingName === character.name && draft;
              const shown = isEditing ? draft : character;
              const taxonomy = characterTaxonomy(shown as DisplayCharacter);
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

              return (
                <article className="ws-character-card" data-testid={`character-card-${characterFormKind(shown as DisplayCharacter)}`} key={character.name}>
                  <div className="ws-character-card__head">
                    <div>
                      <h2>{shown?.name}</h2>
                      <p>{[characterTemplateLabel(shown as DisplayCharacter), characterRoleLabel(shown?.role), displayedGameId].filter(Boolean).join(" / ")}</p>
                      <div className="ws-character-taxonomy" aria-label="角色分类信息">
                        <span className="ws-character-taxonomy__badge">{importanceLabel(taxonomy.importance)}</span>
                        <span className="ws-character-taxonomy__badge">{narrativeFunctionLabel(taxonomy.narrativeFunction)}</span>
                        <span className="ws-character-taxonomy__badge">{profileStatusLabel(taxonomy.status)}</span>
                        {shown?.profile_completeness !== undefined && shown?.profile_completeness !== null ? (
                          <span className="ws-character-taxonomy__badge">完成度 · {shown.profile_completeness}%</span>
                        ) : null}
                      </div>
                    </div>
                    <div className="ws-character-card__actions">
                      <span>{characterCardBadge(shown?.lifecycle_state)}{panel?.updated_chapter ? ` · 第 ${panel.updated_chapter} 章更新` : ""}</span>
                      {isEditing ? (
                        <><button type="button" className="ws-button ws-button--primary" disabled={busy === character.name} onClick={save}>保存角色卡</button><button type="button" className="ws-button" disabled={busy === character.name} onClick={() => { setEditingName(null); setDraft(null); setStateDrafts({}); }}>取消</button></>
                      ) : (
                        <><button type="button" className="ws-button" onClick={() => beginEdit(character)} title="编辑人物侧写">编辑</button><button type="button" className="ws-button" disabled={busy === character.name} onClick={() => complete(character)} title="用本地规则补全空白侧写">补全基础侧写</button></>
                      )}
                    </div>
                  </div>
                  <StableProfileSection
                    character={character}
                    relations={graphRelations}
                    isEditing={Boolean(isEditing)}
                    draft={isEditing ? draft : null}
                    onChangeNested={(field, value) => draft && setDraft(updateNestedValue(draft, field, value))}
                    onChangeTaxonomy={(field, value) => draft && setDraft({ ...draft, [field]: value })}
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
                </article>
              );
            })}
          </div>
        ) : (
          <p className="ws-card__hint">
            {characters.length > 0 ? "当前筛选没有匹配的角色卡。" : "暂无角色档案。"}
          </p>
        )}
      </section>
    </div>
  );
}
