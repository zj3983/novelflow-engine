"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  checkFileProjectCharacterConsistency,
  fetchFileProjectCharacterTimeline,
  type CharacterConsistencyWarning,
  type CharacterPlanContext,
  type CharacterTimelineCategory,
  type CharacterTimelineResponse,
} from "../../lib/api";

type CharacterOption = { name: string };
type InspectionTab = "timeline" | "consistency";

const CATEGORY_LABELS: Record<CharacterTimelineCategory | "all", string> = {
  all: "全部",
  state: "状态",
  location: "位置",
  emotion: "情绪",
  relationship: "关系",
  progression: "成长",
  skill: "技能",
  equipment: "装备",
  knowledge: "知识",
  appearance: "出场",
};

function displayValue(value: unknown): string {
  if (value === undefined || value === null || value === "") return "未知";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function warningIcon(warning: CharacterConsistencyWarning): string {
  if (warning.severity === "error") return "🔴";
  if (warning.severity === "info") return "🔵";
  return "🟡";
}

export function CharacterInspectionPanel({
  projectId,
  encodedProjectId,
  characters,
  currentChapter,
  refreshVersion,
}: {
  projectId: string;
  encodedProjectId: string;
  characters: CharacterOption[];
  currentChapter: number;
  refreshVersion?: number;
}) {
  const [selectedName, setSelectedName] = useState("");
  const [tab, setTab] = useState<InspectionTab>("timeline");
  const [timeline, setTimeline] = useState<CharacterTimelineResponse | null>(null);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [timelineError, setTimelineError] = useState<string | null>(null);
  const [category, setCategory] = useState<CharacterTimelineCategory | "all">("all");
  const [startChapter, setStartChapter] = useState("");
  const [endChapter, setEndChapter] = useState("");
  const [targetChapter, setTargetChapter] = useState("");
  const [planText, setPlanText] = useState("");
  const [warnings, setWarnings] = useState<CharacterConsistencyWarning[] | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);

  useEffect(() => {
    if (characters.length === 0) {
      setSelectedName("");
      return;
    }
    if (!characters.some((character) => character.name === selectedName)) {
      setSelectedName(characters[0].name);
    }
  }, [characters, selectedName]);

  useEffect(() => {
    if (!selectedName) return;
    let cancelled = false;
    setTimelineLoading(true);
    setTimelineError(null);
    setTimeline(null);
    setWarnings(null);
    const defaultTarget = Math.max(1, currentChapter + 1);
    setTargetChapter(String(defaultTarget));
    setPlanText(JSON.stringify({ character_name: selectedName }, null, 2));
    fetchFileProjectCharacterTimeline(projectId, selectedName)
      .then((result) => {
        if (!cancelled) setTimeline(result);
      })
      .catch((error: unknown) => {
        if (!cancelled) setTimelineError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (!cancelled) setTimelineLoading(false);
      });
    return () => { cancelled = true; };
  }, [currentChapter, projectId, refreshVersion, selectedName]);

  const filteredEvents = useMemo(() => {
    const start = startChapter.trim() ? Number(startChapter) : undefined;
    const end = endChapter.trim() ? Number(endChapter) : undefined;
    return (timeline?.events ?? []).filter((event) => (
      (category === "all" || event.category === category)
      && (start === undefined || event.chapter_number >= start)
      && (end === undefined || event.chapter_number <= end)
    ));
  }, [category, endChapter, startChapter, timeline]);

  const runConsistencyCheck = async () => {
    if (!selectedName) return;
    const target = Number(targetChapter);
    if (!Number.isInteger(target) || target < 1) {
      setCheckError("请输入不小于 1 的目标章节。" );
      return;
    }
    let context: CharacterPlanContext;
    try {
      const parsed: unknown = JSON.parse(planText || "{}");
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("object_required");
      context = parsed as CharacterPlanContext;
    } catch {
      setCheckError("结构化计划 JSON 格式错误，请输入对象。" );
      return;
    }
    setChecking(true);
    setCheckError(null);
    try {
      const result = await checkFileProjectCharacterConsistency(projectId, selectedName, target, {
        ...context,
        character_name: selectedName,
      });
      setWarnings(result.warnings);
    } catch (error: unknown) {
      setCheckError(error instanceof Error ? error.message : String(error));
    } finally {
      setChecking(false);
    }
  };

  if (characters.length === 0) return null;

  return (
    <section className="ws-card ws-character-inspection" aria-labelledby="character-inspection-title">
      <div className="ws-section-head">
        <div>
          <h2 id="character-inspection-title">历史检查</h2>
          <p className="ws-card__hint">只读取已有结构化证据；不会修改角色卡或正文。</p>
        </div>
        <label>
          <span>角色</span>
          <select aria-label="检查角色" value={selectedName} onChange={(event) => setSelectedName(event.target.value)}>
            {characters.map((character) => <option key={character.name} value={character.name}>{character.name}</option>)}
          </select>
        </label>
      </div>

      <div className="ws-tabs" role="tablist" aria-label="角色历史检查">
        <button type="button" role="tab" aria-selected={tab === "timeline"} className={`ws-button${tab === "timeline" ? " ws-button--primary" : ""}`} onClick={() => setTab("timeline")}>时间线</button>
        <button type="button" role="tab" aria-selected={tab === "consistency"} className={`ws-button${tab === "consistency" ? " ws-button--primary" : ""}`} onClick={() => setTab("consistency")}>一致性</button>
      </div>

      {tab === "timeline" ? (
        <div role="tabpanel" aria-label="角色时间线">
          <div className="ws-panel-grid">
            <label><span>分类</span><select aria-label="时间线分类" value={category} onChange={(event) => setCategory(event.target.value as CharacterTimelineCategory | "all")}>
              {(Object.keys(CATEGORY_LABELS) as Array<CharacterTimelineCategory | "all">).map((key) => <option key={key} value={key}>{CATEGORY_LABELS[key]}</option>)}
            </select></label>
            <label><span>起始章节</span><input aria-label="时间线起始章节" type="number" min={0} value={startChapter} onChange={(event) => setStartChapter(event.target.value)} /></label>
            <label><span>结束章节</span><input aria-label="时间线结束章节" type="number" min={0} value={endChapter} onChange={(event) => setEndChapter(event.target.value)} /></label>
          </div>
          {timelineLoading ? <p className="ws-card__hint">正在读取历史记录……</p> : null}
          {timelineError ? <p className="ws-error-text">加载时间线失败：{timelineError}</p> : null}
          {!timelineLoading && !timelineError && filteredEvents.length === 0 ? (
            <p className="ws-card__hint">
              {timeline?.history_status === "no_evidence" ? "暂无可验证的历史记录。" : "当前筛选范围暂无变化记录。"}
            </p>
          ) : null}
          <div className="ws-character-inspection__events">
            {[...filteredEvents].reverse().map((event) => (
              <article className="ws-character-inspection__event" data-testid="character-timeline-event" key={event.event_id}>
                <div className="ws-character-inspection__event-head">
                  <Link className="ws-text-link" href={`/projects/${encodedProjectId}/review?chapter=${event.chapter_number}`}>第 {event.chapter_number} 章</Link>
                  <strong>{event.title}</strong>
                  <span>{CATEGORY_LABELS[event.category]}</span>
                </div>
                <p>{event.summary}</p>
                {event.before !== undefined || event.after !== undefined ? <p className="ws-card__hint">变化：{displayValue(event.before)} → {displayValue(event.after)}</p> : null}
              </article>
            ))}
          </div>
        </div>
      ) : (
        <div role="tabpanel" aria-label="角色一致性检查">
          <div className="ws-panel-grid">
            <label><span>目标章节</span><input aria-label="一致性目标章节" type="number" min={1} value={targetChapter} onChange={(event) => setTargetChapter(event.target.value)} /></label>
          </div>
          <label className="ws-character-inspection__plan"><span>结构化计划 JSON</span><textarea aria-label="结构化计划 JSON" rows={7} value={planText} onChange={(event) => setPlanText(event.target.value)} /></label>
          <p className="ws-card__hint">可填写 location、skills_used、equipment_used、knowledge_fact_ids、relationship_expectations；不读取正文语义。</p>
          <button type="button" className="ws-button ws-button--primary" disabled={checking} onClick={runConsistencyCheck}>{checking ? "检查中……" : "运行一致性检查"}</button>
          {checkError ? <p className="ws-error-text">检查失败：{checkError}</p> : null}
          {warnings && warnings.length === 0 ? <p className="ws-card__hint">未发现可由结构化证据确认的冲突。</p> : null}
          <div className="ws-character-inspection__warnings">
            {(warnings ?? []).map((warning, index) => (
              <article className="ws-character-inspection__warning" data-testid="character-consistency-warning" key={`${warning.code}-${index}`}>
                <strong>{warningIcon(warning)} 第 {warning.target_chapter} 章 · {warning.code}</strong>
                <p>{warning.message}</p>
                {warning.suggestion ? <p className="ws-card__hint">建议：{warning.suggestion}</p> : null}
              </article>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
