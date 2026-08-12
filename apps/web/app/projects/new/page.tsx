"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import { PageHeader } from "../../../components/ws/PageHeader";
import { ContinuationImportWizard } from "../../../components/ContinuationImportWizard";
import {
  createFileProject,
  fetchNovelTypes as listNovelTypes,
  listSkillPacks,
  type NovelType,
} from "../../../lib/api";
import { DEFAULT_NOVEL_TYPE_ID } from "../../../lib/novelTypes";

type CreationMode = "inspiration" | "blank" | "continuation";
type EnhancementAvailability = "loading" | "available" | "missing" | "incomplete" | "error";

const COMMERCIAL_SHUANGWEN_REQUIRED_MODULE_PURPOSES = {
  "plot-engine": ["outline"],
  "chapter-sop": ["chapter_plan"],
  "writer-execution": ["writer"],
  "review-checklist": ["reviewer"],
  "genre-examples": ["outline", "chapter_plan", "writer"],
} as const;

export default function NewProjectPage() {
  const router = useRouter();
  const inspirationTabRef = useRef<HTMLButtonElement>(null);
  const blankTabRef = useRef<HTMLButtonElement>(null);
  const continuationTabRef = useRef<HTMLButtonElement>(null);
  const mountedRef = useRef(true);
  const submitRequestIdRef = useRef(0);
  const typeSelectionTouchedRef = useRef(false);
  const [mode, setMode] = useState<CreationMode>("inspiration");
  const [title, setTitle] = useState("");
  const [novelTypeId, setNovelTypeId] = useState("");
  const [novelTypes, setNovelTypes] = useState<NovelType[]>([]);
  const [typesLoading, setTypesLoading] = useState(true);
  const [typesError, setTypesError] = useState("");
  const [typesLoadVersion, setTypesLoadVersion] = useState(0);
  const [idea, setIdea] = useState("");
  const [commercialShuangwenEnabled, setCommercialShuangwenEnabled] = useState(false);
  const [commercialShuangwenAvailability, setCommercialShuangwenAvailability] =
    useState<EnhancementAvailability>("loading");
  const [commercialShuangwenUnavailableReason, setCommercialShuangwenUnavailableReason] =
    useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      submitRequestIdRef.current += 1;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setTypesLoading(true);
    setTypesError("");

    void listNovelTypes()
      .then((types) => {
        if (cancelled) return;
        setNovelTypes(types);
        if (!typeSelectionTouchedRef.current) {
          const defaultType = types.find((type) => type.id === DEFAULT_NOVEL_TYPE_ID) ?? types[0];
          setNovelTypeId(defaultType?.id ?? "");
        }
      })
      .catch(() => {
        if (cancelled) return;
        setNovelTypes([]);
        setTypesError("小说类型加载失败，请检查服务连接后重试。");
      })
      .finally(() => {
        if (!cancelled) setTypesLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [typesLoadVersion]);

  useEffect(() => {
    let cancelled = false;

    void listSkillPacks()
      .then((packs) => {
        if (cancelled) return;
        const pack = packs.find((item) => item.skill_id === "commercial-shuangwen");
        if (!pack) {
          setCommercialShuangwenAvailability("missing");
          setCommercialShuangwenUnavailableReason("skill_pack_missing");
          setCommercialShuangwenEnabled(false);
          return;
        }
        const installedModules = new Map(pack.modules.map((module) => [module.module_id, module]));
        const missingModuleIds = Object.keys(COMMERCIAL_SHUANGWEN_REQUIRED_MODULE_PURPOSES).filter(
          (moduleId) => !installedModules.has(moduleId),
        );
        const localPurposeMismatches = Object.entries(
          COMMERCIAL_SHUANGWEN_REQUIRED_MODULE_PURPOSES,
        ).flatMap(([moduleId, requiredPurposes]) => {
          const module = installedModules.get(moduleId);
          if (!module) return [];
          const actualPurposes = new Set(module.purposes ?? []);
          const requiredPurposeSet = new Set<string>(requiredPurposes);
          const missingPurposes = requiredPurposes.filter((purpose) => !actualPurposes.has(purpose));
          const unexpectedPurposes = [...actualPurposes].filter(
            (purpose) => !requiredPurposeSet.has(purpose),
          );
          return missingPurposes.length > 0 || unexpectedPurposes.length > 0
            ? [{
                module_id: moduleId,
                missing_purposes: missingPurposes,
                unexpected_purposes: unexpectedPurposes,
              }]
            : [];
        });
        const status = pack.narrative_enhancement_status;
        const reportedMissing = status?.missing_module_ids ?? [];
        const effectiveMissing = reportedMissing.length > 0 ? reportedMissing : missingModuleIds;
        const reportedPurposeMismatches = status?.purpose_mismatches ?? [];
        const effectivePurposeMismatches = reportedPurposeMismatches.length > 0
          ? reportedPurposeMismatches
          : localPurposeMismatches;
        if (
          status?.status === "incomplete"
          || effectiveMissing.length > 0
          || effectivePurposeMismatches.length > 0
        ) {
          const reasons = [];
          if (effectiveMissing.length > 0) {
            reasons.push(`缺少必需模块：${effectiveMissing.join(", ")}`);
          }
          if (effectivePurposeMismatches.length > 0) {
            reasons.push(
              `模块用途不匹配：${effectivePurposeMismatches
                .map((mismatch) => {
                  const details = [];
                  if (mismatch.missing_purposes.length > 0) {
                    details.push(`缺少 ${mismatch.missing_purposes.join("+")}`);
                  }
                  if ((mismatch.unexpected_purposes ?? []).length > 0) {
                    details.push(`多出 ${mismatch.unexpected_purposes.join("+")}`);
                  }
                  return `${mismatch.module_id} ${details.join("，")}`;
                })
                .join(", ")}`,
            );
          }
          setCommercialShuangwenAvailability("incomplete");
          setCommercialShuangwenUnavailableReason(reasons.join("；"));
          setCommercialShuangwenEnabled(false);
          return;
        }
        if (status && status.status !== "available") {
          setCommercialShuangwenAvailability("missing");
          setCommercialShuangwenUnavailableReason(status.reason || "skill_pack_unavailable");
          setCommercialShuangwenEnabled(false);
          return;
        }
        setCommercialShuangwenAvailability("available");
        setCommercialShuangwenUnavailableReason("");
      })
      .catch(() => {
        if (cancelled) return;
        setCommercialShuangwenAvailability("error");
        setCommercialShuangwenUnavailableReason("skill_pack_list_failed");
        setCommercialShuangwenEnabled(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const selectedNovelType = useMemo(
    () => novelTypes.find((type) => type.id === novelTypeId),
    [novelTypeId, novelTypes],
  );

  const canSubmit = useMemo(() => {
    if (typesLoading || typesError || !selectedNovelType) return false;
    if (mode === "continuation") return false;
    return mode === "blank" ? Boolean(title.trim()) : Boolean(idea.trim());
  }, [idea, mode, selectedNovelType, title, typesError, typesLoading]);

  function selectMode(nextMode: CreationMode) {
    setMode(nextMode);
    setError("");
  }

  function focusMode(nextMode: CreationMode) {
    selectMode(nextMode);
    const nextTab = nextMode === "inspiration" ? inspirationTabRef : nextMode === "blank" ? blankTabRef : continuationTabRef;
    nextTab.current?.focus();
  }

  function handleModeKeyDown(event: KeyboardEvent<HTMLButtonElement>, currentMode: CreationMode) {
    let nextMode: CreationMode | null = null;
    if (event.key === "Home") nextMode = "inspiration";
    if (event.key === "End") nextMode = "continuation";
    if (event.key === "ArrowRight") nextMode = currentMode === "inspiration" ? "blank" : currentMode === "blank" ? "continuation" : "inspiration";
    if (event.key === "ArrowLeft") nextMode = currentMode === "inspiration" ? "continuation" : currentMode === "blank" ? "inspiration" : "blank";
    if (!nextMode) return;

    event.preventDefault();
    focusMode(nextMode);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit || submitting || mode === "continuation") return;

    const requestId = ++submitRequestIdRef.current;
    setSubmitting(true);
    setError("");
    try {
      const response = await createFileProject({
        mode,
        title: title.trim(),
        novel_type_id: novelTypeId,
        idea: mode === "inspiration" ? idea.trim() : "",
        ...(commercialShuangwenEnabled
          ? { narrative_enhancement_ids: ["commercial-shuangwen"] }
          : {}),
      });
      if (!mountedRef.current || requestId !== submitRequestIdRef.current) return;
      router.push(response.next_path);
    } catch (err) {
      if (!mountedRef.current || requestId !== submitRequestIdRef.current) return;
      const message = err instanceof Error ? err.message : String(err);
      setError(`创建失败：${message}`);
    } finally {
      if (mountedRef.current && requestId === submitRequestIdRef.current) setSubmitting(false);
    }
  }

  return (
    <div className="ws-page ws-page--narrow">
      <PageHeader
        crumbs={[{ label: "作品", href: "/projects" }, { label: "新建小说" }]}
        title="新建小说"
        subtitle="选择一个起点，建立新的写作项目。"
      />

      <section className="ws-project-create" aria-label="新建小说表单">
        <div className="ws-project-create__tabs" role="tablist" aria-label="创建方式" aria-orientation="horizontal">
          <button
            ref={inspirationTabRef}
            id="creation-mode-inspiration"
            type="button"
            role="tab"
            aria-selected={mode === "inspiration"}
            aria-controls="creation-form"
            tabIndex={mode === "inspiration" ? 0 : -1}
            className={`ws-project-create__tab${mode === "inspiration" ? " is-active" : ""}`}
            onClick={() => selectMode("inspiration")}
            onKeyDown={(event) => handleModeKeyDown(event, "inspiration")}
          >
            从灵感开书
          </button>
          <button
            ref={blankTabRef}
            id="creation-mode-blank"
            type="button"
            role="tab"
            aria-selected={mode === "blank"}
            aria-controls="creation-form"
            tabIndex={mode === "blank" ? 0 : -1}
            className={`ws-project-create__tab${mode === "blank" ? " is-active" : ""}`}
            onClick={() => selectMode("blank")}
            onKeyDown={(event) => handleModeKeyDown(event, "blank")}
          >
            建立空白小说
          </button>
          <button
            ref={continuationTabRef}
            id="creation-mode-continuation"
            type="button"
            role="tab"
            aria-selected={mode === "continuation"}
            aria-controls="continuation-import"
            tabIndex={mode === "continuation" ? 0 : -1}
            className={`ws-project-create__tab${mode === "continuation" ? " is-active" : ""}`}
            onClick={() => selectMode("continuation")}
            onKeyDown={(event) => handleModeKeyDown(event, "continuation")}
          >
            续写已有小说
          </button>
        </div>

        {mode === "continuation" ? (
          <div id="continuation-import">
            <ContinuationImportWizard novelTypes={novelTypes} />
          </div>
        ) : <form
          id="creation-form"
          className="ws-project-create__form"
          role="tabpanel"
          aria-labelledby={`creation-mode-${mode}`}
          onSubmit={handleSubmit}
        >
          <label className="ws-project-create__field">
            <span>小说类型</span>
            <select
              value={novelTypeId}
              onChange={(event) => {
                typeSelectionTouchedRef.current = true;
                setNovelTypeId(event.target.value);
              }}
              disabled={typesLoading || Boolean(typesError) || novelTypes.length === 0}
              required
            >
              {typesLoading ? <option value="">正在加载小说类型...</option> : null}
              {!typesLoading && novelTypes.length === 0 ? <option value="">暂无可用类型</option> : null}
              {novelTypes.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.name}
                </option>
              ))}
            </select>
            {selectedNovelType ? <small>{selectedNovelType.description}</small> : null}
          </label>

          <section className="ws-project-create__field--wide" aria-labelledby="narrative-enhancements-heading">
            <h2 id="narrative-enhancements-heading" className="ws-card__title">
              叙事增强
            </h2>
            <label className="checkbox-row">
              <input
                type="checkbox"
                aria-label="商业爽文推进"
                checked={commercialShuangwenEnabled}
                disabled={commercialShuangwenAvailability !== "available"}
                onChange={(event) => setCommercialShuangwenEnabled(event.target.checked)}
              />
              <span>
                <strong>商业爽文推进</strong>
                <br />
                <span className="ws-card__hint">需求、压制、反击、回报；按题材加载具体例子。</span>
              </span>
            </label>
            {commercialShuangwenAvailability === "missing" ? (
              <p className="ws-project-create__error" role="alert">
                未安装“商业爽文推进”叙事增强，当前不可用。
              </p>
            ) : null}
            {commercialShuangwenAvailability === "incomplete" ? (
              <p className="ws-project-create__error" role="alert">
                “商业爽文推进”配置不完整：{commercialShuangwenUnavailableReason}，当前不可用。
              </p>
            ) : null}
            {commercialShuangwenAvailability === "error" ? (
              <p className="ws-project-create__error" role="alert">
                叙事增强列表加载失败，“商业爽文推进”当前不可用。
              </p>
            ) : null}
          </section>

          {typesError ? (
            <div className="ws-project-create__error" role="alert">
              <p>{typesError}</p>
              <button type="button" className="ws-btn" onClick={() => setTypesLoadVersion((value) => value + 1)}>
                重新加载
              </button>
            </div>
          ) : null}

          {!typesLoading && !typesError && novelTypes.length === 0 ? (
            <p className="ws-project-create__error" role="alert">
              小说类型库为空，请先在全局小说类型库中添加类型后再创建小说。
            </p>
          ) : null}

          <label className="ws-project-create__field">
            <span>
              小说名 <small>{mode === "blank" ? "必填" : "选填"}</small>
            </span>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              maxLength={120}
              required={mode === "blank"}
              autoComplete="off"
            />
          </label>

          {mode === "inspiration" ? (
            <label className="ws-project-create__field ws-project-create__field--wide">
              <span>
                灵感 <small>必填</small>
              </span>
              <textarea
                value={idea}
                onChange={(event) => setIdea(event.target.value)}
                maxLength={1000}
                required
                rows={6}
              />
              <small className="ws-project-create__count">{idea.length} / 1000</small>
            </label>
          ) : null}

          {error ? (
            <p className="ws-project-create__error" role="alert">
              {error}
            </p>
          ) : null}

          <div className="ws-project-create__actions">
            <button className="ws-btn ws-btn--primary" type="submit" disabled={!canSubmit || submitting}>
              {submitting ? "创建中..." : "创建小说"}
            </button>
          </div>
        </form>}
      </section>
    </div>
  );
}
