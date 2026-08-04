"use client";

import { Pencil, Save, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  updateProject,
  type ImportedEquipmentCard,
  type ImportedWorldBlueprint,
} from "../../lib/api";
import styles from "./EquipmentCatalog.module.css";

type Props = {
  projectId: string;
  blueprint: ImportedWorldBlueprint;
  onSaved?: () => void;
};

function options(cards: ImportedEquipmentCard[], key: "equipment_type" | "rarity" | "current_owner") {
  return Array.from(new Set(cards.map((card) => String(card[key] ?? "").trim()).filter(Boolean)));
}

function list(value?: string[]) {
  return value?.filter(Boolean).join("、") ?? "";
}

function loreLabel(status?: ImportedEquipmentCard["lore_status"]) {
  if (status === "confirmed") return "来历已确认";
  if (status === "rumor") return "来历传闻";
  return "来历尚未揭晓";
}

export function EquipmentCatalog({ projectId, blueprint, onSaved }: Props) {
  const [cards, setCards] = useState<ImportedEquipmentCard[]>(blueprint.equipment_cards ?? []);
  const [typeFilter, setTypeFilter] = useState("");
  const [rarityFilter, setRarityFilter] = useState("");
  const [ownerFilter, setOwnerFilter] = useState("");
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [draft, setDraft] = useState<ImportedEquipmentCard | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => setCards(blueprint.equipment_cards ?? []), [blueprint.equipment_cards]);

  const filtered = useMemo(() => cards.map((card, index) => ({ card, index })).filter(({ card }) => (
    (!typeFilter || card.equipment_type === typeFilter)
    && (!rarityFilter || card.rarity === rarityFilter)
    && (!ownerFilter || card.current_owner === ownerFilter)
  )), [cards, ownerFilter, rarityFilter, typeFilter]);

  const beginEdit = (card: ImportedEquipmentCard, index: number) => {
    setEditingIndex(index);
    setDraft({ ...card });
    setError("");
  };

  const setText = (key: keyof ImportedEquipmentCard, value: string) => {
    setDraft((current) => current ? { ...current, [key]: value } : current);
  };

  const save = async () => {
    if (editingIndex === null || !draft) return;
    if (!draft.name.trim() || !draft.equipment_type.trim()) {
      setError("装备名称和类型不能为空。");
      return;
    }
    const next = cards.map((card, index) => index === editingIndex ? {
      ...draft,
      name: draft.name.trim(),
      equipment_type: draft.equipment_type.trim(),
    } : card);
    setBusy(true);
    setError("");
    try {
      const updated = await updateProject(
        projectId,
        { world_blueprint: { equipment_cards: next } },
        { fallbackToMock: false },
      );
      setCards(updated.world_blueprint?.equipment_cards ?? next);
      setEditingIndex(null);
      setDraft(null);
      onSaved?.();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : String(saveError));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="ws-card" aria-label="装备图鉴" aria-labelledby="equipment-catalog-title">
      <div className="ws-section-head">
        <div>
          <h2 className="ws-card__title" id="equipment-catalog-title">装备图鉴</h2>
          <p className="ws-card__hint">记录正文出现的具名装备、属性、归属和可核对的来历。</p>
        </div>
      </div>

      <div className={styles.filters} aria-label="装备筛选">
        <label>
          <span>装备类型</span>
          <select className="ws-input" aria-label="装备类型" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
            <option value="">全部类型</option>
            {options(cards, "equipment_type").map((value) => <option key={value}>{value}</option>)}
          </select>
        </label>
        <label>
          <span>装备品质</span>
          <select className="ws-input" aria-label="装备品质" value={rarityFilter} onChange={(event) => setRarityFilter(event.target.value)}>
            <option value="">全部品质</option>
            {options(cards, "rarity").map((value) => <option key={value}>{value}</option>)}
          </select>
        </label>
        <label>
          <span>当前持有者</span>
          <select className="ws-input" aria-label="当前持有者" value={ownerFilter} onChange={(event) => setOwnerFilter(event.target.value)}>
            <option value="">全部持有者</option>
            {options(cards, "current_owner").map((value) => <option key={value}>{value}</option>)}
          </select>
        </label>
      </div>

      {filtered.length ? (
        <div className={styles.list}>
          {filtered.map(({ card, index }) => (
            <article className={styles.item} key={card.id || `${card.name}-${index}`}>
              <div className={styles.itemHead}>
                <div className={styles.nameBlock}>
                  <h3>{card.name}</h3>
                  <p>{[card.rarity, card.equipment_type, card.slot].filter(Boolean).join(" · ")}</p>
                </div>
                <button className="ws-button" type="button" aria-label={`编辑${card.name}`} onClick={() => beginEdit(card, index)}>
                  <Pencil aria-hidden="true" size={15} /> 编辑
                </button>
              </div>
              <dl className={styles.facts}>
                {card.required_level ? <div><dt>等级</dt><dd>{card.required_level}</dd></div> : null}
                {card.class_restrictions?.length ? <div><dt>职业</dt><dd>{list(card.class_restrictions)}</dd></div> : null}
                {card.current_owner ? <div><dt>持有者</dt><dd>{card.current_owner}</dd></div> : null}
                {card.current_location ? <div><dt>位置</dt><dd>{card.current_location}</dd></div> : null}
                {card.durability ? <div><dt>耐久</dt><dd>{card.durability}</dd></div> : null}
                {card.status ? <div><dt>状态</dt><dd>{card.status}</dd></div> : null}
                {card.first_appearance_chapter ? <div><dt>首次出现</dt><dd>第 {card.first_appearance_chapter} 章</dd></div> : null}
                {card.source ? <div><dt>来源</dt><dd>{card.source}</dd></div> : null}
              </dl>
              {card.base_attributes && Object.keys(card.base_attributes).length ? (
                <p className={styles.line}><strong>基础属性</strong>{Object.entries(card.base_attributes).map(([name, value]) => `${name} ${value}`).join(" · ")}</p>
              ) : null}
              {card.skills?.length ? <p className={styles.line}><strong>技能</strong>{list(card.skills)}</p> : null}
              {card.special_effects?.length ? <p className={styles.line}><strong>特效</strong>{list(card.special_effects)}</p> : null}
              {card.description ? <blockquote className={styles.flavor}>{card.description}</blockquote> : null}
              {card.lore ? (
                <div className={styles.lore}>
                  <span data-status={card.lore_status ?? "unknown"}>{loreLabel(card.lore_status)}</span>
                  <p>{card.lore}</p>
                  {card.set_lore ? <p>{card.set_lore}</p> : null}
                </div>
              ) : null}

              {editingIndex === index && draft ? (
                <div className={styles.editor}>
                  <label><span>装备说明</span><textarea className="ws-input" aria-label="装备说明" value={draft.description ?? ""} onChange={(event) => setText("description", event.target.value)} /></label>
                  <label><span>装备来历</span><textarea className="ws-input" aria-label="装备来历" value={draft.lore ?? ""} onChange={(event) => setText("lore", event.target.value)} /></label>
                  <label><span>来历状态</span><select className="ws-input" aria-label="来历状态" value={draft.lore_status ?? "unknown"} onChange={(event) => setText("lore_status", event.target.value)}><option value="confirmed">已确认</option><option value="rumor">传闻</option><option value="unknown">未知</option></select></label>
                  <label><span>持有者</span><input className="ws-input" aria-label="装备持有者" value={draft.current_owner ?? ""} onChange={(event) => setText("current_owner", event.target.value)} /></label>
                  <label><span>耐久</span><input className="ws-input" aria-label="装备耐久" value={draft.durability ?? ""} onChange={(event) => setText("durability", event.target.value)} /></label>
                  <label><span>状态</span><input className="ws-input" aria-label="装备状态" value={draft.status ?? ""} onChange={(event) => setText("status", event.target.value)} /></label>
                  <div className={styles.actions}>
                    <button className="ws-button ws-button--primary" type="button" disabled={busy} onClick={() => void save()}><Save aria-hidden="true" size={15} />保存装备卡</button>
                    <button className="ws-button" type="button" disabled={busy} onClick={() => { setEditingIndex(null); setDraft(null); setError(""); }}><X aria-hidden="true" size={15} />取消</button>
                  </div>
                  {error ? <p className={styles.error}>{error}</p> : null}
                </div>
              ) : null}
            </article>
          ))}
        </div>
      ) : <p className="ws-card__hint">没有符合当前筛选条件的装备。</p>}
    </section>
  );
}
