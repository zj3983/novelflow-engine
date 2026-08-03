"use client";

import { useState } from "react";

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

function characterCardBadge(state: string | undefined): string {
  if (state === "proposed") return "待出场卡";
  if (state === "active") return "确定性角色卡";
  return "记录卡";
}

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
      { label: "软肋 / 顾虑", path: ["personality_portrait", "psychology", "fear"] },
      { label: "说话参考", path: ["dialogue_examples"], list: true },
    ] },
    { title: "当前剧情", fields: [
      { label: "重要人际关系", relation: true },
      { label: "技能 / 武器 / 特殊能力", path: ["current_life_profile", "resources_and_ability"] },
      { label: "眼前难题", path: ["current_life_profile", "immediate_problem"] },
      { label: "当前目标", path: ["story_drive", "immediate_goal"] },
      { label: "失败代价", path: ["story_drive", "failure_stakes"] },
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
      { label: "当前目标", path: ["story_drive", "immediate_goal"] },
      { label: "软肋 / 顾虑", path: ["personality_portrait", "psychology", "fear"] },
      { label: "说话参考", path: ["dialogue_examples"], list: true },
    ] },
    { title: "关系与作用", fields: [
      { label: "与主角及重要人物关系", relation: true },
      { label: "主要冲突", path: ["story_drive", "main_conflict_reason"] },
      { label: "技能 / 特长", path: ["current_life_profile", "resources_and_ability"] },
      { label: "隐藏信息", path: ["story_drive", "hidden_matters"], list: true },
      { label: "剧情作用", path: ["story_function"] },
    ] },
  ],
  minor: [
    { title: "角色摘要", fields: [
      { label: "身份 / 职业", path: ["identity_profile", "current_identity"] },
      { label: "当前目的", path: ["story_drive", "immediate_goal"] },
      { label: "与主要人物关系", relation: true },
      { label: "剧情作用", path: ["story_function"] },
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
};

function structuredStateRows(layer: CharacterStateLayer | undefined): DisplayRow[] {
  return Object.entries(layer?.current ?? {}).flatMap(([key, value]) => {
    const formatted = stateRows({ current: { [key]: value } })[0];
    return formatted ? [[CURRENT_STATE_FIELD_LABELS[key] ?? formatted[0], formatted[1]]] : [];
  });
}

export default function CharactersPage() {
  const { project, story, error, encodedProjectId, projectId, refresh } = useProjectWorkspace();
  const characters = mergeCharacters(project?.character_profiles, story?.characters);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [draft, setDraft] = useState<DisplayCharacter | null>(null);
  const [stateDrafts, setStateDrafts] = useState<Partial<Record<StateNamespace, string>>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

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
      {error ? <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}><p className="ws-error-text">加载失败：{error}</p></div> : null}
      {message ? <p className="ws-inline-message">{message}</p> : null}

      <section className="ws-character-workspace" aria-labelledby="character-workspace-title">
        <div className="ws-section-head">
          <h2 className="ws-character-workspace__title" id="character-workspace-title">人物档案</h2>
        </div>
        {characters.length > 0 ? (
          <div className="ws-character-list">
            {characters.map((character) => {
              const gameStory = isGameWebnovel(project);
              const isEditing = editingName === character.name && draft;
              const shown = isEditing ? draft : character;
              const effectiveGameState = shown?.game_state ?? (shown?.game_panel ? { current: shown.game_panel } : undefined);
              const showGameState = gameStory && Boolean(effectiveGameState);
              const panel = showGameState && !shown?.game_state ? shown?.game_panel : undefined;
              const displayedGameId = showGameState
                ? effectiveGameState?.current?.game_id ?? shown?.game_id ?? panel?.game_id
                : undefined;
              const graphRelations = (project?.relationship_graph ?? []).filter(
                (relation) => relation.source === shown?.name || relation.target === shown?.name,
              );
              const genericState = currentStateLayer(shown?.current_state) ?? shown?.real_state;
              const stateLayers = (gameStory ? [
                ["real_state", shown?.real_state],
                ["game_state", showGameState ? effectiveGameState : undefined],
              ] : [
                ["current_state", genericState],
              ] as Array<[StateNamespace, CharacterStateLayer | undefined]>).filter((entry): entry is [StateNamespace, CharacterStateLayer] => Boolean(entry[1]));
              const templateKind = characterTemplateKind(shown as DisplayCharacter);
              const templateSections = CHARACTER_TEMPLATES[templateKind];
              const relationsText = relationshipSummary(shown?.name ?? "", project?.relationship_graph ?? []);

              return (
                <article className="ws-character-card" data-testid={`character-card-${templateKind}`} key={character.name}>
                  <div className="ws-character-card__head">
                    <div><h2>{shown?.name}</h2><p>{[templateKindLabel(templateKind), characterRoleLabel(shown?.role), displayedGameId].filter(Boolean).join(" / ")}</p></div>
                    <div className="ws-character-card__actions">
                      <span>{characterCardBadge(shown?.lifecycle_state)}{panel?.updated_chapter ? ` · 第 ${panel.updated_chapter} 章更新` : ""}</span>
                      {isEditing ? (
                        <><button type="button" className="ws-button ws-button--primary" disabled={busy === character.name} onClick={save}>保存角色卡</button><button type="button" className="ws-button" disabled={busy === character.name} onClick={() => { setEditingName(null); setDraft(null); setStateDrafts({}); }}>取消</button></>
                      ) : (
                        <><button type="button" className="ws-button" onClick={() => beginEdit(character)} title="编辑人物侧写">编辑</button><button type="button" className="ws-button" disabled={busy === character.name} onClick={() => complete(character)} title="用本地规则补全空白侧写">补全基础侧写</button></>
                      )}
                    </div>
                  </div>
                  <div className={`ws-character-template ws-character-template--${templateKind}`}>
                    {templateSections.map((section) => {
                      const fields = section.fields.filter((field) => {
                        if (isEditing) return true;
                        const rawValue = field.relation ? relationsText : nestedValue(shown as DisplayCharacter, field.path ?? []);
                        return (Array.isArray(rawValue) ? rawValue.length > 0 : Boolean(String(rawValue).trim()));
                      });
                      if (!isEditing && fields.length === 0) return null;
                      return (
                      <section className="ws-character-template__section" key={section.title}>
                        <h3>{section.title}</h3>
                        <div className="ws-character-template__fields">
                          {fields.map((field) => {
                            const rawValue = field.relation ? relationsText : nestedValue(shown as DisplayCharacter, field.path ?? []);
                            const text = Array.isArray(rawValue) ? rawValue.join(isEditing ? "\n" : "；") : rawValue;
                            const displayValue = field.number && text ? `${text}${field.label.includes("年龄") ? "岁" : "章"}` : text;
                            return isEditing && field.path ? (
                              <label className="ws-character-template__field" key={field.label}>
                                <span>{field.label}</span>
                                {field.number ? (
                                  <input aria-label={field.label} type="number" min={0} value={text} onChange={(event) => setDraft(updateNestedValue(draft as DisplayCharacter, field, event.target.value))} />
                                ) : (
                                  <textarea aria-label={field.label} rows={field.list ? 3 : 2} value={text} onChange={(event) => setDraft(updateNestedValue(draft as DisplayCharacter, field, event.target.value))} />
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

                  {(stateLayers.length > 0 || graphRelations.length > 0 || panel) ? (
                    <details className="ws-character-runtime">
                      <summary>运行状态与章节动态</summary>
                      {stateLayers.map(([namespace, layer]) => isEditing ? (
                        <label key={namespace}><span>{STATE_TITLES[namespace]} JSON</span><textarea aria-label={`${STATE_TITLES[namespace]} JSON`} rows={8} value={stateDrafts[namespace] ?? stateJson(layer)} onChange={(event) => setStateDrafts((current) => ({ ...current, [namespace]: event.target.value }))} /></label>
                      ) : (
                        <dl className="ws-panel-grid" key={namespace}>{structuredStateRows(layer).map(([label, value]) => <div key={`${namespace}-${label}`}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
                      ))}
                    </details>
                  ) : null}
                </article>
              );
            })}
          </div>
        ) : <p className="ws-card__hint">暂无角色档案。</p>}
      </section>
    </div>
  );
}
