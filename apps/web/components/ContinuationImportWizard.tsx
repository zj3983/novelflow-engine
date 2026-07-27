"use client";

import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Check,
  ChevronRight,
  FileText,
  Folder,
  LoaderCircle,
  Merge,
  Scissors,
  Zap,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { type ChangeEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  confirmContinuationAnalysis,
  createContinuationImport,
  createContinuationProject,
  fetchContinuationAnalysis,
  fetchContinuationImport,
  listContinuationSources,
  quickContinueNovel,
  replaceContinuationChapters,
  scanContinuationSource,
  startContinuationAnalysis,
  type ContinuationAnalysis,
  type ContinuationChapter,
  type ContinuationEvidenceRef,
  type ContinuationImportSession,
  type ContinuationScanResult,
  type ContinuationSourceList,
  type NovelType,
} from "../lib/api";

type Step = "source" | "chapters" | "analysis" | "settings";
type AnalysisTab = "overview" | "characters" | "world" | "power" | "timeline" | "hooks" | "style" | "start";

const STEPS: Array<{ id: Step; label: string }> = [
  { id: "source", label: "来源" },
  { id: "chapters", label: "章节校对" },
  { id: "analysis", label: "分析确认" },
  { id: "settings", label: "续写设置" },
];

const ANALYSIS_TABS: Array<{ id: AnalysisTab; label: string }> = [
  { id: "overview", label: "概况" },
  { id: "characters", label: "人物" },
  { id: "world", label: "世界观" },
  { id: "power", label: "力量体系" },
  { id: "timeline", label: "时间线" },
  { id: "hooks", label: "伏笔" },
  { id: "style", label: "文风" },
  { id: "start", label: "续写起点" },
];

const ERROR_TEXT: Record<string, string> = {
  source_encoding_unknown: "无法判断文本编码，请选择编码后重试。",
  path_outside_allowed_roots: "该路径不在允许访问的目录内。",
  unsupported_source_type: "只支持 TXT 或 Markdown 文件。",
  chapters_empty: "没有识别到可导入的章节。",
  session_revision_conflict: "内容已被其他操作更新，请重新加载后再试。",
  continuation_analysis_invalid_response: "分析结果不完整，请重新分析。",
  continuation_analysis_not_confirmed: "请先处理冲突并确认分析结果。",
  continuation_analysis_needs_confirmation: "仍有需要人工确认的内容。",
  source_changed_since_scan: "原始文件已经变化，请重新扫描。",
  continuation_project_internal_error: "项目创建失败，请稍后重试。",
  analysis_confirmation_required: "分析仍有待确认内容，处理后才能快速续写。",
};

function errorText(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return ERROR_TEXT[message] ?? message;
}

async function chapterFingerprint(body: string): Promise<string> {
  const bytes = new TextEncoder().encode(body);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}

async function normalizeChapters(chapters: ContinuationChapter[]): Promise<ContinuationChapter[]> {
  return Promise.all(chapters.map(async (chapter, index) => ({
    ...chapter,
    number: index + 1,
    title: chapter.title.trim(),
    body: chapter.body.trim(),
    fingerprint: await chapterFingerprint(chapter.body.trim()),
  })));
}

function EvidenceButton({ evidence, chapters }: { evidence: ContinuationEvidenceRef; chapters: ContinuationChapter[] }) {
  const [open, setOpen] = useState(false);
  const chapter = chapters.find((item) => item.chapter_id === evidence.chapter_id);
  const excerpt = evidence.quote || chapter?.body.slice(evidence.excerpt_start, evidence.excerpt_end) || "原文片段不可用";
  return (
    <span className="ws-continuation__evidence">
      <button type="button" className="ws-text-link" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        {chapter ? `第 ${chapter.number} 章证据` : "查看证据"}
      </button>
      {open ? <span className="ws-continuation__excerpt">{excerpt}</span> : null}
    </span>
  );
}

function ConfidenceTag({ value }: { value: "confirmed" | "inferred" }) {
  return <span className={`ws-continuation__confidence is-${value}`}>{value === "confirmed" ? "已证实" : "推断"}</span>;
}

export function ContinuationImportWizard({ novelTypes }: { novelTypes: NovelType[] }) {
  const router = useRouter();
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const [step, setStep] = useState<Step>("source");
  const [sources, setSources] = useState<ContinuationSourceList>({ current_path: "", directories: [], files: [] });
  const [sourcePath, setSourcePath] = useState("");
  const [encoding, setEncoding] = useState("");
  const [showEncoding, setShowEncoding] = useState(false);
  const [scan, setScan] = useState<ContinuationScanResult | null>(null);
  const [session, setSession] = useState<ContinuationImportSession | null>(null);
  const [chapters, setChapters] = useState<ContinuationChapter[]>([]);
  const [selectedChapter, setSelectedChapter] = useState(0);
  const [analysis, setAnalysis] = useState<ContinuationAnalysis | null>(null);
  const [analysisTab, setAnalysisTab] = useState<AnalysisTab>("overview");
  const [quickRequested, setQuickRequested] = useState(false);
  const [quickConfirm, setQuickConfirm] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [startAfterChapter, setStartAfterChapter] = useState(1);
  const [fidelity, setFidelity] = useState<"faithful" | "adaptive">("faithful");
  const [targetChars, setTargetChars] = useState(4500);
  const [direction, setDirection] = useState("");
  const [mustPreserve, setMustPreserve] = useState("");
  const [forbiddenContent, setForbiddenContent] = useState("");
  const [generateOutline, setGenerateOutline] = useState(false);
  const [outlineChapters, setOutlineChapters] = useState(10);
  const [novelTypeId, setNovelTypeId] = useState("generic_webnovel");

  useEffect(() => {
    let active = true;
    void listContinuationSources().then((result) => {
      if (active) setSources(result);
    }).catch((caught) => {
      if (active) setError(errorText(caught));
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (session?.status !== "analyzing") return;
    let active = true;
    const timer = window.setInterval(() => {
      void fetchContinuationImport(session.session_id).then(async (next) => {
        if (!active) return;
        if (next.status === "ready") {
          const result = await fetchContinuationAnalysis(next.session_id);
          if (!active) return;
          setSession(next);
          setAnalysis(result);
          setBusy("");
          if (quickRequested) {
            if (result.needs_confirmation.length) {
              setError("分析仍有待确认内容，处理后才能快速续写。");
            } else {
              setQuickConfirm(true);
            }
          }
        } else if (next.status === "failed") {
          setSession(next);
          setBusy("");
          setError(ERROR_TEXT[next.error] ?? next.error ?? "分析失败，请重试。");
        } else {
          setSession(next);
        }
      }).catch((caught) => {
        if (active) {
          setBusy("");
          setError(errorText(caught));
        }
      });
    }, 700);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [quickRequested, session?.session_id, session?.status]);

  useEffect(() => {
    if (chapters.length) setStartAfterChapter(chapters[chapters.length - 1].number);
  }, [chapters.length]);

  const currentChapter = chapters[selectedChapter];
  const chapterBlockers = useMemo(() => {
    if (!scan) return [] as string[];
    const ids = new Set(chapters.map((chapter) => chapter.chapter_id));
    const unresolvedDuplicates = scan.duplicate_groups.filter((group) => group.filter((id) => ids.has(id)).length > 1);
    const messages: string[] = [];
    if (chapters.some((chapter) => !chapter.title.trim() || !chapter.body.trim())) messages.push("章节标题和正文不能为空");
    if (unresolvedDuplicates.length) messages.push(`仍有 ${unresolvedDuplicates.length} 组重复章节需要合并`);
    return messages;
  }, [chapters, scan]);
  const activeStepIndex = STEPS.findIndex((item) => item.id === step);

  async function browse(path: string) {
    setBusy("browse");
    setError("");
    try {
      const result = await listContinuationSources(path);
      setSources(result);
      if (result.current_path) setSourcePath(result.current_path);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy("");
    }
  }

  async function performScan() {
    setBusy("scan");
    setError("");
    setScan(null);
    try {
      const result = await scanContinuationSource(sourcePath.trim(), encoding || undefined);
      setScan(result);
      setShowEncoding(false);
    } catch (caught) {
      const code = caught instanceof Error ? caught.message : String(caught);
      setShowEncoding(code === "source_encoding_unknown");
      setError(errorText(caught));
    } finally {
      setBusy("");
    }
  }

  async function createSession() {
    setBusy("session");
    setError("");
    try {
      const result = await createContinuationImport(sourcePath.trim(), encoding || undefined);
      setSession(result);
      setChapters(result.chapters);
      setSelectedChapter(0);
      setStep("chapters");
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy("");
    }
  }

  async function quickFromSource() {
    if (!scan) return;
    setBusy("analysis");
    setError("");
    setQuickRequested(true);
    try {
      const created = await createContinuationImport(sourcePath.trim(), encoding || undefined);
      const normalized = await normalizeChapters(created.chapters);
      const saved = await replaceContinuationChapters(created.session_id, created.revision, normalized);
      setSession(saved);
      setChapters(saved.chapters);
      setSelectedChapter(0);
      await startContinuationAnalysis(saved.session_id);
      const next = await fetchContinuationImport(saved.session_id);
      setSession(next);
      setStep("analysis");
      if (next.status === "ready") {
        const result = await fetchContinuationAnalysis(next.session_id);
        setAnalysis(result);
        setBusy("");
        if (result.needs_confirmation.length) {
          setError("分析仍有待确认内容，处理后才能快速续写。");
        } else {
          setQuickConfirm(true);
        }
      } else if (next.status === "failed") {
        setBusy("");
        setError(ERROR_TEXT[next.error] ?? next.error ?? "分析失败，请重试。");
      }
    } catch (caught) {
      setBusy("");
      setError(errorText(caught));
    }
  }

  function updateChapter(patch: Partial<ContinuationChapter>) {
    setChapters((items) => items.map((item, index) => index === selectedChapter ? { ...item, ...patch } : item));
  }

  function moveChapter(offset: number) {
    const target = selectedChapter + offset;
    if (target < 0 || target >= chapters.length) return;
    const next = [...chapters];
    [next[selectedChapter], next[target]] = [next[target], next[selectedChapter]];
    setChapters(next.map((chapter, index) => ({ ...chapter, number: index + 1 })));
    setSelectedChapter(target);
  }

  function mergePrevious() {
    if (!currentChapter || selectedChapter === 0) return;
    const next = [...chapters];
    next[selectedChapter - 1] = {
      ...next[selectedChapter - 1],
      body: `${next[selectedChapter - 1].body.trim()}\n\n${currentChapter.body.trim()}`,
      source_end: Math.max(next[selectedChapter - 1].source_end, currentChapter.source_end),
    };
    next.splice(selectedChapter, 1);
    setChapters(next.map((chapter, index) => ({ ...chapter, number: index + 1 })));
    setSelectedChapter(selectedChapter - 1);
  }

  function splitAtCursor() {
    if (!currentChapter || !bodyRef.current) return;
    const point = bodyRef.current.selectionStart;
    const before = currentChapter.body.slice(0, point).trim();
    const after = currentChapter.body.slice(point).trim();
    if (!before || !after) {
      setError("请把光标放在正文中间再拆分章节。");
      return;
    }
    const split: ContinuationChapter = {
      ...currentChapter,
      chapter_id: `${currentChapter.chapter_id}-split-${Date.now()}`,
      title: `${currentChapter.title}（下）`,
      body: after,
      source_start: currentChapter.source_start + point,
      fingerprint: "pending",
    };
    const next = [...chapters];
    next[selectedChapter] = { ...currentChapter, body: before, title: currentChapter.title.replace(/（下）$/, "") };
    next.splice(selectedChapter + 1, 0, split);
    setChapters(next.map((chapter, index) => ({ ...chapter, number: index + 1 })));
    setSelectedChapter(selectedChapter + 1);
    setError("");
  }

  async function saveChapters() {
    if (!session) return;
    if (chapters.some((chapter) => !chapter.title.trim() || !chapter.body.trim())) {
      setError("章节标题和正文不能为空。");
      return;
    }
    setBusy("chapters");
    setError("");
    try {
      const normalized = await normalizeChapters(chapters);
      const result = await replaceContinuationChapters(session.session_id, session.revision, normalized);
      setSession(result);
      setChapters(result.chapters);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy("");
    }
  }

  async function analyze() {
    if (!session) return;
    setBusy("analysis");
    setError("");
    try {
      const normalized = await normalizeChapters(chapters);
      const saved = await replaceContinuationChapters(session.session_id, session.revision, normalized);
      setSession(saved);
      setChapters(saved.chapters);
      await startContinuationAnalysis(saved.session_id);
      const next = await fetchContinuationImport(saved.session_id);
      setSession(next);
      setStep("analysis");
      if (next.status === "ready") {
        setAnalysis(await fetchContinuationAnalysis(next.session_id));
        setBusy("");
      } else if (next.status === "failed") {
        setBusy("");
        setError(ERROR_TEXT[next.error] ?? next.error ?? "分析失败，请重试。");
      }
    } catch (caught) {
      setBusy("");
      setError(errorText(caught));
    }
  }

  function updateAnalysis(mutator: (draft: ContinuationAnalysis) => void) {
    setAnalysis((value) => {
      if (!value) return value;
      const next = structuredClone(value);
      mutator(next);
      return next;
    });
  }

  async function confirmAnalysis() {
    if (!session || !analysis) return;
    if (analysis.needs_confirmation.length) {
      setError("请先处理全部待确认冲突。");
      return;
    }
    setBusy("confirm");
    setError("");
    try {
      const result = await confirmContinuationAnalysis(session.session_id, session.revision, analysis);
      setSession(result);
      setStep("settings");
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy("");
    }
  }

  function showQuickConfirmation() {
    if (!analysis) return;
    if (analysis.needs_confirmation.length) {
      setError("分析仍有待确认内容，处理后才能快速续写。");
      return;
    }
    setError("");
    setQuickConfirm(true);
  }

  async function runQuickContinuation() {
    if (!session || !analysis) return;
    if (analysis.needs_confirmation.length) {
      setError("分析仍有待确认内容，处理后才能快速续写。");
      return;
    }
    setBusy("quick");
    setError("");
    try {
      const saved = await confirmContinuationAnalysis(session.session_id, session.revision, analysis);
      setSession(saved);
      const result = await quickContinueNovel(saved.session_id);
      router.push(result.project_route);
    } catch (caught) {
      setBusy("");
      setError(errorText(caught));
    }
  }

  async function finish() {
    if (!session) return;
    setBusy("create");
    setError("");
    try {
      const result = await createContinuationProject(session.session_id, session.revision, {
        start_after_chapter: startAfterChapter,
        fidelity,
        target_chars: targetChars,
        direction: direction.trim(),
        planned_chapters: 0,
        must_preserve: mustPreserve.split("\n").map((item) => item.trim()).filter(Boolean),
        forbidden_content: forbiddenContent.split("\n").map((item) => item.trim()).filter(Boolean),
        generate_outline: generateOutline,
        outline_chapters: generateOutline ? outlineChapters : 0,
        novel_type_id: novelTypeId,
      });
      router.push(result.next_path);
    } catch (caught) {
      setError(errorText(caught));
      setBusy("");
    }
  }

  return (
    <section className="ws-continuation" role="tabpanel" aria-labelledby="creation-mode-continuation">
      <ol className="ws-continuation__steps" aria-label="续写导入步骤">
        {STEPS.map((item, index) => (
          <li key={item.id} className={index === activeStepIndex ? "is-active" : index < activeStepIndex ? "is-done" : ""}>
            <span>{index < activeStepIndex ? <Check size={14} /> : index + 1}</span>{item.label}
          </li>
        ))}
      </ol>

      {error ? <p className="ws-continuation__alert is-error" role="alert"><AlertTriangle size={17} />{error}</p> : null}

      {step === "source" ? (
        <div className="ws-continuation__panel">
          <div className="ws-continuation__heading"><div><h2>选择小说来源</h2><p>选择单个 TXT、Markdown 文件，或包含多章文件的目录。</p></div></div>
          <label className="ws-project-create__field ws-project-create__field--wide">
            <span>小说文件或目录路径</span>
            <div className="ws-continuation__path-row">
              <input value={sourcePath} onChange={(event) => setSourcePath(event.target.value)} placeholder="D:\\novels\\my-story" />
              <button type="button" className="ws-btn" disabled={!sourcePath.trim() || Boolean(busy)} onClick={() => void browse(sourcePath)}><Folder size={16} />浏览</button>
            </div>
          </label>
          <div className="ws-continuation__browser" aria-label="来源浏览器">
            {sources.current_path ? <button type="button" className="ws-continuation__back" onClick={() => void browse(sources.current_path.replace(/[\\/][^\\/]+$/, ""))}><ArrowLeft size={15} />上一级</button> : null}
            {[...sources.directories, ...sources.files].map((item) => {
              const directory = sources.directories.some((candidate) => candidate.path === item.path);
              return <button type="button" key={item.path} onClick={() => directory ? void browse(item.path) : setSourcePath(item.path)}><span>{directory ? <Folder size={17} /> : <FileText size={17} />}{item.name}</span><ChevronRight size={15} /></button>;
            })}
            {!sources.directories.length && !sources.files.length ? <p>此处没有可选择的 TXT、Markdown 文件或目录。</p> : null}
          </div>
          {showEncoding ? <label className="ws-project-create__field"><span>文本编码</span><select value={encoding} onChange={(event) => setEncoding(event.target.value)}><option value="">请选择</option><option value="utf-8">UTF-8</option><option value="gb18030">GB18030</option><option value="gbk">GBK</option><option value="big5">Big5</option><option value="utf-16-le">UTF-16 LE</option><option value="utf-16-be">UTF-16 BE</option></select></label> : null}
          {scan ? (
            <div className="ws-continuation__scan-summary">
              <strong>识别到 {scan.chapters.length} 章</strong><span>{scan.total_chars.toLocaleString()} 字符 · {scan.encoding}</span>
              {scan.warnings.map((warning) => <p key={warning}><AlertTriangle size={15} />{warning}</p>)}
              {scan.duplicate_groups.length ? <p><AlertTriangle size={15} />发现 {scan.duplicate_groups.length} 组重复章节</p> : null}
              {scan.numbering_gaps.length ? <p><AlertTriangle size={15} />章节序号缺失：{scan.numbering_gaps.join("、")}</p> : null}
            </div>
          ) : null}
          <div className="ws-continuation__actions">
            <button type="button" className="ws-btn" disabled={!sourcePath.trim() || Boolean(busy) || (showEncoding && !encoding)} onClick={() => void performScan()}>{busy === "scan" ? <LoaderCircle className="is-spinning" size={16} /> : null}{scan ? "重新扫描" : "扫描来源"}</button>
            {scan ? <button type="button" className="ws-btn" disabled={!scan.can_analyze || Boolean(busy)} onClick={() => void quickFromSource()}><Zap size={16} />快速续写</button> : null}
            {scan ? <button type="button" className="ws-btn ws-btn--primary" disabled={!scan.chapters.length || Boolean(busy)} onClick={() => void createSession()}>进入章节校对</button> : null}
          </div>
        </div>
      ) : null}

      {step === "chapters" ? (
        <div className="ws-continuation__panel">
          <div className="ws-continuation__heading"><div><h2>校对章节</h2><p>共 {chapters.length} 章，保存后再启动分析。</p></div><button type="button" className="ws-btn ws-btn--sm" disabled={Boolean(busy)} onClick={() => void saveChapters()}>保存章节</button></div>
          {chapterBlockers.length ? <div className="ws-continuation__alert" role="alert"><AlertTriangle size={17} />{chapterBlockers.join("；")}</div> : null}
          <div className="ws-continuation__chapter-layout">
            <nav className="ws-continuation__chapter-list" aria-label="导入章节">
              {chapters.map((chapter, index) => <button type="button" key={chapter.chapter_id} className={index === selectedChapter ? "is-active" : ""} onClick={() => setSelectedChapter(index)}><span>第 {index + 1} 章</span><strong>{chapter.title}</strong></button>)}
            </nav>
            {currentChapter ? <div className="ws-continuation__chapter-editor">
              <label className="ws-project-create__field"><span>章节名</span><input value={currentChapter.title} onChange={(event) => updateChapter({ title: event.target.value })} /></label>
              <label className="ws-project-create__field"><span>正文</span><textarea ref={bodyRef} rows={18} value={currentChapter.body} onChange={(event) => updateChapter({ body: event.target.value })} /></label>
              <div className="ws-continuation__tools" aria-label="章节编辑工具">
                <button type="button" className="ws-btn ws-btn--sm" title="上移章节" disabled={selectedChapter === 0} onClick={() => moveChapter(-1)}><ArrowUp size={15} />上移</button>
                <button type="button" className="ws-btn ws-btn--sm" title="下移章节" disabled={selectedChapter === chapters.length - 1} onClick={() => moveChapter(1)}><ArrowDown size={15} />下移</button>
                <button type="button" className="ws-btn ws-btn--sm" disabled={selectedChapter === 0} onClick={mergePrevious}><Merge size={15} />合并上一章</button>
                <button type="button" className="ws-btn ws-btn--sm" onClick={splitAtCursor}><Scissors size={15} />按光标拆分</button>
              </div>
            </div> : null}
          </div>
          <div className="ws-continuation__actions"><button type="button" className="ws-btn ws-btn--primary" disabled={Boolean(busy) || !session || chapterBlockers.length > 0} onClick={() => void analyze()}>{busy === "analysis" ? <LoaderCircle className="is-spinning" size={16} /> : null}保存并分析</button></div>
        </div>
      ) : null}

      {step === "analysis" ? (
        <div className="ws-continuation__panel">
          <div className="ws-continuation__heading"><div><h2>确认分析结果</h2><p>推断内容可修改；有冲突的条目必须处理后才能继续。</p></div></div>
          {session?.status === "analyzing" ? <div className="ws-continuation__analyzing" role="status"><LoaderCircle className="is-spinning" size={22} /><strong>正在分析小说</strong><span>可停留在此页等待，完成后会自动刷新。</span></div> : null}
          {session?.status === "failed" ? <div className="ws-continuation__actions"><button type="button" className="ws-btn" onClick={() => void analyze()}>重新分析</button></div> : null}
          {analysis ? <>
            <div className="ws-continuation__analysis-tabs" role="tablist" aria-label="分析内容">{ANALYSIS_TABS.map((item) => <button key={item.id} type="button" role="tab" aria-selected={analysisTab === item.id} className={analysisTab === item.id ? "is-active" : ""} onClick={() => setAnalysisTab(item.id)}>{item.label}</button>)}</div>
            <div className="ws-continuation__analysis-body" role="tabpanel">
              {analysisTab === "overview" ? <label className="ws-project-create__field"><span>故事概况</span><textarea rows={8} value={analysis.story_overview} onChange={(event) => updateAnalysis((draft) => { draft.story_overview = event.target.value; })} /></label> : null}
              {analysisTab === "characters" ? analysis.characters.map((character, index) => <article className="ws-continuation__analysis-item" key={`${character.name}-${index}`}><header><strong>{character.name}</strong><ConfidenceTag value={character.confidence} /></header><input aria-label={`${character.name}角色定位`} value={character.role} onChange={(event) => updateAnalysis((draft) => { draft.characters[index].role = event.target.value; })} /><textarea aria-label={`${character.name}人物摘要`} rows={4} value={character.summary} onChange={(event) => updateAnalysis((draft) => { draft.characters[index].summary = event.target.value; })} />{character.evidence.map((evidence, evidenceIndex) => <EvidenceButton key={evidenceIndex} evidence={evidence} chapters={chapters} />)}</article>) : null}
              {analysisTab === "world" ? analysis.world.map((item, index) => <AnalysisClaimEditor key={index} label="世界设定" item={item} chapters={chapters} onChange={(value) => updateAnalysis((draft) => { draft.world[index].claim = value; })} />) : null}
              {analysisTab === "power" ? analysis.power_system.map((item, index) => <AnalysisClaimEditor key={index} label="力量规则" item={item} chapters={chapters} onChange={(value) => updateAnalysis((draft) => { draft.power_system[index].claim = value; })} />) : null}
              {analysisTab === "timeline" ? analysis.timeline.map((item, index) => <article className="ws-continuation__analysis-item" key={index}><header><span>{item.sequence || `事件 ${index + 1}`}</span><ConfidenceTag value={item.confidence} /></header><textarea aria-label={`时间线事件 ${index + 1}`} rows={3} value={item.text} onChange={(event) => updateAnalysis((draft) => { draft.timeline[index].text = event.target.value; })} />{item.evidence.map((evidence, evidenceIndex) => <EvidenceButton key={evidenceIndex} evidence={evidence} chapters={chapters} />)}</article>) : null}
              {analysisTab === "hooks" ? analysis.open_hooks.map((item, index) => <article className="ws-continuation__analysis-item" key={index}><header><span>{item.status === "open" ? "未回收" : item.status === "resolved" ? "已回收" : "待判断"}</span><ConfidenceTag value={item.confidence} /></header><textarea aria-label={`伏笔 ${index + 1}`} rows={3} value={item.text} onChange={(event) => updateAnalysis((draft) => { draft.open_hooks[index].text = event.target.value; })} />{item.evidence.map((evidence, evidenceIndex) => <EvidenceButton key={evidenceIndex} evidence={evidence} chapters={chapters} />)}</article>) : null}
              {analysisTab === "style" ? <div className="ws-continuation__style-grid">{(["narrative_voice", "point_of_view", "tense", "pacing", "dialogue_style"] as const).map((key) => <label className="ws-project-create__field" key={key}><span>{{ narrative_voice: "叙事声音", point_of_view: "视角", tense: "时态", pacing: "节奏", dialogue_style: "对白风格" }[key]}</span><input value={analysis.style_profile[key]} onChange={(event) => updateAnalysis((draft) => { draft.style_profile[key] = event.target.value; })} /></label>)}</div> : null}
              {analysisTab === "start" ? <div className="ws-continuation__style-grid"><label className="ws-project-create__field"><span>当前局面</span><textarea rows={5} value={analysis.continuation_start.situation} onChange={(event) => updateAnalysis((draft) => { draft.continuation_start.situation = event.target.value; })} /></label><label className="ws-project-create__field"><span>续写建议</span><textarea rows={5} value={analysis.continuation_start.guidance} onChange={(event) => updateAnalysis((draft) => { draft.continuation_start.guidance = event.target.value; })} /></label></div> : null}
            </div>
            {analysis.needs_confirmation.length ? <div className="ws-continuation__conflicts"><h3>待确认冲突</h3>{analysis.needs_confirmation.map((item, index) => <div key={`${item.source}-${index}`}><label><span>{item.source}</span><input value={item.claim} onChange={(event) => updateAnalysis((draft) => { draft.needs_confirmation[index].claim = event.target.value; })} /></label><button type="button" className="ws-btn ws-btn--sm" onClick={() => updateAnalysis((draft) => { draft.needs_confirmation.splice(index, 1); })}>标记已处理</button></div>)}</div> : null}
            {quickConfirm ? <section className="ws-continuation__quick-confirm" role="dialog" aria-label="快速续写确认">
              <div><strong>快速续写确认</strong><span>将从第 {Math.max(...chapters.map((chapter) => chapter.number))} 章之后开始</span></div>
              <dl><div><dt>模式</dt><dd>忠实续写</dd></div><div><dt>目标</dt><dd>4,500 字</dd></div><div><dt>方向</dt><dd>{analysis.continuation_start.guidance || analysis.continuation_start.situation || analysis.story_overview || "延续当前剧情"}</dd></div></dl>
              <div className="ws-continuation__actions"><button type="button" className="ws-btn" disabled={Boolean(busy)} onClick={() => setQuickConfirm(false)}>返回调整</button><button type="button" className="ws-btn ws-btn--primary" disabled={Boolean(busy)} onClick={() => void runQuickContinuation()}>{busy === "quick" ? <LoaderCircle className="is-spinning" size={16} /> : <Zap size={16} />}确认并生成下一章</button></div>
            </section> : null}
            <div className="ws-continuation__actions"><button type="button" className="ws-btn" disabled={Boolean(busy)} onClick={showQuickConfirmation}><Zap size={16} />快速续写</button><button type="button" className="ws-btn ws-btn--primary" disabled={Boolean(busy) || analysis.needs_confirmation.length > 0} onClick={() => void confirmAnalysis()}>{busy === "confirm" ? <LoaderCircle className="is-spinning" size={16} /> : null}确认分析结果</button></div>
          </> : null}
        </div>
      ) : null}

      {step === "settings" ? (
        <div className="ws-continuation__panel">
          <div className="ws-continuation__heading"><div><h2>设置续写方式</h2><p>选择从哪里接续，以及新章节需要遵守的边界。</p></div></div>
          <div className="ws-continuation__settings-grid">
            <label className="ws-project-create__field"><span>从哪一章之后续写</span><select value={startAfterChapter} onChange={(event) => setStartAfterChapter(Number(event.target.value))}>{chapters.map((chapter) => <option key={chapter.chapter_id} value={chapter.number}>第 {chapter.number} 章 · {chapter.title}</option>)}</select></label>
            <fieldset className="ws-continuation__segmented"><legend>续写模式</legend><button type="button" className={fidelity === "faithful" ? "is-active" : ""} aria-pressed={fidelity === "faithful"} onClick={() => setFidelity("faithful")}>忠实续写</button><button type="button" className={fidelity === "adaptive" ? "is-active" : ""} aria-pressed={fidelity === "adaptive"} onClick={() => setFidelity("adaptive")}>适度改编</button></fieldset>
            <label className="ws-project-create__field"><span>每章目标字数</span><input type="number" min={1000} max={20000} step={100} value={targetChars} onChange={(event) => setTargetChars(Number(event.target.value))} /></label>
            <label className="ws-project-create__field"><span>小说类型</span><select value={novelTypeId} onChange={(event) => setNovelTypeId(event.target.value)}>{novelTypes.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <label className="ws-project-create__field ws-project-create__field--wide"><span>后续方向</span><textarea rows={4} maxLength={1000} value={direction} onChange={(event) => setDirection(event.target.value)} /></label>
            <label className="ws-project-create__field"><span>必须保留 <small>每行一条</small></span><textarea rows={5} value={mustPreserve} onChange={(event) => setMustPreserve(event.target.value)} /></label>
            <label className="ws-project-create__field"><span>禁止内容 <small>每行一条</small></span><textarea rows={5} value={forbiddenContent} onChange={(event) => setForbiddenContent(event.target.value)} /></label>
            <label className="ws-continuation__toggle"><input type="checkbox" checked={generateOutline} onChange={(event) => setGenerateOutline(event.target.checked)} /><span>同时生成后续大纲</span></label>
            {generateOutline ? <label className="ws-project-create__field"><span>大纲章节数</span><input type="number" min={5} max={30} value={outlineChapters} onChange={(event) => setOutlineChapters(Number(event.target.value))} /></label> : null}
          </div>
          <div className="ws-continuation__actions"><button type="button" className="ws-btn ws-btn--primary" disabled={Boolean(busy) || !session || targetChars < 1000 || targetChars > 20000 || (generateOutline && (outlineChapters < 5 || outlineChapters > 30))} onClick={() => void finish()}>{busy === "create" ? <LoaderCircle className="is-spinning" size={16} /> : null}创建续写项目</button></div>
        </div>
      ) : null}
    </section>
  );
}

function AnalysisClaimEditor({ label, item, chapters, onChange }: { label: string; item: { claim: string; confidence: "confirmed" | "inferred"; evidence: ContinuationEvidenceRef[] }; chapters: ContinuationChapter[]; onChange: (value: string) => void }) {
  return <article className="ws-continuation__analysis-item"><header><span>{label}</span><ConfidenceTag value={item.confidence} /></header><textarea aria-label={label} rows={3} value={item.claim} onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onChange(event.target.value)} />{item.evidence.map((evidence, index) => <EvidenceButton key={index} evidence={evidence} chapters={chapters} />)}</article>;
}
