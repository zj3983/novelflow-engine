"use client";

import { useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import {
  completeFileProjectCharacterPortrait,
  updateFileProjectCharacter,
  type CharacterPortrait,
} from "../../../../lib/api";
import { cleanLines, compactRecord, mergeCharacters, panelRows, richProfileEntries, shortStatus, type DisplayCharacter } from "../../../../lib/worldDisplay";

function characterCardBadge(state: string | undefined): string {
  if (state === "proposed") return "待出场卡";
  if (state === "active") return "确定性角色卡";
  return "记录卡";
}

type PortraitSection = {
  key: keyof CharacterPortrait;
  title: string;
  fields: Array<{ key: string; label: string; list?: boolean }>;
};

const portraitSections: PortraitSection[] = [
  {
    key: "temperament",
    title: "性格底色",
    fields: [
      { key: "outward_impression", label: "外在印象" },
      { key: "core_traits", label: "核心性格", list: true },
      { key: "inner_contradiction", label: "内在矛盾" },
      { key: "values", label: "价值观", list: true },
      { key: "bottom_line", label: "底线" },
    ],
  },
  {
    key: "psychology",
    title: "心理侧写",
    fields: [
      { key: "desire", label: "核心欲望" },
      { key: "fear", label: "主要恐惧" },
      { key: "blind_spot", label: "判断盲点" },
      { key: "defense", label: "防御方式" },
      { key: "shame_point", label: "羞耻点" },
    ],
  },
  {
    key: "behavior",
    title: "行为模式",
    fields: [
      { key: "normal_mode", label: "平时" },
      { key: "pressure_mode", label: "压力下" },
      { key: "conflict_response", label: "冲突时" },
      { key: "failure_response", label: "失败后" },
      { key: "decision_tendency", label: "做决定" },
    ],
  },
  {
    key: "emotion",
    title: "情绪表现",
    fields: [
      { key: "triggers", label: "触发点", list: true },
      { key: "restraint_style", label: "克制方式" },
      { key: "loss_of_control", label: "失控表现" },
      { key: "mannerisms", label: "常见小动作", list: true },
    ],
  },
  {
    key: "social",
    title: "社交模式",
    fields: [
      { key: "strangers", label: "陌生人" },
      { key: "friends", label: "朋友" },
      { key: "authority", label: "上位者" },
      { key: "enemies", label: "敌人" },
    ],
  },
  {
    key: "voice",
    title: "语言特征",
    fields: [
      { key: "common_words", label: "常用词", list: true },
      { key: "sentence_habit", label: "句子习惯" },
      { key: "avoided_topics", label: "回避话题", list: true },
      { key: "lying_style", label: "撒谎方式" },
      { key: "anger_style", label: "生气时" },
      { key: "relaxed_style", label: "放松时" },
    ],
  },
  {
    key: "growth",
    title: "成长弧线",
    fields: [
      { key: "initial_flaw", label: "初始缺陷" },
      { key: "invariants", label: "稳定不变量", list: true },
      { key: "change_conditions", label: "变化条件", list: true },
      { key: "stage_direction", label: "阶段方向" },
    ],
  },
  { key: "writing_limits", title: "写作禁区", fields: [{ key: "writing_limits", label: "不能出现", list: true }] },
];

function cloneCharacter(character: DisplayCharacter): DisplayCharacter {
  return JSON.parse(JSON.stringify(character)) as DisplayCharacter;
}

function fieldValue(portrait: CharacterPortrait, section: keyof CharacterPortrait, field: string): string | string[] {
  if (section === "writing_limits") return portrait.writing_limits ?? [];
  const group = portrait[section];
  if (!group || typeof group !== "object") return "";
  const value = (group as Record<string, unknown>)[field];
  return Array.isArray(value) ? value.map(String) : String(value ?? "");
}

function updatePortrait(
  character: DisplayCharacter,
  section: keyof CharacterPortrait,
  field: string,
  value: string,
  list: boolean,
): DisplayCharacter {
  const next = cloneCharacter(character);
  const portrait = { ...(next.personality_portrait ?? {}) } as CharacterPortrait & Record<string, unknown>;
  if (section === "writing_limits") {
    portrait.writing_limits = value.split("\n").map((line) => line.trim()).filter(Boolean);
  } else {
    const group = { ...((portrait[section] as Record<string, unknown> | undefined) ?? {}) };
    group[field] = list ? value.split("\n").map((line) => line.trim()).filter(Boolean) : value;
    portrait[section] = group as never;
  }
  next.personality_portrait = portrait;
  return next;
}

export default function CharactersPage() {
  const { project, story, error, encodedProjectId, refresh } = useProjectWorkspace();
  const characters = mergeCharacters(project?.character_profiles, story?.characters);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [draft, setDraft] = useState<DisplayCharacter | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const beginEdit = (character: DisplayCharacter) => {
    setEditingName(character.name);
    setDraft(cloneCharacter(character));
    setMessage(null);
  };

  const save = async () => {
    if (!draft || !editingName) return;
    setBusy(editingName);
    setMessage(null);
    try {
      await updateFileProjectCharacter(encodedProjectId, editingName, { personality_portrait: draft.personality_portrait });
      setEditingName(null);
      setDraft(null);
      setMessage("角色卡已保存。");
      refresh();
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
      await completeFileProjectCharacterPortrait(encodedProjectId, character.name);
      setMessage(`${character.name} 的基础侧写已补全。`);
      refresh();
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
        subtitle="完整侧写由规则生成，正文只提取当前场景需要的表现。"
      />
      {error ? <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}><p className="ws-error-text">加载失败：{error}</p></div> : null}
      {message ? <p className="ws-inline-message">{message}</p> : null}

      <section className="ws-card">
        <p className="ws-card__title">人物档案</p>
        {characters.length > 0 ? (
          <div className="ws-character-list">
            {characters.map((character) => {
              const isEditing = editingName === character.name && draft;
              const shown = isEditing ? draft : character;
              const panel = shown?.game_panel;
              const rows = panelRows(panel);
              const attributes = compactRecord(panel?.attributes);
              const equipment = compactRecord(panel?.equipment);
              const inventory = compactRecord(panel?.inventory);
              const motiveRows = [
                ["人设类型", shown?.character_type], ["核心动机", shown?.core_motivation], ["行为逻辑", shown?.behavior_logic],
                ["互动模式", shown?.interaction_mode], ["故事功能", shown?.story_function], ["本章作用", shown?.chapter_role],
              ].filter(([, value]) => typeof value === "string" && value.trim());
              const socialRows = richProfileEntries(shown?.social_profile);
              const psychRows = richProfileEntries(shown?.psychological_profile);
              const moralRows = richProfileEntries(shown?.moral_profile);
              const portrait = shown?.personality_portrait ?? {};

              return (
                <article className="ws-character-card" key={character.name}>
                  <div className="ws-character-card__head">
                    <div><h2>{shown?.name}</h2><p>{[shown?.role, shown?.game_id || panel?.game_id, shown?.lifecycle_state].filter(Boolean).join(" / ") || "角色"}</p></div>
                    <div className="ws-character-card__actions">
                      <span>{characterCardBadge(shown?.lifecycle_state)}{panel?.updated_chapter ? ` · 第 ${panel.updated_chapter} 章更新` : ""}</span>
                      {isEditing ? (
                        <><button type="button" className="ws-button ws-button--primary" disabled={busy === character.name} onClick={save}>保存角色卡</button><button type="button" className="ws-button" disabled={busy === character.name} onClick={() => { setEditingName(null); setDraft(null); }}>取消</button></>
                      ) : (
                        <><button type="button" className="ws-button" onClick={() => beginEdit(character)} title="编辑人物侧写">编辑</button><button type="button" className="ws-button" disabled={busy === character.name} onClick={() => complete(character)} title="用本地规则补全空白侧写">补全基础侧写</button></>
                      )}
                    </div>
                  </div>
                  <p className="ws-character-card__status">{shortStatus(shown as DisplayCharacter)}</p>
                  {rows.length > 0 ? <dl className="ws-panel-grid">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl> : null}
                  {motiveRows.length > 0 ? <div className="ws-character-section-grid">{motiveRows.map(([label, value]) => <section className="ws-character-mini" key={label}><strong>{label}</strong><p>{value}</p></section>)}</div> : null}
                  {[socialRows, psychRows, moralRows].some((items) => items.length > 0) ? <div className="ws-character-block"><strong>已有三维档案</strong><div className="ws-profile-columns">{[["社会面", socialRows], ["心理面", psychRows], ["底线面", moralRows]].map(([title, items]) => Array.isArray(items) && items.length > 0 ? <section className="ws-profile-column" key={title as string}><b>{title as string}</b><dl>{items.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></section> : null)}</div></div> : null}

                  <div className="ws-character-portrait-grid">
                    {portraitSections.map((section) => {
                      const hasValue = section.fields.some((field) => {
                        const value = fieldValue(portrait, section.key, field.key);
                        return Array.isArray(value) ? value.length > 0 : value.trim().length > 0;
                      });
                      if (!isEditing && !hasValue) return null;
                      return <section className="ws-character-portrait-section" key={String(section.key)}><h3>{section.title}</h3>{section.fields.map((field) => { const value = fieldValue(portrait, section.key, field.key); const text = Array.isArray(value) ? value.join("\n") : value; return isEditing ? <label key={field.key}><span>{field.label}</span><textarea rows={field.list ? 3 : 2} value={text} onChange={(event) => setDraft(updatePortrait(draft as DisplayCharacter, section.key, field.key, event.target.value, Boolean(field.list)))} /></label> : <div className="ws-character-portrait-line" key={field.key}><b>{field.label}</b><p>{text || "未填写"}</p></div>; })}</section>;
                    })}
                  </div>
                  {cleanLines(shown?.poison_points, 8).length > 0 ? <div className="ws-character-block"><strong>写作禁忌提示</strong><div className="ws-tag-row">{cleanLines(shown?.poison_points, 8).map((point, index) => <span className="ws-danger-tag" key={`${point}-${index}`}>{point}</span>)}</div></div> : null}
                  {[...attributes, ...equipment, ...inventory].length > 0 ? <div className="ws-character-block"><strong>面板细节</strong><ul>{[...attributes, ...equipment, ...inventory].slice(0, 8).map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></div> : null}
                </article>
              );
            })}
          </div>
        ) : <p className="ws-card__hint">暂无角色档案。</p>}
      </section>
    </div>
  );
}
