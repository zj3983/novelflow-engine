"use client";

import { useEffect, useState } from "react";

import {
  updateProject,
  type ImportedMonsterProfile,
  type ImportedWorldBlueprint,
} from "../../lib/api";

type Props = {
  projectId: string;
  blueprint: ImportedWorldBlueprint;
  onSaved?: () => void;
};

const EMPTY_MONSTER: ImportedMonsterProfile = {
  name: "",
  category: "",
  rank: "普通",
  level: "",
  hp: "",
  attack_mode: "",
  skills: [],
  traits: [],
  habitats: [],
  drops: [],
  status: "active",
};

function listText(value?: string[]) {
  return (value ?? []).join("、");
}

function parseList(value: string) {
  return value.split(/[、,，;；\n]/).map((item) => item.trim()).filter(Boolean);
}

function fieldValue(profile: ImportedMonsterProfile, key: keyof ImportedMonsterProfile) {
  const value = profile[key];
  return Array.isArray(value) ? listText(value) : String(value ?? "");
}

function displayLevel(value?: string) {
  const level = value?.trim();
  if (!level) return "";
  return /^lv\.?/i.test(level) ? level : `Lv.${level}`;
}

export function MonsterBestiary({ projectId, blueprint, onSaved }: Props) {
  const [profiles, setProfiles] = useState<ImportedMonsterProfile[]>(blueprint.monster_profiles ?? []);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [draft, setDraft] = useState<ImportedMonsterProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => setProfiles(blueprint.monster_profiles ?? []), [blueprint.monster_profiles]);

  const beginEdit = (profile: ImportedMonsterProfile, index: number) => {
    setEditingIndex(index);
    setDraft({ ...profile, skills: [...(profile.skills ?? [])], traits: [...(profile.traits ?? [])], habitats: [...(profile.habitats ?? [])], drops: [...(profile.drops ?? [])] });
    setError("");
  };

  const beginAdd = () => {
    setEditingIndex(-1);
    setDraft({ ...EMPTY_MONSTER });
    setError("");
  };

  const setText = (key: keyof ImportedMonsterProfile, value: string) => {
    setDraft((current) => current ? { ...current, [key]: value } : current);
  };

  const setList = (key: "skills" | "traits" | "habitats" | "drops", value: string) => {
    setDraft((current) => current ? { ...current, [key]: parseList(value) } : current);
  };

  const saveProfiles = async (nextProfiles: ImportedMonsterProfile[]) => {
    setBusy(true);
    setError("");
    try {
      const updated = await updateProject(
        projectId,
        { world_blueprint: { monster_profiles: nextProfiles } },
        { fallbackToMock: false },
      );
      setProfiles(updated.world_blueprint?.monster_profiles ?? nextProfiles);
      setEditingIndex(null);
      setDraft(null);
      onSaved?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!draft?.name.trim()) {
      setError("怪物名称不能为空。");
      return;
    }
    const normalized = {
      ...draft,
      id: draft.id || `monster-${Date.now()}`,
      name: draft.name.trim(),
      first_appearance_chapter: Number(draft.first_appearance_chapter || 0) || undefined,
    };
    const next = editingIndex === -1
      ? [...profiles, normalized]
      : profiles.map((item, index) => index === editingIndex ? normalized : item);
    await saveProfiles(next);
  };

  const remove = async (index: number) => {
    await saveProfiles(profiles.filter((_, itemIndex) => itemIndex !== index));
  };

  return (
    <section className="ws-card" aria-labelledby="monster-bestiary-title">
      <div className="ws-section-head">
        <div>
          <h2 className="ws-card__title" id="monster-bestiary-title">怪物图鉴</h2>
          <p className="ws-card__hint">怪物资料独立于人物角色卡，写作时只读取本章出场怪物。</p>
        </div>
        <button type="button" className="ws-button" onClick={beginAdd}>新增怪物</button>
      </div>

      {profiles.length ? (
        <div className="ws-rule-list">
          {profiles.map((profile, index) => (
            <article className="ws-rule-item" key={profile.id || `${profile.name}-${index}`}>
              <div>
                <strong>{profile.name}</strong>
                <span>{[profile.category, profile.rank, displayLevel(profile.level)].filter(Boolean).join(" · ")}</span>
              </div>
              <p>生命：{profile.hp || "未设定"}　攻击方式：<span>{profile.attack_mode || "未设定"}</span></p>
              {profile.skills?.length ? <p>技能：{listText(profile.skills)}</p> : null}
              {profile.traits?.length ? <p>特性：{listText(profile.traits)}</p> : null}
              {profile.habitats?.length ? <p>出没地点：{listText(profile.habitats)}</p> : null}
              {profile.drops?.length ? <p>可能掉落：{listText(profile.drops)}</p> : null}
              <div className="ws-toolbar">
                <button type="button" className="ws-button" aria-label={`编辑${profile.name}`} onClick={() => beginEdit(profile, index)}>编辑</button>
                <button type="button" className="ws-button" aria-label={`删除${profile.name}`} disabled={busy} onClick={() => remove(index)}>删除</button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="ws-card__hint">暂无怪物卡。</p>
      )}

      {draft ? (
        <div className="ws-form-grid" style={{ marginTop: 16 }}>
          {([
            ["name", "怪物名称"], ["category", "怪物类别"], ["rank", "怪物品阶"], ["level", "怪物等级"],
            ["hp", "怪物生命"], ["attack_mode", "攻击方式"], ["skills", "技能"], ["traits", "特性"],
            ["habitats", "出没地点"], ["drops", "可能掉落"], ["first_appearance_chapter", "首次出场章节"], ["status", "当前状态"],
          ] as Array<[keyof ImportedMonsterProfile, string]>).map(([key, label]) => (
            <label className="ws-search" key={key}>
              <span>{label}</span>
              <input
                className="ws-input"
                aria-label={label}
                type={key === "first_appearance_chapter" ? "number" : "text"}
                value={fieldValue(draft, key)}
                onChange={(event) => ["skills", "traits", "habitats", "drops"].includes(key)
                  ? setList(key as "skills" | "traits" | "habitats" | "drops", event.target.value)
                  : setText(key, event.target.value)}
              />
            </label>
          ))}
          <div className="ws-toolbar ws-form-grid__wide">
            <button type="button" className="ws-button ws-button--primary" disabled={busy} onClick={save}>保存怪物卡</button>
            <button type="button" className="ws-button" disabled={busy} onClick={() => { setEditingIndex(null); setDraft(null); setError(""); }}>取消</button>
          </div>
          {error ? <p className="ws-card__hint ws-form-grid__wide" style={{ color: "var(--ws-danger)" }}>{error}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
