"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  createNovelType,
  deleteNovelType,
  fetchNovelTypes,
  updateNovelType,
  type NovelType,
  type NovelTypeRulebook,
  type NovelTypeWriteRequest,
} from "../../lib/api";
import styles from "./NovelTypeLibraryClient.module.css";

const RULEBOOK_FIELDS: Array<{ key: keyof NovelTypeRulebook; label: string; hint: string }> = [
  { key: "progression_rules", label: "成长规则", hint: "力量、能力与阶段推进的约束" },
  { key: "economy_rules", label: "资源规则", hint: "资源获取、交换与消耗逻辑" },
  { key: "quest_rules", label: "任务规则", hint: "目标、阻力与回报的约束" },
  { key: "faction_rules", label: "势力规则", hint: "阵营行动与关系反馈" },
  { key: "panel_rules", label: "面板规则", hint: "数值、提示与信息展示约束" },
  { key: "chapter_formula", label: "章节结构", hint: "每章推进与兑现方式" },
  { key: "forbidden_breaks", label: "禁止破坏", hint: "写作中不能违反的底线" },
];

type Draft = {
  id: string;
  name: string;
  description: string;
  keywords: string;
  core_promises: string;
  ledger_fields: string;
  rulebook: Record<keyof NovelTypeRulebook, string>;
  quality_checks: string;
  trope_templates: string;
  power_system_template: string;
  builtin: boolean;
};

function emptyRulebook(): NovelTypeRulebook {
  return {
    progression_rules: [],
    economy_rules: [],
    quest_rules: [],
    faction_rules: [],
    panel_rules: [],
    chapter_formula: [],
    forbidden_breaks: [],
  };
}

function toLines(items: string[]): string {
  return items.join("\n");
}

function fromLines(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function draftFromType(record: NovelType): Draft {
  const rules = { ...emptyRulebook(), ...record.rulebook };
  return {
    id: record.id,
    name: record.name,
    description: record.description,
    keywords: toLines(record.keywords),
    core_promises: toLines(record.core_promises),
    ledger_fields: toLines(record.ledger_fields),
    rulebook: Object.fromEntries(
      RULEBOOK_FIELDS.map(({ key }) => [key, toLines(rules[key])]),
    ) as Draft["rulebook"],
    quality_checks: toLines(record.quality_checks),
    trope_templates: JSON.stringify(record.trope_templates, null, 2),
    power_system_template: JSON.stringify(canonicalJson(record.power_system_template ?? {}), null, 2),
    builtin: record.builtin,
  };
}

function blankDraft(): Draft {
  return draftFromType({
    id: "",
    name: "",
    description: "",
    keywords: [],
    core_promises: [],
    ledger_fields: [],
    rulebook: emptyRulebook(),
    quality_checks: [],
    trope_templates: [],
    builtin: false,
  });
}

function parseDraft(draft: Draft): NovelTypeWriteRequest {
  let templates: unknown;
  let powerSystemTemplate: unknown;
  try {
    templates = JSON.parse(draft.trope_templates || "[]");
  } catch {
    throw new Error("套路模板必须是有效的 JSON 数组。");
  }
  if (!Array.isArray(templates) || templates.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
    throw new Error("套路模板必须是有效的 JSON 数组，数组中的每一项都应是对象。");
  }
  try {
    powerSystemTemplate = JSON.parse(draft.power_system_template || "{}");
  } catch {
    throw new Error("力量体系骨架必须是有效的 JSON 对象。");
  }
  if (!powerSystemTemplate || typeof powerSystemTemplate !== "object" || Array.isArray(powerSystemTemplate)) {
    throw new Error("力量体系骨架必须是 JSON 对象，不能是数组或空值。");
  }
  if (!draft.id.trim()) throw new Error("请填写类型 ID。");
  if (!/^[a-z][a-z0-9_-]{0,63}$/.test(draft.id.trim())) {
    throw new Error("类型 ID 需以小写字母开头，只能包含小写字母、数字、下划线或连字符。");
  }
  if (!draft.name.trim()) throw new Error("请填写类型名称。");

  return {
    id: draft.id.trim(),
    name: draft.name.trim(),
    description: draft.description.trim(),
    keywords: fromLines(draft.keywords),
    core_promises: fromLines(draft.core_promises),
    ledger_fields: fromLines(draft.ledger_fields),
    rulebook: Object.fromEntries(
      RULEBOOK_FIELDS.map(({ key }) => [key, fromLines(draft.rulebook[key])]),
    ) as NovelTypeRulebook,
    quality_checks: fromLines(draft.quality_checks),
    trope_templates: templates as Array<Record<string, unknown>>,
    power_system_template: powerSystemTemplate as Record<string, unknown>,
  };
}

function canonicalJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalJson);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalJson(item)]),
    );
  }
  return value;
}

function normalizedDraft(draft: Draft): string {
  let templates: unknown;
  let powerSystemTemplate: unknown;
  try {
    templates = canonicalJson(JSON.parse(draft.trope_templates || "[]"));
  } catch {
    templates = draft.trope_templates.trim();
  }
  try {
    powerSystemTemplate = canonicalJson(JSON.parse(draft.power_system_template || "{}"));
  } catch {
    powerSystemTemplate = draft.power_system_template.trim();
  }
  return JSON.stringify({
    id: draft.id.trim(),
    name: draft.name.trim(),
    description: draft.description.trim(),
    keywords: fromLines(draft.keywords),
    core_promises: fromLines(draft.core_promises),
    ledger_fields: fromLines(draft.ledger_fields),
    rulebook: Object.fromEntries(RULEBOOK_FIELDS.map(({ key }) => [key, fromLines(draft.rulebook[key])])),
    quality_checks: fromLines(draft.quality_checks),
    trope_templates: templates,
    power_system_template: powerSystemTemplate,
    builtin: draft.builtin,
  });
}

function naturalError(error: unknown): string {
  const message = error instanceof Error ? error.message : "操作失败，请稍后重试。";
  if (/failed to fetch|networkerror|network request failed|fetch failed|request timed out|aborterror/i.test(message)) {
    return "连接服务失败，请稍后重试。";
  }
  const used = message.match(/is used by project\(s\):\s*(.+)$/i);
  if (used) return `该类型正被项目 ${used[1]} 使用，暂时不能删除。`;
  if (/already exists|collides/i.test(message)) return "这个类型 ID 已存在，请换一个 ID。";
  if (/failed:\s*409/i.test(message)) return "请求与现有类型冲突，请检查类型 ID 或占用情况。";
  if (/built-in novel type cannot be deleted/i.test(message)) return "内置类型不能删除。";
  if (/Payload novel type ID must match/i.test(message)) return "类型 ID 与当前记录不一致，请重新载入后再试。";
  if (/failed:\s*422|validation|unprocessable|List values must|value_error|string_pattern|min_length|extra_forbidden/i.test(message)) {
    return "提交内容未通过校验，请检查必填项、类型 ID 和每行内容。";
  }
  if (/novel_type_not_found/i.test(message)) return "该类型已不存在，请重新载入列表。";
  return message;
}

export function NovelTypeLibraryClient() {
  const [records, setRecords] = useState<NovelType[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(blankDraft);
  const [baseline, setBaseline] = useState<Draft>(blankDraft);
  const [search, setSearch] = useState("");
  const [mode, setMode] = useState<"loading" | "idle" | "saving" | "deleting" | "error">("loading");
  const [message, setMessage] = useState("正在载入全局小说类型库...");
  const [isCreating, setIsCreating] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const editVersionRef = useRef(0);
  const draftRef = useRef(draft);
  const operationPendingRef = useRef(false);
  draftRef.current = draft;

  useEffect(() => {
    let active = true;
    setMode("loading");
    setMessage(loadAttempt ? "正在重新载入全局小说类型库..." : "正在载入全局小说类型库...");
    void fetchNovelTypes()
      .then((items) => {
        if (!active) return;
        setRecords(items);
        setIsCreating(false);
        const first = items[0];
        if (first) {
          const next = draftFromType(first);
          setSelectedId(first.id);
          setDraft(next);
          setBaseline(next);
          setMessage(`已载入 ${items.length} 个小说类型。`);
        } else {
          const next = blankDraft();
          setSelectedId(null);
          setDraft(next);
          setBaseline(next);
          setMessage("类型库为空，可以新建第一个自定义类型。");
        }
        setMode("idle");
      })
      .catch((error) => {
        if (!active) return;
        setRecords([]);
        setSelectedId(null);
        setIsCreating(false);
        setMode("error");
        setMessage(`小说类型库载入失败：${naturalError(error)}`);
      });
    return () => {
      active = false;
    };
  }, [loadAttempt]);

  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("zh-CN");
    if (!query) return records;
    return records.filter((record) =>
      [record.name, record.id, record.description, ...record.keywords].join(" ").toLocaleLowerCase("zh-CN").includes(query),
    );
  }, [records, search]);

  const busy = mode === "saving" || mode === "deleting";
  const initialLoadUnavailable = records.length === 0 && (mode === "loading" || mode === "error");
  const dirty = useMemo(() => normalizedDraft(draft) !== normalizedDraft(baseline), [baseline, draft]);

  function openRecord(record: NovelType) {
    const next = draftFromType(record);
    setSelectedId(record.id);
    setDraft(next);
    setBaseline(next);
    setIsCreating(false);
    setMode("idle");
    setMessage(`正在编辑“${record.name}”。`);
  }

  function selectRecord(record: NovelType) {
    if (operationPendingRef.current || busy || (!isCreating && selectedId === record.id)) return;
    if (dirty && !window.confirm("当前修改尚未保存，确定放弃吗？")) return;
    editVersionRef.current += 1;
    openRecord(record);
  }

  function beginCreating() {
    const next = blankDraft();
    setSelectedId(null);
    setDraft(next);
    setBaseline(next);
    setIsCreating(true);
    setMode("idle");
    setMessage("填写内容后创建自定义类型。");
  }

  function startCreating() {
    if (operationPendingRef.current || busy || isCreating) return;
    if (dirty && !window.confirm("当前修改尚未保存，确定放弃吗？")) return;
    editVersionRef.current += 1;
    beginCreating();
  }

  function resetDraft() {
    if (operationPendingRef.current || busy) return;
    editVersionRef.current += 1;
    if (isCreating) {
      const first = records[0];
      if (first) openRecord(first);
      else setDraft(blankDraft());
      return;
    }
    setDraft(baseline);
    setMode("idle");
    setMessage("已恢复到上次载入或保存的内容。");
  }

  async function save() {
    if (operationPendingRef.current || busy) return;
    let payload: NovelTypeWriteRequest;
    try {
      payload = parseDraft(draft);
    } catch (error) {
      setMode("error");
      setMessage(naturalError(error));
      return;
    }

    const editVersion = editVersionRef.current;
    const submittedDraft = normalizedDraft(draft);
    operationPendingRef.current = true;
    setMode("saving");
    setMessage(isCreating ? "正在创建类型..." : "正在保存修改...");
    try {
      const saved = isCreating ? await createNovelType(payload) : await updateNovelType(draft.id, payload);
      setRecords((current) => {
        const exists = current.some((record) => record.id === saved.id);
        return exists ? current.map((record) => (record.id === saved.id ? saved : record)) : [...current, saved];
      });
      if (editVersionRef.current !== editVersion || normalizedDraft(draftRef.current) !== submittedDraft) {
        setMode("idle");
        setMessage(`“${saved.name}”已保存；已保留当前正在编辑的内容。`);
        return;
      }
      const next = draftFromType(saved);
      setSelectedId(saved.id);
      setDraft(next);
      setBaseline(next);
      setIsCreating(false);
      setMode("idle");
      setMessage(`“${saved.name}”已保存。`);
    } catch (error) {
      setMode("error");
      setMessage(naturalError(error));
    } finally {
      operationPendingRef.current = false;
    }
  }

  async function remove() {
    if (operationPendingRef.current || busy || isCreating || draft.builtin || !selectedId) return;
    if (!window.confirm(`确定删除自定义类型“${draft.name}”吗？此操作无法撤销。`)) return;
    const editVersion = editVersionRef.current;
    const deletingDraft = normalizedDraft(draft);
    const deletingId = selectedId;
    operationPendingRef.current = true;
    setMode("deleting");
    setMessage("正在删除类型...");
    try {
      await deleteNovelType(deletingId);
      const remaining = records.filter((record) => record.id !== deletingId);
      setRecords(remaining);
      if (editVersionRef.current !== editVersion || normalizedDraft(draftRef.current) !== deletingDraft) {
        setMode("idle");
        setMessage(`“${draft.name}”已删除；已保留当前正在编辑的内容。`);
        return;
      }
      const next = remaining[0];
      editVersionRef.current += 1;
      if (next) openRecord(next);
      else beginCreating();
      setMessage(`“${draft.name}”已删除。`);
    } catch (error) {
      setMode("error");
      setMessage(naturalError(error));
    } finally {
      operationPendingRef.current = false;
    }
  }

  const statusRole = mode === "error" ? "alert" : "status";

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>写作规则</p>
          <h1>全局小说类型库</h1>
          <p>类型决定写作时加载的题材承诺、规则和检查；修改会影响之后使用该类型的生成。</p>
        </div>
        <button className={styles.primaryButton} type="button" onClick={startCreating} disabled={busy || initialLoadUnavailable}>
          新建类型
        </button>
      </header>

      <p className={`${styles.status} ${mode === "error" ? styles.statusError : ""}`} role={statusRole} aria-live="polite">
        <span>{mode === "loading" ? "载入中" : mode === "saving" ? "保存中" : mode === "deleting" ? "删除中" : mode === "error" ? "操作失败" : "就绪"}</span>
        {message}
      </p>

      {initialLoadUnavailable ? (
        <section className={styles.loadPanel} aria-label="小说类型库状态">
          <h2>{mode === "loading" ? "正在载入类型库" : "无法载入类型库"}</h2>
          <p>{message}</p>
          {mode === "error" ? (
            <button className={styles.secondaryButton} type="button" onClick={() => setLoadAttempt((current) => current + 1)}>
              重新加载
            </button>
          ) : null}
        </section>
      ) : (
      <div className={styles.workspace}>
        <aside className={styles.library} aria-label="小说类型列表">
          <label className={styles.searchLabel}>
            <span>搜索类型</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="名称、ID 或关键词" type="search" />
          </label>
          {mode === "loading" ? (
            <p className={styles.empty}>正在读取类型列表...</p>
          ) : filtered.length ? (
            <div className={styles.typeList}>
              {filtered.map((record) => (
                <button
                  className={`${styles.typeItem} ${selectedId === record.id && !isCreating ? styles.typeItemSelected : ""}`}
                  type="button"
                  key={record.id}
                  onClick={() => selectRecord(record)}
                  disabled={busy}
                  aria-pressed={selectedId === record.id && !isCreating}
                >
                  <span className={styles.typeTitle}>
                    <strong>{record.name}</strong>
                    <small>{record.builtin ? "内置" : "自定义"}</small>
                  </span>
                  <span className={styles.typeDescription}>{record.description || "暂无简短介绍"}</span>
                  <code>{record.id}</code>
                </button>
              ))}
            </div>
          ) : (
            <p className={styles.empty}>{records.length ? "没有匹配的类型。" : "类型库为空。"}</p>
          )}
        </aside>

        <form className={styles.editor} aria-label="小说类型编辑器" onSubmit={(event) => { event.preventDefault(); void save(); }}>
          <div className={styles.editorHeader}>
            <div>
              <p className={styles.eyebrow}>{isCreating ? "新建自定义类型" : draft.builtin ? "编辑内置类型" : "编辑自定义类型"}</p>
              <h2>{isCreating ? "未命名类型" : draft.name || "类型详情"}</h2>
            </div>
            <span className={styles.identity}>{isCreating ? "待创建" : draft.builtin ? "内置" : "自定义"}</span>
          </div>

          <section className={styles.section}>
            <h3>基本信息</h3>
            <div className={styles.twoColumns}>
              <Field label="类型 ID" hint={isCreating ? "创建后不可修改；使用小写字母、数字、下划线或连字符。" : "创建后不可修改。"}>
                <input value={draft.id} disabled={!isCreating || busy} onChange={(event) => setDraft({ ...draft, id: event.target.value })} />
              </Field>
              <Field label="类型名称">
                <input value={draft.name} disabled={busy} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
              </Field>
            </div>
            <Field label="简短介绍">
              <textarea rows={3} value={draft.description} disabled={busy} onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
            </Field>
            <Field label="关键词（每行一项）">
              <textarea rows={4} value={draft.keywords} disabled={busy} onChange={(event) => setDraft({ ...draft, keywords: event.target.value })} />
            </Field>
          </section>

          <section className={styles.section}>
            <h3>写作承诺与账本</h3>
            <div className={styles.twoColumns}>
              <Field label="核心承诺（每行一项）">
                <textarea rows={7} value={draft.core_promises} disabled={busy} onChange={(event) => setDraft({ ...draft, core_promises: event.target.value })} />
              </Field>
              <Field label="账本字段（每行一项）">
                <textarea rows={7} value={draft.ledger_fields} disabled={busy} onChange={(event) => setDraft({ ...draft, ledger_fields: event.target.value })} />
              </Field>
            </div>
          </section>

          <section className={styles.section}>
            <div className={styles.sectionHeading}>
              <h3>规则手册</h3>
              <p>每组每行一条规则。</p>
            </div>
            <div className={styles.ruleGrid}>
              {RULEBOOK_FIELDS.map(({ key, label, hint }) => (
                <Field key={key} label={label} hint={hint}>
                  <textarea
                    rows={5}
                    value={draft.rulebook[key]}
                    disabled={busy}
                    onChange={(event) => setDraft({ ...draft, rulebook: { ...draft.rulebook, [key]: event.target.value } })}
                  />
                </Field>
              ))}
            </div>
          </section>

          <section className={styles.section}>
            <h3>检查与模板</h3>
            <Field label="质量检查（每行一项）">
              <textarea rows={6} value={draft.quality_checks} disabled={busy} onChange={(event) => setDraft({ ...draft, quality_checks: event.target.value })} />
            </Field>
            <Field label="套路模板（JSON 数组）" hint='格式示例：[ { "id": "template_id", "name": "模板名", "beats": [] } ]。保存前会校验数组和对象结构。'>
              <textarea className={styles.jsonInput} rows={14} value={draft.trope_templates} disabled={busy} spellCheck={false} onChange={(event) => setDraft({ ...draft, trope_templates: event.target.value })} />
            </Field>
            <Field label="力量体系骨架 JSON" hint="使用 JSON 对象定义体系形式、阶段和路线约束；空骨架填写 {}。">
              <textarea className={styles.jsonInput} rows={14} value={draft.power_system_template} disabled={busy} spellCheck={false} onChange={(event) => setDraft({ ...draft, power_system_template: event.target.value })} />
            </Field>
          </section>

          <footer className={styles.actions}>
            <div>
              <button className={styles.primaryButton} type="submit" disabled={busy || mode === "loading"}>
                {mode === "saving" ? "保存中..." : isCreating ? "创建类型" : "保存修改"}
              </button>
              <button className={styles.secondaryButton} type="button" onClick={resetDraft} disabled={busy || mode === "loading"}>
                取消 / 重置
              </button>
            </div>
            <button className={styles.dangerButton} type="button" onClick={() => void remove()} disabled={busy || isCreating || draft.builtin || !selectedId}>
              {mode === "deleting" ? "删除中..." : "删除类型"}
            </button>
          </footer>
        </form>
      </div>
      )}
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactElement }) {
  return (
    <label className={styles.field}>
      <span>{label}</span>
      {hint ? <small>{hint}</small> : null}
      {children}
    </label>
  );
}
