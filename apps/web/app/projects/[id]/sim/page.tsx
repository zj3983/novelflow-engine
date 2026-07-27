"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { useChapterDetail } from "../../../../components/ws/useChapterDetail";
import type { ChapterBundle, StoryCharacter } from "../../../../lib/api";
import { cleanLines } from "../../../../lib/worldDisplay";

type Reaction = {
  name: string;
  role: string;
  lines: string[];
};

type ActionLike = {
  name?: string;
  goal?: string;
  action?: string;
  priority?: number;
  emotion?: string;
};

type PlotSimulation = {
  reader_hook?: string;
  chapter_desire?: string;
  obstacle_chain?: string[];
  choice_point?: string;
  payoff?: string;
  cost?: string;
  emotional_turn?: string;
  outsider_misread?: string;
  ending_hook?: string;
};

type SimulationPlan = {
  plot_simulation?: PlotSimulation;
  character_performance?: Array<{
    name?: string;
    role?: string;
    risk_posture?: string;
    action_style?: string;
    decision_rules?: string[];
  }>;
  npc_boundaries?: Array<{ name?: string; service_role?: string; interaction_rules?: string[] }>;
  craft_pack?: Record<string, unknown>;
};

type WorldPulseLatest = {
  pulse_index?: number;
  chapter_number?: number;
  visible_at_chapter?: number;
  public_traces?: string[];
  pressure_points?: string[];
  summary?: string;
};

type VisibilityInboxItem = {
  channel?: string;
  visible_at_chapter?: number;
  source_chapter?: number;
  hint?: string;
  trace?: string;
  summary?: string;
};

function compactText(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return `${value}`;
  if (!value || typeof value !== "object") return fallback;
  const entries = Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => {
      if (typeof item === "string" || typeof item === "number") return `${key}: ${item}`;
      if (Array.isArray(item)) return `${key}: ${item.join("、")}`;
      return "";
    })
    .filter(Boolean);
  return entries.join("；") || fallback;
}

function asTextList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => compactText(item)).filter(Boolean).slice(0, 5);
}

function worldPulseLatest(bundle: ChapterBundle): WorldPulseLatest | null {
  const latest = bundle.simulation_status?.world_pulse?.latest;
  if (!latest || typeof latest !== "object") return null;
  return latest as WorldPulseLatest;
}

function visibilityInbox(bundle: ChapterBundle): VisibilityInboxItem[] {
  const inbox = bundle.simulation_status?.visibility_inbox;
  if (!Array.isArray(inbox)) return [];
  return inbox.filter((item): item is VisibilityInboxItem => Boolean(item && typeof item === "object")).slice(-6);
}

function worldPulseLine(pulse: WorldPulseLatest): string {
  const parts = [
    typeof pulse.pulse_index === "number" ? `脉冲 ${pulse.pulse_index}` : "",
    typeof pulse.chapter_number === "number" ? `源自第 ${pulse.chapter_number} 章` : "",
    typeof pulse.visible_at_chapter === "number" ? `第 ${pulse.visible_at_chapter} 章可见` : "",
  ].filter(Boolean);
  return parts.join(" / ") || pulse.summary || "暂无世界响应记录。";
}

function eventPlanLine(bundle: ChapterBundle): string {
  const plan = bundle.event_plan;
  return (
    plan?.turn ||
    plan?.pivot ||
    plan?.collision ||
    bundle.event_beat?.pivot ||
    bundle.event_beat?.turn ||
    bundle.chapter_intent?.next_focus ||
    bundle.next_outline ||
    ""
  );
}

function orderedActions(bundle: ChapterBundle): ActionLike[] {
  return (bundle.event_plan?.ordered_actions?.length ? bundle.event_plan.ordered_actions : bundle.character_moves ?? []) as ActionLike[];
}

function addReaction(map: Map<string, Reaction>, name: string, role: string, line: string) {
  const cleanName = name.trim();
  const cleanLine = line.trim();
  if (!cleanName || !cleanLine) return;
  const current = map.get(cleanName) ?? { name: cleanName, role, lines: [] };
  if (role && !current.role) current.role = role;
  if (!current.lines.includes(cleanLine)) current.lines.push(cleanLine);
  map.set(cleanName, current);
}

function addSurfaceReaction(map: Map<string, Reaction>, line: string) {
  if (line.includes("交易行") || line.includes("木牌")) {
    addReaction(map, "交易行告示牌", "市场机制", line);
  }
  if (line.includes("频道") || line.includes("玩家")) {
    addReaction(map, "公共频道", "玩家群体", line);
  }
  if (line.includes("洛婶") || line.includes("药剂铺")) {
    addReaction(map, "药剂师洛婶", "服务NPC", line);
  }
  if (line.includes("系统") || line.includes("预警") || line.includes("公告")) {
    addReaction(map, "系统公告", "系统机制", line);
  }
}

function chapterReactions(bundle: ChapterBundle, characters: StoryCharacter[]): Reaction[] {
  const map = new Map<string, Reaction>();
  const chapterNumber = bundle.chapter_number;
  const actions = orderedActions(bundle);
  const simulationPlan = (bundle.simulation_plan ?? {}) as SimulationPlan;

  for (const action of actions) {
    if (!action.name) continue;
    const line = [action.emotion, action.goal, action.action].filter(Boolean).join("：");
    addReaction(map, action.name, "角色", line);
  }

  for (const item of simulationPlan.character_performance ?? []) {
    if (!item.name) continue;
    const line = item.risk_posture || item.action_style || item.decision_rules?.join("；") || "";
    addReaction(map, item.name, item.role || "角色", line);
  }

  for (const item of simulationPlan.npc_boundaries ?? []) {
    if (!item.name) continue;
    addReaction(map, item.name, item.service_role || "NPC", item.interaction_rules?.join("；") || item.service_role || "");
  }

  for (const event of bundle.world_events ?? []) {
    if (event.actor) {
      addReaction(
        map,
        event.actor,
        event.actor.includes("系统") ? "系统机制" : "世界实体",
        [event.action, event.target, event.location].filter(Boolean).join(" → "),
      );
    }
  }

  for (const line of bundle.event_plan?.world_reactions ?? []) {
    addSurfaceReaction(map, line);
  }

  for (const character of characters) {
    const role = character.role || character.lifecycle_state || "角色";
    for (const memory of character.memory ?? []) {
      if (memory.includes(`第${chapterNumber}章`) || memory.includes(`第 ${chapterNumber} 章`)) {
        addReaction(map, character.name, role, memory);
      }
    }
  }

  return Array.from(map.values())
    .map((reaction) => ({ ...reaction, lines: reaction.lines.slice(0, 4) }))
    .filter((reaction) => reaction.lines.length > 0)
    .slice(0, 12);
}

function craftHighlights(bundle: ChapterBundle): string[] {
  const simulationPlan = (bundle.simulation_plan ?? {}) as SimulationPlan;
  const pack = simulationPlan.craft_pack;
  if (!pack) return [];
  const lines: string[] = [];
  const showTell = pack.show_vs_tell as { formula?: string } | undefined;
  const beatShape = pack.scene_beat_shape as { shape?: string[] } | undefined;
  const detailBudget = pack.detail_budget as { per_scene_new_world_details?: number; per_chapter_new_terms?: number } | undefined;
  const microHooks = pack.micro_hooks as { interval_chars?: string; chapter_end_hook?: string } | undefined;
  const repetition = pack.repetition_control as { near_duplicate_check?: string } | undefined;
  if (showTell?.formula) lines.push(`显隐转换：${showTell.formula}`);
  if (beatShape?.shape?.length) lines.push(`场景节拍：${beatShape.shape.join(" / ")}`);
  if (detailBudget) {
    lines.push(`细节预算：每场最多 ${detailBudget.per_scene_new_world_details ?? 2} 个新世界细节，每章最多 ${detailBudget.per_chapter_new_terms ?? 1} 个新名词`);
  }
  if (microHooks?.interval_chars) lines.push(`页内微钩子：每 ${microHooks.interval_chars} 字留一个未结算问题`);
  if (repetition?.near_duplicate_check) lines.push(`复读检测：${repetition.near_duplicate_check}`);
  return lines.slice(0, 5);
}

function plotSimulation(bundle: ChapterBundle): PlotSimulation | null {
  const simulationPlan = (bundle.simulation_plan ?? {}) as SimulationPlan;
  const plot = simulationPlan.plot_simulation;
  if (!plot || typeof plot !== "object") return null;
  return plot;
}

function plotLineItems(plot: PlotSimulation): Array<{ label: string; value: string }> {
  return [
    { label: "读者钩子", value: compactText(plot.reader_hook) },
    { label: "主角目标", value: compactText(plot.chapter_desire) },
    { label: "选择点", value: compactText(plot.choice_point) },
    { label: "爽点兑现", value: compactText(plot.payoff) },
    { label: "代价", value: compactText(plot.cost) },
    { label: "情绪转折", value: compactText(plot.emotional_turn) },
    { label: "外人误判", value: compactText(plot.outsider_misread) },
    { label: "章末钩子", value: compactText(plot.ending_hook) },
  ].filter((item) => item.value);
}

export default function SimulationPage() {
  const { project, story, chapterIndex, error, encodedProjectId, projectId, refreshVersion } = useProjectWorkspace();
  const simulationIndex = useMemo(() => chapterIndex.filter((entry) => entry.has_simulation).reverse(), [chapterIndex]);
  const [selectedChapter, setSelectedChapter] = useState(0);

  useEffect(() => {
    if (!simulationIndex.length) {
      setSelectedChapter(0);
      return;
    }
    if (!simulationIndex.some((entry) => entry.chapter_number === selectedChapter)) {
      setSelectedChapter(simulationIndex[0].chapter_number);
    }
  }, [selectedChapter, simulationIndex]);

  const { chapter, loading: chapterLoading, error: chapterError } = useChapterDetail({
    projectId,
    story: story ?? null,
    chapterNumber: selectedChapter,
    refreshVersion,
  });
  const bundles = chapter && chapter.chapter_number === selectedChapter ? [chapter] : [];
  const latest = chapterIndex.at(-1);
  const characters = story?.characters ?? [];

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="世界响应"
        subtitle={project?.current_focus || latest?.next_focus || "章节规划确定本章剧情，世界响应只检查人物边界、信息可见性和连续性。"}
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : null}

      {simulationIndex.length > 1 ? (
        <label className="ws-search">
          <span>响应章节</span>
          <select className="ws-input" value={selectedChapter} onChange={(event) => setSelectedChapter(Number(event.target.value))}>
            {simulationIndex.map((entry) => (
              <option key={entry.chapter_number} value={entry.chapter_number}>
                第 {entry.chapter_number} 章：{entry.chapter_title || "未命名"}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {chapterError ? <p className="ws-inline-error" role="alert">章节加载失败：{chapterError}</p> : null}
      {chapterLoading && !chapter ? <p className="ws-card__hint">正在加载章节...</p> : null}

      {bundles.length > 0 ? (
        <div className="ws-sim-list">
          {bundles.map((bundle) => {
            const actions = orderedActions(bundle);
            const reactions = chapterReactions(bundle, characters);
            const scenes = bundle.scene_cards ?? [];
            const events = bundle.world_events ?? [];
            const facts = cleanLines(bundle.chapter_summary?.facts, 4);
            const status = bundle.simulation_status;
            const crafts = craftHighlights(bundle);
            const pulse = worldPulseLatest(bundle);
            const inbox = visibilityInbox(bundle);
            const publicTraces = asTextList(pulse?.public_traces);
            const pressurePoints = asTextList(pulse?.pressure_points);
            const plot = plotSimulation(bundle);

            return (
              <section className="ws-card ws-sim-chapter" key={bundle.chapter_number}>
                <div className="ws-section-head">
                  <div>
                    <p className="ws-card__title">第 {bundle.chapter_number} 章响应记录</p>
                    <h2 className="ws-sim-chapter__title">{bundle.chapter_title || bundle.chapter_intent?.chapter_title || "未命名"}</h2>
                  </div>
                  <Link href={`/projects/${encodedProjectId}/write?chapter=${bundle.chapter_number}`} className="ws-text-link">
                    看正文
                  </Link>
                </div>

                <p className="ws-card__hint">
                  {bundle.chapter_summary?.summary || bundle.chapter_intent?.next_focus || bundle.next_outline || "暂无摘要。"}
                </p>

                <div className="ws-sim-grid">
                  <div className="ws-simple-item">
                    <strong>章节目标</strong>
                    <span>{eventPlanLine(bundle) || "暂无焦点。"}</span>
                  </div>
                  <div className="ws-simple-item">
                    <strong>冲突 / 赌注</strong>
                    <span>
                      {bundle.conflict_summary?.stakes ||
                        bundle.conflict_summary?.summary ||
                        compactText(bundle.chapter_intent?.primary_conflict, "暂无冲突记录。")}
                    </span>
                  </div>
                  <div className="ws-simple-item">
                    <strong>运行状态</strong>
                    <span>
                      {status
                        ? `${status.ok ? "完整校验" : "降级校验"} · ${status.mode || "unknown"}`
                        : bundle.simulation_plan
                          ? "完整校验"
                          : "章节回填记录"}
                    </span>
                  </div>
                </div>

                {plot ? (
                  <div className="ws-character-block">
                    <strong>章节计划明细</strong>
                    <div className="ws-sim-grid">
                      {plotLineItems(plot).map((item) => (
                        <div className="ws-simple-item" key={item.label}>
                          <strong>{item.label}</strong>
                          <span>{item.value}</span>
                        </div>
                      ))}
                    </div>
                    {plot.obstacle_chain?.length ? (
                      <ul>
                        {plot.obstacle_chain.slice(0, 5).map((line, index) => (
                          <li key={`${line}-${index}`}>{line}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ) : null}

                {pulse || inbox.length > 0 ? (
                  <div className="ws-character-block">
                    <strong>世界响应</strong>
                    <p className="ws-card__hint">{pulse ? worldPulseLine(pulse) : "本章暂无新的世界响应。"}</p>
                    {publicTraces.length > 0 ? (
                      <ul>
                        {publicTraces.map((line, index) => (
                          <li key={`trace-${index}`}>{line}</li>
                        ))}
                      </ul>
                    ) : null}
                    {pressurePoints.length > 0 ? (
                      <ul>
                        {pressurePoints.map((line, index) => (
                          <li key={`pressure-${index}`}>{line}</li>
                        ))}
                      </ul>
                    ) : null}
                    {inbox.length > 0 ? (
                      <ul>
                        {inbox.map((item, index) => (
                          <li key={`${item.channel || "inbox"}-${index}`}>
                            {[item.channel, item.hint || item.trace || item.summary, item.visible_at_chapter ? `第 ${item.visible_at_chapter} 章可见` : ""]
                              .filter(Boolean)
                              .join("：")}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ) : null}

                {crafts.length > 0 ? (
                  <div className="ws-character-block">
                    <strong>写作技巧</strong>
                    <ul>
                      {crafts.map((line, index) => (
                        <li key={`${line}-${index}`}>{line}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {reactions.length > 0 ? (
                  <div className="ws-character-block">
                    <strong>人物响应</strong>
                    <div className="ws-reaction-list">
                      {reactions.map((reaction) => (
                        <article className="ws-reaction-item" key={reaction.name}>
                          <h3>{reaction.name}</h3>
                          <p>{reaction.role}</p>
                          <ul>
                            {reaction.lines.map((line, index) => (
                              <li key={`${line}-${index}`}>{line}</li>
                            ))}
                          </ul>
                        </article>
                      ))}
                    </div>
                  </div>
                ) : null}

                {actions.length > 0 ? (
                  <div className="ws-character-block">
                    <strong>角色动作</strong>
                    <ul>
                      {actions.slice(0, 8).map((action, index) => (
                        <li key={`${action.name || "action"}-${index}`}>
                          {[action.name, action.goal, action.action].filter(Boolean).join("：")}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {scenes.length > 0 ? (
                  <div className="ws-character-block">
                    <strong>场景卡</strong>
                    <ul>
                      {scenes.slice(0, 8).map((scene, index) => (
                        <li key={scene.scene_id || index}>
                          {[scene.location, scene.purpose || scene.conflict || scene.ending_pressure].filter(Boolean).join("：")}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {events.length > 0 ? (
                  <div className="ws-character-block">
                    <strong>世界事件</strong>
                    <ul>
                      {events.slice(0, 8).map((event, index) => (
                        <li key={event.event_id || index}>
                          {[event.actor, event.action, event.target, event.location].filter(Boolean).join(" → ")}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {facts.length > 0 ? (
                  <div className="ws-character-block">
                    <strong>连续性记录</strong>
                    <ul>
                      {facts.map((fact, index) => (
                        <li key={`${fact}-${index}`}>{fact}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {bundle.next_outline ? (
                  <div className="ws-character-block">
                    <strong>下一章焦点</strong>
                    <p className="ws-card__hint">{bundle.next_outline}</p>
                  </div>
                ) : null}
              </section>
            );
          })}
        </div>
      ) : !chapterLoading && !chapterError ? (
        <section className="ws-card">
          <p className="ws-card__title">世界响应</p>
          <p className="ws-card__hint">还没有世界响应记录。</p>
        </section>
      ) : null}
    </div>
  );
}
