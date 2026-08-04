"use client";

import { useEffect, useRef, useState } from "react";

import {
  updateProject,
  type ImportedWorldBlueprint,
  type ProjectResponse,
} from "../../lib/api";
import { hasPowerSystemDraft, hasStructuredPowerSystem, StructuredPowerSystem } from "./StructuredPowerSystem";

export type EditableWorldRuleField =
  | "world_rules"
  | "power_system"
  | "progression_rules"
  | "quest_rules"
  | "economy_rules"
  | "faction_rules"
  | "panel_rules"
  | "constraints"
  | "forbidden_breaks"
  | "reality_bridge_rules";

type Props = {
  projectId: string;
  blueprint: ImportedWorldBlueprint;
  onSaved?: () => void;
};

export type WorldBlueprintStore = {
  current: ImportedWorldBlueprint;
  pending?: Partial<Record<EditableWorldRuleField, string[]>>;
};

type SaveWorldRulesArgs = Omit<Props, "blueprint"> & {
  field: EditableWorldRuleField;
  text: string;
  blueprintStore: WorldBlueprintStore;
  updater?: typeof updateProject;
};

export const WORLD_RULE_EDITOR_SECTIONS: ReadonlyArray<{
  id: string;
  title: string;
  wide: boolean;
  fields: ReadonlyArray<{ field: EditableWorldRuleField; label: string; buttonLabel: string }>;
}> = [
  { id: "basic", title: "基础规则", wide: true, fields: [{ field: "world_rules", label: "基础规则", buttonLabel: "保存基础规则" }] },
  {
    id: "progression",
    title: "成长体系",
    wide: true,
    fields: [
      { field: "power_system", label: "等级、职业与技能", buttonLabel: "保存力量体系" },
      { field: "progression_rules", label: "成长与战斗边界", buttonLabel: "保存成长规则" },
    ],
  },
  { id: "economy", title: "经济体系", wide: false, fields: [{ field: "economy_rules", label: "货币、价格与交易", buttonLabel: "保存经济体系" }] },
  { id: "quest", title: "任务体系", wide: false, fields: [{ field: "quest_rules", label: "任务类型、状态与奖励", buttonLabel: "保存任务体系" }] },
  {
    id: "faction-panel",
    title: "阵营与面板",
    wide: true,
    fields: [
      { field: "faction_rules", label: "阵营规则", buttonLabel: "保存阵营规则" },
      { field: "panel_rules", label: "面板规则", buttonLabel: "保存面板规则" },
    ],
  },
  { id: "reality", title: "游戏影响现实", wide: true, fields: [{ field: "reality_bridge_rules", label: "游戏影响现实规则", buttonLabel: "保存游戏影响现实规则" }] },
  {
    id: "constraints",
    title: "世界硬约束",
    wide: true,
    fields: [
      { field: "constraints", label: "世界硬约束", buttonLabel: "保存世界硬约束" },
      { field: "forbidden_breaks", label: "不可违反规则", buttonLabel: "保存不可违反规则" },
    ],
  },
];

export function worldRuleEditorSections(blueprint: ImportedWorldBlueprint) {
  const genreIds = (blueprint.genre_plugin_ids ?? []).map((id) => String(id).trim().toLowerCase());
  const isGameStory = genreIds.includes("game_webnovel");
  const isXianxia = genreIds.includes("xianxia");
  if (isGameStory) return WORLD_RULE_EDITOR_SECTIONS;

  return WORLD_RULE_EDITOR_SECTIONS
    .filter((section) => !["quest", "reality"].includes(section.id))
    .map((section) => {
      if (section.id === "progression" && isXianxia) {
        return {
          ...section,
          title: "修炼体系",
          fields: section.fields.map((field) => field.field === "power_system"
            ? { ...field, label: "境界、功法与能力", buttonLabel: "保存修炼体系" }
            : { ...field, label: "突破、战斗与代价", buttonLabel: "保存修炼规则" }),
        };
      }
      if (section.id === "economy" && isXianxia) {
        return {
          ...section,
          title: "资源体系",
          fields: section.fields.map((field) => ({
            ...field,
            label: "灵石、资源与交换",
            buttonLabel: "保存资源体系",
          })),
        };
      }
      if (section.id === "faction-panel") {
        return {
          ...section,
          title: isXianxia ? "宗门与势力" : "阵营规则",
          fields: section.fields.filter((field) => field.field === "faction_rules"),
        };
      }
      return section;
    });
}

function rulesText(value?: string[]) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string").join("\n") : "";
}

const EDITABLE_WORLD_RULE_FIELDS: EditableWorldRuleField[] = [
  "world_rules",
  "power_system",
  "progression_rules",
  "quest_rules",
  "economy_rules",
  "faction_rules",
  "panel_rules",
  "constraints",
  "forbidden_breaks",
  "reality_bridge_rules",
];

export type WorldRulesEditorState = {
  drafts: Record<EditableWorldRuleField, string>;
  dirty: Record<EditableWorldRuleField, boolean>;
  statuses: Partial<Record<EditableWorldRuleField, "success" | "error">>;
  errors: Partial<Record<EditableWorldRuleField, string>>;
};

function ruleDrafts(blueprint: ImportedWorldBlueprint): Record<EditableWorldRuleField, string> {
  return {
    world_rules: rulesText(blueprint.world_rules),
    power_system: rulesText(blueprint.power_system),
    progression_rules: rulesText(blueprint.progression_rules),
    quest_rules: rulesText(blueprint.quest_rules),
    economy_rules: rulesText(blueprint.economy_rules),
    faction_rules: rulesText(blueprint.faction_rules),
    panel_rules: rulesText(blueprint.panel_rules),
    constraints: rulesText(blueprint.constraints),
    forbidden_breaks: rulesText(blueprint.forbidden_breaks),
    reality_bridge_rules: rulesText(blueprint.reality_bridge_rules),
  };
}

export function createWorldRulesEditorState(blueprint: ImportedWorldBlueprint): WorldRulesEditorState {
  return {
    drafts: ruleDrafts(blueprint),
    dirty: {
      world_rules: false,
      power_system: false,
      progression_rules: false,
      quest_rules: false,
      economy_rules: false,
      faction_rules: false,
      panel_rules: false,
      constraints: false,
      forbidden_breaks: false,
      reality_bridge_rules: false,
    },
    statuses: {},
    errors: {},
  };
}

export function mergeWorldRulesProps(
  state: WorldRulesEditorState,
  blueprint: ImportedWorldBlueprint,
): WorldRulesEditorState {
  const incoming = ruleDrafts(blueprint);
  const drafts = { ...state.drafts };
  const dirty = { ...state.dirty };
  for (const field of EDITABLE_WORLD_RULE_FIELDS) {
    if (!dirty[field]) {
      drafts[field] = incoming[field];
    } else if (sameRules(blueprint[field], parseRuleLines(drafts[field]))) {
      dirty[field] = false;
      drafts[field] = incoming[field];
    }
  }
  return { ...state, drafts, dirty };
}

export function editWorldRuleField(
  state: WorldRulesEditorState,
  field: EditableWorldRuleField,
  value: string,
): WorldRulesEditorState {
  return {
    ...state,
    drafts: { ...state.drafts, [field]: value },
    dirty: { ...state.dirty, [field]: true },
    statuses: { ...state.statuses, [field]: undefined },
    errors: { ...state.errors, [field]: undefined },
  };
}

export function markWorldRuleSaved(
  state: WorldRulesEditorState,
  field: EditableWorldRuleField,
  submittedText: string,
): WorldRulesEditorState {
  return {
    ...state,
    statuses: {
      ...state.statuses,
      [field]: state.drafts[field] === submittedText ? "success" : undefined,
    },
    errors: { ...state.errors, [field]: undefined },
  };
}

function sameRules(left?: string[], right?: string[]) {
  return JSON.stringify(left ?? []) === JSON.stringify(right ?? []);
}

export function syncWorldBlueprintStore(
  store: WorldBlueprintStore,
  incoming: ImportedWorldBlueprint,
): void {
  const pending = { ...(store.pending ?? {}) };
  const next = { ...store.current, ...incoming };
  for (const field of EDITABLE_WORLD_RULE_FIELDS) {
    const savedRules = pending[field];
    if (!savedRules) continue;
    if (sameRules(incoming[field], savedRules)) {
      delete pending[field];
    } else {
      next[field] = savedRules;
    }
  }
  store.current = next;
  store.pending = pending;
}

export function parseRuleLines(value: string): string[] {
  return value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

export async function saveWorldRules({
  projectId,
  field,
  text,
  blueprintStore,
  onSaved,
  updater = updateProject,
}: SaveWorldRulesArgs): Promise<ProjectResponse> {
  const parsedRules = parseRuleLines(text);
  const nextBlueprint = { ...blueprintStore.current, [field]: parsedRules };
  const updated = await updater(
    projectId,
    { world_blueprint: { [field]: parsedRules } },
    { fallbackToMock: false },
  );
  blueprintStore.current = { ...nextBlueprint, ...(updated.world_blueprint ?? {}) };
  blueprintStore.pending = {
    ...(blueprintStore.pending ?? {}),
    [field]: blueprintStore.current[field] ?? parsedRules,
  };
  onSaved?.();
  return updated;
}

export function WorldRulesEditor({ projectId, blueprint, onSaved }: Props) {
  const [editorState, setEditorState] = useState(() => createWorldRulesEditorState(blueprint));
  const [saving, setSaving] = useState<EditableWorldRuleField | null>(null);
  const blueprintStore = useRef<WorldBlueprintStore>({ current: blueprint });
  const powerSystemSpec = blueprint.power_system_spec as unknown;
  const hasStructuredPower = hasStructuredPowerSystem(powerSystemSpec, blueprint.genre_plugin_ids);
  const hasPowerDraft = hasPowerSystemDraft(powerSystemSpec);
  const hasLegacyPower = Array.isArray(blueprint.power_system)
    && blueprint.power_system.some((item) => typeof item === "string" && item.trim());

  useEffect(() => {
    syncWorldBlueprintStore(blueprintStore.current, blueprint);
    setEditorState((current) => mergeWorldRulesProps(current, blueprint));
  }, [blueprint]);

  const setDraft = (field: EditableWorldRuleField, value: string) => {
    setEditorState((current) => editWorldRuleField(current, field, value));
  };

  const save = async (field: EditableWorldRuleField) => {
    const submittedText = editorState.drafts[field];
    setSaving(field);
    setEditorState((current) => ({
      ...current,
      statuses: { ...current.statuses, [field]: undefined },
      errors: { ...current.errors, [field]: undefined },
    }));
    try {
      await saveWorldRules({
        projectId,
        field,
        text: submittedText,
        blueprintStore: blueprintStore.current,
        onSaved,
      });
      setEditorState((current) => markWorldRuleSaved(current, field, submittedText));
    } catch (err) {
      setEditorState((current) => ({
        ...current,
        errors: { ...current.errors, [field]: err instanceof Error ? err.message : String(err) },
        statuses: { ...current.statuses, [field]: "error" },
      }));
    } finally {
      setSaving(null);
    }
  };

  const editor = (field: EditableWorldRuleField, label: string, buttonLabel: string) => (
    <div className="ws-prompt-section">
      <label className="ws-search">
        <span>{label}</span>
        <textarea
          className="ws-input"
          rows={5}
          value={editorState.drafts[field]}
          onChange={(event) => setDraft(field, event.target.value)}
        />
      </label>
      <div className="ws-toolbar">
        <button type="button" className="ws-button ws-button--primary" disabled={saving !== null} onClick={() => save(field)}>
          {saving === field ? "保存中..." : buttonLabel}
        </button>
        {saving === field ? <span role="status" aria-live="polite">保存中...</span> : null}
        {editorState.statuses[field] === "success" ? <span role="status" aria-live="polite" style={{ color: "var(--ws-success)" }}>保存成功</span> : null}
        {editorState.statuses[field] === "error" ? <span className="ws-error-text" role="alert">保存失败：{editorState.errors[field]}</span> : null}
      </div>
    </div>
  );

  return (
    <section className="ws-card" aria-labelledby="world-rules-title">
      <div className="ws-section-head">
        <div>
          <h2 className="ws-card__title" id="world-rules-title">世界规则</h2>
          <p className="ws-card__hint">每行解析为一条规则，空行不会保存。</p>
        </div>
      </div>

      {hasStructuredPower ? (
        <StructuredPowerSystem
          spec={blueprint.power_system_spec}
          genrePluginIds={blueprint.genre_plugin_ids}
        />
      ) : null}
      {!hasStructuredPower && (hasLegacyPower || hasPowerDraft) ? <p className="ws-card__hint">力量体系需要补全</p> : null}

      <div className="ws-form-grid">
        {worldRuleEditorSections(blueprint).map((section) => (
          <section
            className={section.wide ? "ws-form-grid__wide" : undefined}
            aria-labelledby={`${section.id}-world-rules-title`}
            key={section.id}
          >
            <h3 id={`${section.id}-world-rules-title`}>{section.title}</h3>
            {section.fields.length > 1 ? (
              <div className="ws-form-grid">
                {section.fields.map((field) => (
                  <div key={field.field}>{editor(field.field, field.label, field.buttonLabel)}</div>
                ))}
              </div>
            ) : section.fields.map((field) => (
              <div key={field.field}>{editor(field.field, field.label, field.buttonLabel)}</div>
            ))}
          </section>
        ))}
      </div>
    </section>
  );
}
