"use client";

import Link from "next/link";
import { Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import {
  fetchProjectForeshadowing,
  fetchProjectOutline,
  fetchOutlineGenerationCheckpoints,
  generateProjectOutline,
  updateProjectForeshadowing,
  updateProjectOutline,
  type ForeshadowingEntry,
  type ForeshadowingStatus,
  type OutlineGenerationMode,
  type OutlineGenerationCheckpointResponse,
  type OutlineGenerationPhaseId,
  type ProjectChapterOutline,
  type ProjectOutline,
  type ProjectOutlineArc,
} from "../../../../lib/api";
import { isGameWebnovel } from "../../../../lib/worldDisplay";

type OutlineTab = "overall" | "arcs" | "chapters" | "foreshadowing";
type ForeshadowingFilter = "active" | "ended" | "all";

const TABS: Array<{ id: OutlineTab; label: string }> = [
  { id: "overall", label: "总纲" },
  { id: "arcs", label: "阶段大纲" },
  { id: "chapters", label: "章节大纲" },
  { id: "foreshadowing", label: "伏笔" },
];

type PositioningField = keyof ProjectOutline["overall"]["positioning"];
type CoreAdvantageField = keyof ProjectOutline["overall"]["core_advantage"];
type CentralMysteryTextField = Exclude<keyof ProjectOutline["overall"]["central_mystery"], "reveal_path">;
type ProtagonistDriveField = keyof ProjectOutline["overall"]["protagonist_drive"];

const POSITIONING_FIELDS: Array<{ field: PositioningField; label: string }> = [
  { field: "protagonist_profile", label: "主角起点" },
  { field: "inciting_incident", label: "故事契机" },
  { field: "failure_stakes", label: "失败后果" },
  { field: "excitement_point", label: "创作兴奋点" },
  { field: "target_audience", label: "目标读者" },
  { field: "reader_promise", label: "读者持续能得到什么" },
];

const FORESHADOWING_FILTERS: Array<{ id: ForeshadowingFilter; label: string }> = [
  { id: "active", label: "未回收" },
  { id: "ended", label: "已结束" },
  { id: "all", label: "全部" },
];

const FORESHADOWING_STATUS_LABELS: Record<ForeshadowingStatus, string> = {
  open: "待推进",
  reinforced: "已强化",
  resolved: "已回收",
  expired: "已失效",
};

const OUTLINE_DETAIL_WINDOW = 10;
const OUTLINE_EXTENSION_WARNING = 3;

const OUTLINE_PHASE_LABELS: Record<OutlineGenerationPhaseId, string> = {
  outline_foundation: "总纲与阶段大纲",
  character_roster: "开篇角色表",
  chapter_window: "章节细纲",
};

const OUTLINE_PHASE_STATUS: Record<string, string> = {
  waiting: "等待",
  running: "正在生成",
  completed: "已保存",
  failed: "失败",
};

const GAME_PACING_STAGES = [
  { id: "newcomer_rise", label: "新手期锋芒" },
  { id: "server_dominance", label: "全服竞争与现实端倪" },
  { id: "dual_world_escalation", label: "双线交织与世界异变" },
  { id: "truth_and_final_war", label: "真相与终局" },
] as const;

function newArcId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `arc-${Date.now()}`;
}

function newArc(index: number): ProjectOutlineArc {
  const startChapter = index === 0 ? 1 : index * 10 + 1;
  return {
    id: newArcId(),
    title: "",
    start_chapter: startChapter,
    end_chapter: startChapter + 9,
    pacing_stage_id: "",
    goal: "",
    obstacle: "",
    payoff: "",
    emotional_curve: "",
    key_results: [],
    hook_plan: "",
    irreversible_change: "",
    end_state: "",
    stage_antagonist: "",
    long_term_antagonist_traces: [],
    game_line_payoff: "",
    reality_line_payoff: "",
    extension_gate: {
      continue_route: "",
      close_route: "",
    },
    active_long_term_lines: [],
    core_loop: "",
    escalations: [],
    midpoint_turn: "",
    climax: "",
    relationship_changes: [],
    foreshadowing_in: [],
    foreshadowing_out: [],
    next_arc_entry: "",
  };
}

function newChapter(chapterNumber: number): ProjectChapterOutline {
  return {
    chapter_number: chapterNumber,
    title: "",
    goal: "",
    obstacle: "",
    action: "",
    turn: "",
    payoff: "",
    ending_hook: "",
    cast: [],
    opponent_response: "",
    emotional_change: "",
    gain_or_loss: "",
  };
}

function withOutlineDefaults(outline: ProjectOutline): ProjectOutline {
  return {
    ...outline,
    overall: {
      ...outline.overall,
      core_selling_point: outline.overall?.core_selling_point ?? "",
      long_term_lines: outline.overall?.long_term_lines ?? [],
      planned_arc_count: outline.overall?.planned_arc_count ?? outline.arcs?.length ?? 0,
      planned_length: outline.overall?.planned_length ?? outline.overall?.core_ending_chapter ?? 0,
      expansion_route: outline.overall?.expansion_route ?? "",
      closing_route: outline.overall?.closing_route ?? "",
      positioning: {
        protagonist_profile: outline.overall?.positioning?.protagonist_profile ?? "",
        inciting_incident: outline.overall?.positioning?.inciting_incident ?? "",
        failure_stakes: outline.overall?.positioning?.failure_stakes ?? "",
        excitement_point: outline.overall?.positioning?.excitement_point ?? "",
        target_audience: outline.overall?.positioning?.target_audience ?? "",
        reader_promise: outline.overall?.positioning?.reader_promise ?? "",
      },
      protagonist_drive: {
        immediate_need: outline.overall?.protagonist_drive?.immediate_need ?? "",
        trigger: outline.overall?.protagonist_drive?.trigger ?? "",
        short_term_goal: outline.overall?.protagonist_drive?.short_term_goal ?? "",
        failure_stakes: outline.overall?.protagonist_drive?.failure_stakes ?? "",
        long_term_transition: outline.overall?.protagonist_drive?.long_term_transition ?? "",
      },
      core_advantage: {
        name: outline.overall?.core_advantage?.name ?? "",
        type: outline.overall?.core_advantage?.type ?? "",
        ability: outline.overall?.core_advantage?.ability ?? "",
        growth_rule: outline.overall?.core_advantage?.growth_rule ?? "",
        limits: outline.overall?.core_advantage?.limits ?? "",
        early_payoff: outline.overall?.core_advantage?.early_payoff ?? "",
      },
      central_mystery: {
        surface_anomaly: outline.overall?.central_mystery?.surface_anomaly ?? "",
        hidden_truth: outline.overall?.central_mystery?.hidden_truth ?? "",
        reality_impact: outline.overall?.central_mystery?.reality_impact ?? "",
        reveal_path: outline.overall?.central_mystery?.reveal_path ?? [],
      },
    },
    arcs: (outline.arcs ?? []).map((arc) => ({
      ...arc,
      active_long_term_lines: arc.active_long_term_lines ?? [],
      core_loop: arc.core_loop ?? "",
      escalations: arc.escalations ?? [],
      midpoint_turn: arc.midpoint_turn ?? "",
      climax: arc.climax ?? arc.payoff ?? "",
      relationship_changes: arc.relationship_changes ?? [],
      foreshadowing_in: arc.foreshadowing_in ?? [],
      foreshadowing_out: arc.foreshadowing_out ?? [],
      next_arc_entry: arc.next_arc_entry ?? "",
    })),
    chapters: (outline.chapters ?? []).map((chapter) => ({
      ...chapter,
      opponent_response: chapter.opponent_response ?? "",
      emotional_change: chapter.emotional_change ?? "",
      gain_or_loss: chapter.gain_or_loss ?? "",
    })),
  };
}

function rangesOverlap(left: ProjectOutlineArc, right: ProjectOutlineArc): boolean {
  return left.start_chapter <= right.end_chapter && right.start_chapter <= left.end_chapter;
}

export default function OutlinePage() {
  const { project, story, error: projectError, encodedProjectId, projectId } = useProjectWorkspace();
  const [activeTab, setActiveTab] = useState<OutlineTab>("overall");
  const [draft, setDraft] = useState<ProjectOutline | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState<OutlineGenerationMode | null>(null);
  const [lastGenerationMode, setLastGenerationMode] = useState<OutlineGenerationMode>("initial");
  const [generationCheckpoints, setGenerationCheckpoints] = useState<OutlineGenerationCheckpointResponse | null>(null);
  const [guidance, setGuidance] = useState("");
  const [message, setMessage] = useState("");
  const [localError, setLocalError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [overallNumbers, setOverallNumbers] = useState({ core: "", ceiling: "" });
  const [foreshadowingItems, setForeshadowingItems] = useState<ForeshadowingEntry[]>([]);
  const [foreshadowingVersion, setForeshadowingVersion] = useState("");
  const [foreshadowingFilter, setForeshadowingFilter] = useState<ForeshadowingFilter>("active");
  const [foreshadowingLoading, setForeshadowingLoading] = useState(true);
  const [foreshadowingSaving, setForeshadowingSaving] = useState(false);
  const [foreshadowingError, setForeshadowingError] = useState("");
  const [foreshadowingMessage, setForeshadowingMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError("");
    fetchProjectOutline(projectId)
      .then((outline) => {
        if (!cancelled) {
          setDraft(withOutlineDefaults(outline));
          setOverallNumbers({
            core: String(outline.overall.core_ending_chapter),
            ceiling: String(outline.overall.extension_ceiling_chapter),
          });
        }
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    setForeshadowingLoading(true);
    setForeshadowingError("");
    setForeshadowingMessage("");
    fetchProjectForeshadowing(projectId)
      .then((response) => {
        if (!cancelled) {
          setForeshadowingItems(response.items);
          setForeshadowingVersion(response.version ?? "");
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setForeshadowingItems([]);
          setForeshadowingError(`伏笔加载失败：${err instanceof Error ? err.message : String(err)}`);
        }
      })
      .finally(() => {
        if (!cancelled) setForeshadowingLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    if (!generating) return;
    let cancelled = false;
    const refreshCheckpoints = () => {
      fetchOutlineGenerationCheckpoints(projectId)
        .then((response) => {
          if (!cancelled) setGenerationCheckpoints(response);
        })
        .catch(() => undefined);
    };
    refreshCheckpoints();
    const timer = window.setInterval(refreshCheckpoints, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [generating, projectId]);

  const nextChapter = (story?.current_chapter ?? 0) + 1;
  const isGameProject = isGameWebnovel(project);
  const continuationStart = project?.continuation?.start_after_chapter ?? null;
  const activeArc = draft?.arcs.find(
    (arc) => arc.start_chapter <= nextChapter && nextChapter <= arc.end_chapter,
  );
  const closeRouteMissing = !activeArc?.extension_gate.close_route.trim();

  const outlineWindow = useMemo(() => {
    if (!draft) return null;
    const currentChapter = story?.current_chapter ?? 0;
    const targetLastChapter = Math.min(
      currentChapter + OUTLINE_DETAIL_WINDOW,
      draft.overall.extension_ceiling_chapter,
    );
    const plannedChapters = new Set(draft.chapters.map((chapter) => chapter.chapter_number));
    let remainingChapters = 0;
    while (
      currentChapter + remainingChapters < targetLastChapter
      && plannedChapters.has(currentChapter + remainingChapters + 1)
    ) {
      remainingChapters += 1;
    }
    const hasMissingChapter = Array.from(
      { length: Math.max(0, targetLastChapter - currentChapter) },
      (_, index) => currentChapter + index + 1,
    ).some((chapterNumber) => !plannedChapters.has(chapterNumber));
    return {
      targetLastChapter,
      remainingChapters,
      canExtend: hasMissingChapter && remainingChapters <= OUTLINE_EXTENSION_WARNING,
      isFull: !hasMissingChapter,
    };
  }, [draft, story?.current_chapter]);

  const warnings = useMemo(() => {
    if (!draft) return [];
    const items: string[] = [];
    if (!draft.overall.story.trim()) {
      items.push("请先填写总纲中的核心故事。");
    }
    const hasOverlap = draft.arcs.some((arc, index) => draft.arcs.slice(index + 1).some((other) => rangesOverlap(arc, other)));
    if (hasOverlap) {
      items.push("阶段章节范围有重叠；生成时会采用起始章节最接近当前章的阶段。");
    }
    const currentChapter = story?.current_chapter ?? 0;
    const plannedChapters = new Set(draft.chapters.map((chapter) => chapter.chapter_number));
    let remainingChapters = 0;
    while (plannedChapters.has(currentChapter + remainingChapters + 1)) {
      remainingChapters += 1;
    }
    if (
      remainingChapters <= OUTLINE_EXTENSION_WARNING &&
      currentChapter + remainingChapters < draft.overall.extension_ceiling_chapter
    ) {
      items.push(`章节计划还剩 ${remainingChapters} 章，请补充下一批。`);
    }
    if (draft.overall.extension_ceiling_chapter < draft.overall.core_ending_chapter) {
      items.push("最大扩展章数不能小于核心完结章数。");
    }
    return items;
  }, [draft, story?.current_chapter]);

  function updateArc(index: number, patch: Partial<ProjectOutlineArc>) {
    setDraft((current) =>
      current
        ? { ...current, arcs: current.arcs.map((arc, arcIndex) => (arcIndex === index ? { ...arc, ...patch } : arc)) }
        : current,
    );
  }

  function updateOverallNumber(field: "core_ending_chapter" | "extension_ceiling_chapter", value: string) {
    setLocalError("");
    setOverallNumbers((current) => ({
      ...current,
      [field === "core_ending_chapter" ? "core" : "ceiling"]: value,
    }));
    const parsed = Number(value);
    if (value.trim() && Number.isInteger(parsed)) {
      setDraft((current) =>
        current ? { ...current, overall: { ...current.overall, [field]: parsed } } : current,
      );
    }
  }

  function updateChapter(index: number, patch: Partial<ProjectChapterOutline>) {
    setDraft((current) =>
      current
        ? {
            ...current,
            chapters: current.chapters.map((chapter, chapterIndex) =>
              chapterIndex === index ? { ...chapter, ...patch } : chapter,
            ),
          }
        : current,
    );
  }

  function addArc() {
    setDraft((current) => (current ? { ...current, arcs: [...current.arcs, newArc(current.arcs.length)] } : current));
  }

  function addChapter() {
    setDraft((current) => {
      if (!current) return current;
      const chapterNumber = Math.max(0, ...current.chapters.map((chapter) => chapter.chapter_number)) + 1;
      return { ...current, chapters: [...current.chapters, newChapter(chapterNumber)] };
    });
  }

  const visibleForeshadowingItems = foreshadowingItems
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => {
      if (foreshadowingFilter === "active") return item.status === "open" || item.status === "reinforced";
      if (foreshadowingFilter === "ended") return item.status === "resolved" || item.status === "expired";
      return true;
    });

  function updateForeshadowing(index: number, patch: Partial<ForeshadowingEntry>) {
    setForeshadowingItems((current) =>
      current.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)),
    );
    setForeshadowingMessage("");
  }

  function updateForeshadowingStatus(index: number, status: ForeshadowingStatus) {
    const item = foreshadowingItems[index];
    if (!item) return;
    const resolvedChapter = status === "resolved"
      ? item.resolved_chapter ?? Math.max(item.last_touched_chapter, story?.current_chapter ?? 0, item.first_chapter)
      : status === "expired"
        ? item.resolved_chapter
        : null;
    updateForeshadowing(index, { status, resolved_chapter: resolvedChapter });
  }

  function selectOutlineTab(tab: OutlineTab, focus = false) {
    setActiveTab(tab);
    if (focus) {
      requestAnimationFrame(() => document.getElementById(`outline-tab-${tab}`)?.focus());
    }
  }

  function handleTabKeyDown(event: React.KeyboardEvent<HTMLButtonElement>, tab: OutlineTab) {
    const currentIndex = TABS.findIndex((item) => item.id === tab);
    let targetIndex = currentIndex;
    if (event.key === "ArrowRight") targetIndex = (currentIndex + 1) % TABS.length;
    else if (event.key === "ArrowLeft") targetIndex = (currentIndex - 1 + TABS.length) % TABS.length;
    else if (event.key === "Home") targetIndex = 0;
    else if (event.key === "End") targetIndex = TABS.length - 1;
    else return;
    event.preventDefault();
    selectOutlineTab(TABS[targetIndex].id, true);
  }

  function addForeshadowing() {
    setForeshadowingItems((current) => [...current, {
      text: "",
      first_chapter: nextChapter,
      last_touched_chapter: nextChapter,
      status: "open",
      payoff_plan: "",
      resolved_chapter: null,
    }]);
    setForeshadowingFilter("active");
    setForeshadowingError("");
    setForeshadowingMessage("");
  }

  async function saveForeshadowing() {
    const normalizedItems = foreshadowingItems.map((item) =>
      item.status === "open" || item.status === "reinforced"
        ? { ...item, resolved_chapter: null }
        : item,
    );
    for (const [index, item] of normalizedItems.entries()) {
      const prefix = `第 ${index + 1} 条伏笔：`;
      if (!item.text.trim()) {
        setForeshadowingError(`${prefix}伏笔内容不能为空。`);
        return;
      }
      if (!Number.isInteger(item.first_chapter) || item.first_chapter < 0) {
        setForeshadowingError(`${prefix}首次章不能小于 0。`);
        return;
      }
      if (!Number.isInteger(item.last_touched_chapter) || item.last_touched_chapter < item.first_chapter) {
        setForeshadowingError(`${prefix}最近推进章不能小于首次章。`);
        return;
      }
      if (
        item.status === "resolved" &&
        (!Number.isInteger(item.resolved_chapter) || (item.resolved_chapter as number) < item.last_touched_chapter)
      ) {
        setForeshadowingError(`${prefix}回收章不能小于最近推进章。`);
        return;
      }
      if (
        item.status === "expired" && item.resolved_chapter !== null &&
        (!Number.isInteger(item.resolved_chapter) || item.resolved_chapter < item.last_touched_chapter)
      ) {
        setForeshadowingError(`${prefix}回收章不能小于最近推进章。`);
        return;
      }
    }
    setForeshadowingSaving(true);
    setForeshadowingError("");
    setForeshadowingMessage("");
    try {
      setForeshadowingItems(normalizedItems);
      const saved = await updateProjectForeshadowing(projectId, normalizedItems, foreshadowingVersion);
      setForeshadowingItems(saved.items);
      setForeshadowingVersion(saved.version ?? "");
      setForeshadowingMessage("伏笔账本已保存。");
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      setForeshadowingError(
        detail.includes("foreshadowing_version_conflict")
          ? "伏笔账本已有新内容，请刷新页面后再保存。"
          : `伏笔保存失败：${detail}`,
      );
    } finally {
      setForeshadowingSaving(false);
    }
  }

  function updatePositioningField(field: PositioningField, value: string) {
    setDraft((current) => current ? {
      ...current,
      overall: { ...current.overall, positioning: { ...current.overall.positioning, [field]: value } },
    } : current);
  }

  function updateCoreAdvantageField(field: CoreAdvantageField, value: string) {
    setDraft((current) => current ? {
      ...current,
      overall: { ...current.overall, core_advantage: { ...current.overall.core_advantage, [field]: value } },
    } : current);
  }

  function updateCentralMysteryField(field: CentralMysteryTextField, value: string) {
    setDraft((current) => current ? {
      ...current,
      overall: { ...current.overall, central_mystery: { ...current.overall.central_mystery, [field]: value } },
    } : current);
  }

  function updateProtagonistDriveField(field: ProtagonistDriveField, value: string) {
    setDraft((current) => current ? {
      ...current,
      overall: { ...current.overall, protagonist_drive: { ...current.overall.protagonist_drive, [field]: value } },
    } : current);
  }

  async function saveOutline() {
    if (!draft) return;
    const coreEndingChapter = Number(overallNumbers.core);
    const extensionCeilingChapter = Number(overallNumbers.ceiling);
    if (
      !overallNumbers.core.trim() ||
      !overallNumbers.ceiling.trim() ||
      !Number.isInteger(coreEndingChapter) ||
      !Number.isInteger(extensionCeilingChapter)
    ) {
      setLocalError("请输入有效的核心完结章数和最大扩展章数。");
      return;
    }
    setLocalError("");
    setSaving(true);
    setMessage("");
    try {
      const { source: _source, ...payload } = draft;
      const saved = await updateProjectOutline(projectId, payload);
      setDraft(withOutlineDefaults(saved));
      setMessage("大纲已保存，下一次剧情规划会读取这版内容。");
    } catch (err) {
      setMessage(`保存失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setSaving(false);
    }
  }

  async function runGeneration(mode: OutlineGenerationMode, restartFrom?: OutlineGenerationPhaseId) {
    if (!draft) return;
    setLastGenerationMode(mode);
    setGenerating(mode);
    setMessage("");
    try {
      const generated = await generateProjectOutline(projectId, mode, guidance.trim(), restartFrom);
      setDraft(withOutlineDefaults({ ...generated.outline, source: "saved" }));
      setOverallNumbers({
        core: String(generated.outline.overall.core_ending_chapter),
        ceiling: String(generated.outline.overall.extension_ceiling_chapter),
      });
      setGuidance("");
      setMessage(mode === "extend" ? "后续五章已补充。" : mode === "regenerate" ? "大纲和开篇角色已重新生成。" : "大纲和开篇角色已生成。");
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      setMessage(
        detail.includes("outline_window_already_full")
          ? `后续大纲已规划到第 ${outlineWindow?.targetLastChapter ?? "当前"} 章，写到接近末尾时再补充。`
          : `生成失败：${detail}`,
      );
    } finally {
      try {
        setGenerationCheckpoints(await fetchOutlineGenerationCheckpoints(projectId));
      } catch {
        // Generation result remains usable even if the progress view cannot refresh.
      }
      setGenerating(null);
    }
  }

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="大纲"
        subtitle="总纲管全书方向，阶段大纲管一段剧情，章节大纲只管当前一章。"
      />

      {projectError || loadError ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{projectError || loadError}</p>
        </div>
      ) : null}

      <section className="ws-outline-workspace" aria-label="三级大纲编辑器">
        <div className="ws-section-head">
          <div>
            <p className="ws-card__title">故事规划</p>
            <p className="ws-card__hint">
              {continuationStart !== null
                ? "覆盖原著与续写后的全书方向"
                : draft?.source === "legacy"
                  ? "当前是旧大纲预览，保存后转为新版结构。"
                  : "保存后，生成时只提取当前章节需要的大纲。"}
            </p>
          </div>
          <button className="ws-btn ws-btn--primary" type="button" onClick={() => void saveOutline()} disabled={saving || generating !== null || !draft}>
            {saving ? "保存中..." : "保存大纲"}
          </button>
        </div>

        {draft ? (
          <div className="ws-outline-generation">
            <label className="ws-outline-field ws-outline-field--wide">
              <span>本次生成补充要求</span>
              <textarea
                className="ws-input"
                rows={3}
                maxLength={1000}
                placeholder="只在这次生成中使用，不会写入长期设定。"
                value={guidance}
                onChange={(event) => setGuidance(event.target.value)}
              />
            </label>
            <div className="ws-outline-generation__actions">
              {draft.arcs.length === 0 && draft.chapters.length === 0 ? (
                <button className="ws-btn" type="button" disabled={generating !== null || saving} onClick={() => void runGeneration("initial")}>
                  {generating === "initial" ? "生成中..." : "生成大纲"}
                </button>
              ) : (
                <>
                  <button className="ws-btn" type="button" disabled={generating !== null || saving} onClick={() => void runGeneration("regenerate")}>
                    {generating === "regenerate" ? "生成中..." : "重新生成"}
                  </button>
                  <button
                    className="ws-btn"
                    type="button"
                    disabled={generating !== null || saving || !outlineWindow?.canExtend}
                    title={
                      outlineWindow?.isFull
                        ? `后续大纲已规划到第 ${outlineWindow.targetLastChapter} 章，写到接近末尾时再补充。`
                        : outlineWindow && !outlineWindow.canExtend
                          ? `当前还有 ${outlineWindow.remainingChapters} 章详细大纲，剩余 ${OUTLINE_EXTENSION_WARNING} 章以内时可补充。`
                          : undefined
                    }
                    onClick={() => void runGeneration("extend")}
                  >
                    {generating === "extend" ? "生成中..." : "补充后续章节"}
                  </button>
                </>
              )}
              {draft.chapters.length > 0 ? (
                <Link className="ws-btn ws-btn--primary" href={`/projects/${encodedProjectId}/world`}>
                  下一步：完善世界观
                </Link>
              ) : null}
            </div>
            {generationCheckpoints && (
              generating !== null
              || generationCheckpoints.phases.some((phase) => phase.status !== "waiting")
            ) ? (
              <section className="ws-outline-generation-progress" aria-label="大纲生成步骤">
                <strong>生成步骤</strong>
                <div className="ws-outline-generation-steps">
                  {generationCheckpoints.phases.map((phase) => (
                    <article key={phase.id}>
                      <b>{OUTLINE_PHASE_LABELS[phase.id]}</b>
                      <p>{OUTLINE_PHASE_STATUS[phase.status] ?? phase.status}</p>
                      {phase.error ? <p className="ws-outline-error">{phase.error}</p> : null}
                      {phase.payload ? (
                        <details>
                          <summary>查看已保存产物</summary>
                          <pre>{JSON.stringify(phase.payload, null, 2)}</pre>
                        </details>
                      ) : null}
                      {phase.status === "failed" && generating === null ? (
                        <button
                          className="ws-btn"
                          type="button"
                          onClick={() => void runGeneration(lastGenerationMode, phase.id)}
                        >
                          从这一步重试
                        </button>
                      ) : null}
                    </article>
                  ))}
                </div>
              </section>
            ) : null}
          </div>
        ) : null}

        <div className="ws-outline-tabs" role="tablist" aria-label="大纲层级">
          {TABS.map((tab) => (
            <button
              className={`ws-outline-tab${activeTab === tab.id ? " is-active" : ""}`}
              id={`outline-tab-${tab.id}`}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              aria-controls={`outline-panel-${tab.id}`}
              tabIndex={activeTab === tab.id ? 0 : -1}
              key={tab.id}
              onClick={() => selectOutlineTab(tab.id)}
              onKeyDown={(event) => handleTabKeyDown(event, tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {message ? <p className="ws-outline-message">{message}</p> : null}
        {localError ? <p className="ws-outline-error">{localError}</p> : null}
        {warnings.map((warning) => (
          <p className="ws-outline-warning" key={warning}>
            {warning}
          </p>
        ))}

        {loading ? <p className="ws-card__hint">正在读取大纲...</p> : null}

        {draft && activeTab === "overall" ? (
          <div className="ws-outline-grid" role="tabpanel" id="outline-panel-overall" aria-labelledby="outline-tab-overall">
            <p className="ws-card__hint ws-outline-field--wide">
              大纲模板：{project?.world_blueprint?.genre_plugin_ids?.[0] || "未选择类型"} · novel-outline-template/v1
            </p>
            <h2 className="ws-outline-field--wide">故事定位</h2>
            <label className="ws-outline-field ws-outline-field--wide">
              <span>一句话简介</span>
              <textarea
                className="ws-input"
                rows={4}
                value={draft.overall.story}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, story: event.target.value } })}
              />
            </label>
            {POSITIONING_FIELDS.map(({ field, label }) => (
              <label className="ws-outline-field" key={field}>
                <span>{label}</span>
                <textarea
                  className="ws-input"
                  rows={3}
                  value={draft.overall.positioning[field]}
                  onChange={(event) => updatePositioningField(field, event.target.value)}
                />
              </label>
            ))}
            <label className="ws-outline-field ws-outline-field--wide">
              <span>核心卖点</span>
              <textarea className="ws-input" rows={3} value={draft.overall.core_selling_point} onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, core_selling_point: event.target.value } })} />
            </label>
            <h3 className="ws-outline-field--wide">主角驱动力</h3>
            {([[
              "immediate_need", "眼前需求"], ["trigger", "触发原因"], ["short_term_goal", "短期目标"], ["failure_stakes", "失败代价"], ["long_term_transition", "转向长期目标的节点"],
            ] as const).map(([field, label]) => (
              <label className="ws-outline-field" key={field}>
                <span>{label}</span>
                <textarea className="ws-input" rows={3} value={draft.overall.protagonist_drive[field]} onChange={(event) => updateProtagonistDriveField(field, event.target.value)} />
              </label>
            ))}
            <h3 className="ws-outline-field--wide">核心优势</h3>
            {([[
              "name", "名称"], ["type", "类型"], ["ability", "具体能力"], ["growth_rule", "成长规则"], ["limits", "限制或代价"], ["early_payoff", "前期首次兑现"],
            ] as const).map(([field, label]) => (
              <label className="ws-outline-field" key={field}>
                <span>{label}</span>
                <textarea className="ws-input" rows={3} value={draft.overall.core_advantage[field]} onChange={(event) => updateCoreAdvantageField(field, event.target.value)} />
              </label>
            ))}
            <h3 className="ws-outline-field--wide">核心谜团</h3>
            {([[
              "surface_anomaly", "表层异常"], ["hidden_truth", "隐藏真相"], ["reality_impact", "现实影响"],
            ] as const).map(([field, label]) => (
              <label className="ws-outline-field" key={field}>
                <span>{label}</span>
                <textarea className="ws-input" rows={3} value={draft.overall.central_mystery[field]} onChange={(event) => updateCentralMysteryField(field, event.target.value)} />
              </label>
            ))}
            <label className="ws-outline-field ws-outline-field--wide">
              <span>分阶段揭露路径（每行一项）</span>
              <textarea
                className="ws-input"
                rows={4}
                value={draft.overall.central_mystery.reveal_path.join("\n")}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, central_mystery: { ...draft.overall.central_mystery, reveal_path: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) } } })}
              />
            </label>
            <h3 className="ws-outline-field--wide">全书结构</h3>
            <label className="ws-outline-field">
              <span>核心完结章数</span>
              <input
                className="ws-input"
                type="number"
                min={story?.current_chapter || 1}
                value={overallNumbers.core}
                onChange={(event) => updateOverallNumber("core_ending_chapter", event.target.value)}
              />
            </label>
            <label className="ws-outline-field ws-outline-field--wide">
              <span>主题命题</span>
              <textarea
                className="ws-input"
                rows={3}
                value={draft.overall.theme_statement}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, theme_statement: event.target.value } })}
              />
            </label>
            <label className="ws-outline-field">
              <span>前台故事</span>
              <textarea
                className="ws-input"
                rows={4}
                value={draft.overall.foreground_story}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, foreground_story: event.target.value } })}
              />
            </label>
            <label className="ws-outline-field">
              <span>后台故事</span>
              <textarea
                className="ws-input"
                rows={4}
                value={draft.overall.background_story}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, background_story: event.target.value } })}
              />
            </label>
            <label className="ws-outline-field">
              <span>全书可验证目标</span>
              <textarea
                className="ws-input"
                rows={4}
                value={draft.overall.book_objective}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, book_objective: event.target.value } })}
              />
            </label>
            <label className="ws-outline-field">
              <span>终局画面</span>
              <textarea
                className="ws-input"
                rows={4}
                value={draft.overall.ending_image}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, ending_image: event.target.value } })}
              />
            </label>
            <label className="ws-outline-field">
              <span>最大扩展章数</span>
              <input
                className="ws-input"
                type="number"
                min={story?.current_chapter || 1}
                value={overallNumbers.ceiling}
                onChange={(event) => updateOverallNumber("extension_ceiling_chapter", event.target.value)}
              />
            </label>
            <label className="ws-outline-field">
              <span>规划卷数</span>
              <input className="ws-input" type="number" min={0} value={draft.overall.planned_arc_count} onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, planned_arc_count: Number(event.target.value) } })} />
            </label>
            <label className="ws-outline-field">
              <span>规划章数</span>
              <input className="ws-input" type="number" min={0} value={draft.overall.planned_length} onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, planned_length: Number(event.target.value) } })} />
            </label>
            <label className="ws-outline-field">
              <span>扩展路线</span>
              <textarea className="ws-input" rows={3} value={draft.overall.expansion_route} onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, expansion_route: event.target.value } })} />
            </label>
            <label className="ws-outline-field">
              <span>收束路线</span>
              <textarea className="ws-input" rows={3} value={draft.overall.closing_route} onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, closing_route: event.target.value } })} />
            </label>
            <label className="ws-outline-field ws-outline-field--wide">
              <span>核心结局契约</span>
              <textarea
                className="ws-input"
                rows={3}
                value={draft.overall.ending_contract}
                onChange={(event) =>
                  setDraft({ ...draft, overall: { ...draft.overall, ending_contract: event.target.value } })
                }
              />
            </label>
            <div className="ws-outline-field ws-outline-field--wide">
              <span>长篇策略</span>
              <div className="ws-outline-strategy" role="radiogroup" aria-label="长篇策略">
                {([
                  ["observe", "观察中"],
                  ["expand", "扩展"],
                  ["close", "收束"],
                ] as const).map(([value, label]) => (
                  <label key={value}>
                    <input
                      type="radio"
                      name="outline-strategy"
                      value={value}
                      checked={draft.overall.current_strategy === value}
                      disabled={value === "close" && closeRouteMissing}
                      onChange={() =>
                        setDraft({
                          ...draft,
                          overall: { ...draft.overall, current_strategy: value },
                        })
                      }
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
              {closeRouteMissing ? (
                <span className="ws-outline-strategy__reason">请先填写当前阶段的收束路线。</span>
              ) : null}
            </div>
            <label className="ws-outline-field">
              <span>主角长期目标</span>
              <textarea
                className="ws-input"
                rows={4}
                value={draft.overall.protagonist_goal}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, protagonist_goal: event.target.value } })}
              />
            </label>
            <label className="ws-outline-field">
              <span>主线冲突</span>
              <textarea
                className="ws-input"
                rows={4}
                value={draft.overall.main_conflict}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, main_conflict: event.target.value } })}
              />
            </label>
            <label className="ws-outline-field">
              <span>成长路线</span>
              <textarea
                className="ws-input"
                rows={4}
                value={draft.overall.growth_path}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, growth_path: event.target.value } })}
              />
            </label>
            <label className="ws-outline-field">
              <span>结局方向</span>
              <textarea
                className="ws-input"
                rows={4}
                value={draft.overall.ending_direction}
                onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, ending_direction: event.target.value } })}
              />
            </label>
            <div className="ws-outline-field ws-outline-field--wide">
              <span>长期主线</span>
              <div className="ws-outline-list">
                {draft.overall.long_term_lines.map((line, index) => (
                  <article className="ws-outline-item" key={`${line.name}-${index}`}>
                    <div className="ws-outline-grid">
                      <label className="ws-outline-field"><span>名称</span><input className="ws-input" value={line.name} onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, long_term_lines: draft.overall.long_term_lines.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item) } })} /></label>
                      <label className="ws-outline-field"><span>作用</span><input className="ws-input" value={line.purpose} onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, long_term_lines: draft.overall.long_term_lines.map((item, itemIndex) => itemIndex === index ? { ...item, purpose: event.target.value } : item) } })} /></label>
                      <label className="ws-outline-field"><span>起点</span><textarea className="ws-input" rows={2} value={line.start_state} onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, long_term_lines: draft.overall.long_term_lines.map((item, itemIndex) => itemIndex === index ? { ...item, start_state: event.target.value } : item) } })} /></label>
                      <label className="ws-outline-field"><span>推进步骤（每行一项）</span><textarea className="ws-input" rows={3} value={line.progression_steps.join("\n")} onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, long_term_lines: draft.overall.long_term_lines.map((item, itemIndex) => itemIndex === index ? { ...item, progression_steps: event.target.value.split("\n").map((value) => value.trim()).filter(Boolean) } : item) } })} /></label>
                      <label className="ws-outline-field ws-outline-field--wide"><span>最终兑现</span><textarea className="ws-input" rows={2} value={line.final_payoff} onChange={(event) => setDraft({ ...draft, overall: { ...draft.overall, long_term_lines: draft.overall.long_term_lines.map((item, itemIndex) => itemIndex === index ? { ...item, final_payoff: event.target.value } : item) } })} /></label>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </div>
        ) : null}

        {draft && activeTab === "arcs" ? (
          <div role="tabpanel" id="outline-panel-arcs" aria-labelledby="outline-tab-arcs">
            <div className="ws-outline-list">
              {draft.arcs.map((arc, index) => {
                const arcState = continuationStart === null
                  ? "regular"
                  : arc.end_chapter <= continuationStart
                    ? "historical"
                    : arc.start_chapter > continuationStart
                      ? "future"
                      : "crossing";
                const historical = arcState === "historical";
                const stateLabel = arcState === "historical" ? "已发生" : arcState === "future" ? "规划中" : arcState === "crossing" ? "边界待修复" : "";
                return (
                <article className="ws-outline-item" data-arc-state={arcState} key={arc.id}>
                  <div className="ws-outline-item__head">
                    <strong>阶段 {index + 1}{stateLabel ? ` · ${stateLabel}` : ""}</strong>
                    <button
                      className="ws-btn ws-btn--sm"
                      type="button"
                      disabled={historical}
                      onClick={() => setDraft({ ...draft, arcs: draft.arcs.filter((_, arcIndex) => arcIndex !== index) })}
                    >
                      删除
                    </button>
                  </div>
                  <fieldset className="ws-outline-grid" disabled={historical}>
                    <label className="ws-outline-field">
                      <span>阶段名称</span>
                      <input className="ws-input" value={arc.title} onChange={(event) => updateArc(index, { title: event.target.value })} />
                    </label>
                    <label className="ws-outline-field">
                      <span>阶段对手</span>
                      <input className="ws-input" value={arc.stage_antagonist} onChange={(event) => updateArc(index, { stage_antagonist: event.target.value })} />
                    </label>
                    {isGameProject ? (
                      <label className="ws-outline-field">
                        <span>网游长篇阶段</span>
                        <select className="ws-input" value={arc.pacing_stage_id ?? ""} onChange={(event) => updateArc(index, { pacing_stage_id: event.target.value })}>
                          <option value="">暂未指定</option>
                          {GAME_PACING_STAGES.map((stage) => <option key={stage.id} value={stage.id}>{stage.label}</option>)}
                        </select>
                      </label>
                    ) : null}
                    <div className="ws-outline-range">
                      <label className="ws-outline-field">
                        <span>起始章</span>
                        <input
                          className="ws-input"
                          type="number"
                          min={1}
                          value={arc.start_chapter}
                          onChange={(event) => updateArc(index, { start_chapter: Number(event.target.value) })}
                        />
                      </label>
                      <label className="ws-outline-field">
                        <span>结束章</span>
                        <input
                          className="ws-input"
                          type="number"
                          min={1}
                          value={arc.end_chapter}
                          onChange={(event) => updateArc(index, { end_chapter: Number(event.target.value) })}
                        />
                      </label>
                    </div>
                    {([
                      ["goal", "阶段目标"],
                      ["obstacle", "主要阻碍"],
                      ["payoff", "关键兑现"],
                      ["end_state", "结束状态"],
                    ] as const).map(([field, label]) => (
                      <label className="ws-outline-field" key={field}>
                        <span>{label}</span>
                        <textarea className="ws-input" rows={3} value={arc[field]} onChange={(event) => updateArc(index, { [field]: event.target.value })} />
                      </label>
                    ))}
                    <label className="ws-outline-field">
                      <span>情绪曲线</span>
                      <textarea className="ws-input" rows={3} value={arc.emotional_curve} onChange={(event) => updateArc(index, { emotional_curve: event.target.value })} />
                    </label>
                    <label className="ws-outline-field">
                      <span>三个阶段结果</span>
                      <textarea
                        className="ws-input"
                        rows={4}
                        value={arc.key_results.join("\n")}
                        onChange={(event) => updateArc(index, { key_results: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) })}
                      />
                    </label>
                    <label className="ws-outline-field">
                      <span>伏笔安排</span>
                      <textarea className="ws-input" rows={3} value={arc.hook_plan} onChange={(event) => updateArc(index, { hook_plan: event.target.value })} />
                    </label>
                    <label className="ws-outline-field">
                      <span>卷尾不可逆变化</span>
                      <textarea className="ws-input" rows={3} value={arc.irreversible_change} onChange={(event) => updateArc(index, { irreversible_change: event.target.value })} />
                    </label>
                    {([[
                      "core_loop", "核心循环"], ["midpoint_turn", "中段转折"], ["climax", "卷末高潮"], ["next_arc_entry", "下卷入口"],
                    ] as const).map(([field, label]) => (
                      <label className="ws-outline-field" key={field}><span>{label}</span><textarea className="ws-input" rows={3} value={arc[field]} onChange={(event) => updateArc(index, { [field]: event.target.value })} /></label>
                    ))}
                    {([[
                      "active_long_term_lines", "推进中的长期线"], ["escalations", "三次升级"], ["relationship_changes", "关系变化"], ["foreshadowing_in", "承接伏笔"], ["foreshadowing_out", "新埋伏笔"],
                    ] as const).map(([field, label]) => (
                      <label className="ws-outline-field" key={field}><span>{label}</span><textarea className="ws-input" rows={3} value={arc[field].join("\n")} onChange={(event) => updateArc(index, { [field]: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) })} /></label>
                    ))}
                    {isGameProject ? ([
                      ["game_line_payoff", "游戏线阶段结果"],
                      ["reality_line_payoff", "现实线阶段结果"],
                    ] as const).map(([field, label]) => (
                      <label className="ws-outline-field" key={field}>
                        <span>{label}</span>
                        <textarea
                          className="ws-input"
                          rows={3}
                          value={arc[field]}
                          onChange={(event) => updateArc(index, { [field]: event.target.value })}
                        />
                      </label>
                    )) : null}
                    <label className="ws-outline-field">
                      <span>继续路线</span>
                      <textarea
                        className="ws-input"
                        rows={3}
                        value={arc.extension_gate.continue_route}
                        onChange={(event) =>
                          updateArc(index, {
                            extension_gate: { ...arc.extension_gate, continue_route: event.target.value },
                          })
                        }
                      />
                    </label>
                    <label className="ws-outline-field">
                      <span>收束路线</span>
                      <textarea
                        className="ws-input"
                        rows={3}
                        value={arc.extension_gate.close_route}
                        onChange={(event) =>
                          updateArc(index, {
                            extension_gate: { ...arc.extension_gate, close_route: event.target.value },
                          })
                        }
                      />
                    </label>
                    <label className="ws-outline-field ws-outline-field--wide">
                      <span>长期对手留下的痕迹</span>
                      <textarea
                        className="ws-input"
                        rows={3}
                        value={arc.long_term_antagonist_traces.join("\n")}
                        onChange={(event) => updateArc(index, { long_term_antagonist_traces: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) })}
                      />
                    </label>
                  </fieldset>
                </article>
                );
              })}
            </div>
            <button className="ws-btn" type="button" onClick={addArc}>
              新增阶段
            </button>
          </div>
        ) : null}

        {draft && activeTab === "chapters" ? (
          <div role="tabpanel" id="outline-panel-chapters" aria-labelledby="outline-tab-chapters">
            <div className="ws-outline-list">
              {draft.chapters.map((chapter, index) => (
                <article className="ws-outline-item" key={`${chapter.chapter_number}-${index}`}>
                  <div className="ws-outline-item__head">
                    <strong>第 {chapter.chapter_number} 章</strong>
                    <button
                      className="ws-btn ws-btn--sm"
                      type="button"
                      onClick={() => setDraft({ ...draft, chapters: draft.chapters.filter((_, chapterIndex) => chapterIndex !== index) })}
                    >
                      删除
                    </button>
                  </div>
                  <div className="ws-outline-grid">
                    <label className="ws-outline-field">
                      <span>章节号</span>
                      <input
                        className="ws-input"
                        type="number"
                        min={1}
                        value={chapter.chapter_number}
                        onChange={(event) => updateChapter(index, { chapter_number: Number(event.target.value) })}
                      />
                    </label>
                    <label className="ws-outline-field">
                      <span>暂定标题</span>
                      <input className="ws-input" value={chapter.title} onChange={(event) => updateChapter(index, { title: event.target.value })} />
                    </label>
                    <label className="ws-outline-field">
                      <span>出场人物</span>
                      <textarea
                        className="ws-input"
                        rows={3}
                        value={chapter.cast.join("\n")}
                        onChange={(event) => updateChapter(index, { cast: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) })}
                      />
                    </label>
                    {([
                      ["goal", "本章目标"],
                      ["obstacle", "主要阻碍"],
                      ["action", "主角行动"],
                      ["turn", "关键转折"],
                      ["payoff", "本章兑现"],
                      ["ending_hook", "章末钩子"],
                      ["opponent_response", "对手反应"],
                      ["emotional_change", "情绪变化"],
                      ["gain_or_loss", "本章得失"],
                    ] as const).map(([field, label]) => (
                      <label className="ws-outline-field" key={field}>
                        <span>{label}</span>
                        <textarea
                          className="ws-input"
                          rows={3}
                          value={chapter[field]}
                          onChange={(event) => updateChapter(index, { [field]: event.target.value })}
                        />
                      </label>
                    ))}
                  </div>
                </article>
              ))}
            </div>
            <button className="ws-btn" type="button" onClick={addChapter}>
              新增章节
            </button>
          </div>
        ) : null}

        {activeTab === "foreshadowing" ? (
          <div className="ws-foreshadowing" role="tabpanel" id="outline-panel-foreshadowing" aria-labelledby="outline-tab-foreshadowing">
            <fieldset className="ws-foreshadowing__fieldset" disabled={foreshadowingSaving}>
            <div className="ws-section-head ws-foreshadowing__head">
              <div>
                <h2>伏笔账本</h2>
                <p className="ws-card__hint">章节生成后自动记录，只有明确回收或手动修改才关闭。</p>
              </div>
              <div className="ws-foreshadowing__actions">
                {foreshadowingItems.length > 0 ? (
                  <button className="ws-btn" type="button" onClick={addForeshadowing}>新增伏笔</button>
                ) : null}
                <button
                  className="ws-btn ws-btn--primary"
                  type="button"
                  disabled={foreshadowingSaving || foreshadowingLoading}
                  onClick={() => void saveForeshadowing()}
                >
                  {foreshadowingSaving ? "保存中..." : "保存伏笔"}
                </button>
              </div>
            </div>

            <div className="ws-segmented-control ws-foreshadowing__filters" aria-label="伏笔筛选">
              {FORESHADOWING_FILTERS.map((filter) => (
                <button
                  key={filter.id}
                  type="button"
                  aria-pressed={foreshadowingFilter === filter.id}
                  onClick={() => setForeshadowingFilter(filter.id)}
                >
                  {filter.label}
                </button>
              ))}
            </div>

            {foreshadowingMessage ? <p className="ws-outline-message" role="status" aria-live="polite">{foreshadowingMessage}</p> : null}
            {foreshadowingError ? <p className="ws-outline-error" role="alert">{foreshadowingError}</p> : null}
            {foreshadowingLoading ? <p className="ws-card__hint" role="status" aria-live="polite">正在读取伏笔账本...</p> : null}

            {!foreshadowingLoading && visibleForeshadowingItems.length === 0 ? (
              <div className="ws-foreshadowing__empty">
                <p className="ws-card__hint">暂无伏笔记录。</p>
                <button className="ws-btn" type="button" onClick={addForeshadowing}>新增伏笔</button>
              </div>
            ) : null}

            <div className="ws-foreshadowing__list">
              {visibleForeshadowingItems.map(({ item, index }) => (
                <article className="ws-foreshadowing__item" key={index}>
                  <div className="ws-foreshadowing__row-head">
                    <strong>伏笔 {index + 1}</strong>
                    <button
                      className="ws-btn ws-btn--icon"
                      type="button"
                      title="删除伏笔"
                      aria-label="删除伏笔"
                      onClick={() => setForeshadowingItems((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                    >
                      <Trash2 aria-hidden="true" size={17} />
                    </button>
                  </div>
                  <div className="ws-foreshadowing__grid">
                    <label className="ws-outline-field ws-foreshadowing__text">
                      <span>伏笔内容</span>
                      <textarea className="ws-input" rows={3} value={item.text} onChange={(event) => updateForeshadowing(index, { text: event.target.value })} />
                    </label>
                    <label className="ws-outline-field">
                      <span>状态</span>
                      <select className="ws-input" value={item.status} onChange={(event) => updateForeshadowingStatus(index, event.target.value as ForeshadowingStatus)}>
                        {Object.entries(FORESHADOWING_STATUS_LABELS).map(([status, label]) => <option key={status} value={status}>{label}</option>)}
                      </select>
                    </label>
                    <label className="ws-outline-field">
                      <span>首次章</span>
                      <input className="ws-input" type="number" min={0} value={item.first_chapter} onChange={(event) => updateForeshadowing(index, { first_chapter: Number(event.target.value) })} />
                    </label>
                    <label className="ws-outline-field">
                      <span>最近推进章</span>
                      <input className="ws-input" type="number" min={item.first_chapter} value={item.last_touched_chapter} onChange={(event) => updateForeshadowing(index, { last_touched_chapter: Number(event.target.value) })} />
                    </label>
                    {item.status === "resolved" ? (
                      <label className="ws-outline-field">
                        <span>回收章</span>
                        <input className="ws-input" type="number" min={item.last_touched_chapter} value={item.resolved_chapter ?? ""} onChange={(event) => updateForeshadowing(index, { resolved_chapter: event.target.value ? Number(event.target.value) : null })} />
                      </label>
                    ) : null}
                    <label className="ws-outline-field ws-foreshadowing__payoff">
                      <span>回收计划</span>
                      <textarea className="ws-input" rows={3} value={item.payoff_plan} onChange={(event) => updateForeshadowing(index, { payoff_plan: event.target.value })} />
                    </label>
                  </div>
                </article>
              ))}
            </div>
            </fieldset>
          </div>
        ) : null}
      </section>
    </div>
  );
}
