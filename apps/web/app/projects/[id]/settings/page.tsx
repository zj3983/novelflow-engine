"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import {
  fetchNovelTypes as listNovelTypes,
  updateProject,
  type ImportedWorldBlueprint,
  type NovelType,
  type ProjectStatus,
} from "../../../../lib/api";
import { DEFAULT_NOVEL_TYPE_ID } from "../../../../lib/novelTypes";

const SOURCE_LABEL = {
  sqlite: "数据库",
  file: "文件夹",
} as const;

import { userFacingErrorMessage } from "../../../../lib/user-facing-error";

const STATUS_LABEL = {
  draft: "草稿",
  outlining: "大纲中",
  writing: "写作中",
  reviewing: "审核中",
  simulating: "生成中",
  paused: "已暂停",
  completed: "已完成",
} as const;

const BOOK_STYLE_OPTIONS = ["幽默", "轻松", "热血", "冷峻", "细腻"] as const;

function statusLabel(status: ProjectStatus | undefined): string {
  const key = String(status || "draft");
  return key in STATUS_LABEL ? STATUS_LABEL[key as keyof typeof STATUS_LABEL] : key;
}

type TypeMessage = {
  kind: "success" | "error";
  text: string;
};

export default function ProjectSettingsPage() {
  const { project, story, loading: projectLoading, error, encodedProjectId, projectId, refresh } = useProjectWorkspace();
  const source = project?.storage_source ? SOURCE_LABEL[project.storage_source] : "数据库";
  const mountedRef = useRef(true);
  const saveRequestIdRef = useRef(0);
  const saveStyleRequestIdRef = useRef(0);
  const saveWritingRequestIdRef = useRef(0);
  const writingDraftTouchedRef = useRef(false);
  const typeSelectionTouchedRef = useRef(false);
  const typeSelectionInitializedRef = useRef(false);
  const [novelTypes, setNovelTypes] = useState<NovelType[]>([]);
  const [selectedTypeId, setSelectedTypeId] = useState("");
  const [typesLoading, setTypesLoading] = useState(true);
  const [typesError, setTypesError] = useState("");
  const [typesLoadVersion, setTypesLoadVersion] = useState(0);
  const [savingType, setSavingType] = useState(false);
  const [typeMessage, setTypeMessage] = useState<TypeMessage | null>(null);
  const [selectedStyle, setSelectedStyle] = useState("");
  const [savingStyle, setSavingStyle] = useState(false);
  const [styleMessage, setStyleMessage] = useState<TypeMessage | null>(null);
  const [writingGuidance, setWritingGuidance] = useState("");
  const [writingReference, setWritingReference] = useState("");
  const [savingWriting, setSavingWriting] = useState(false);
  const [writingMessage, setWritingMessage] = useState<TypeMessage | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      saveRequestIdRef.current += 1;
      saveStyleRequestIdRef.current += 1;
      saveWritingRequestIdRef.current += 1;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setTypesLoading(true);
    setTypesError("");

    void listNovelTypes()
      .then((types) => {
        if (!cancelled) setNovelTypes(types);
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
    if (!project || typesLoading || typesError || typeSelectionInitializedRef.current) return;
    typeSelectionInitializedRef.current = true;
    if (!typeSelectionTouchedRef.current) {
      const configuredTypeId = project.world_blueprint?.genre_plugin_ids?.[0];
      const defaultType = novelTypes.find((type) => type.id === DEFAULT_NOVEL_TYPE_ID) ?? novelTypes[0];
      setSelectedTypeId(configuredTypeId || defaultType?.id || "");
    }
  }, [novelTypes, project, typesError, typesLoading]);

  useEffect(() => {
    setSelectedStyle(project?.world_blueprint?.writing_style || "");
  }, [project?.project_id, project?.world_blueprint?.writing_style]);

  useEffect(() => {
    saveWritingRequestIdRef.current += 1;
    setSavingWriting(false);
    writingDraftTouchedRef.current = false;
    setWritingGuidance("");
    setWritingReference("");
    setWritingMessage(null);
  }, [projectId]);

  useEffect(() => {
    if (!project || writingDraftTouchedRef.current) return;
    setWritingGuidance(project.world_blueprint?.writing_guidance || "");
    setWritingReference(project.world_blueprint?.writing_reference || "");
  }, [project?.project_id, project?.world_blueprint?.writing_guidance, project?.world_blueprint?.writing_reference]);

  const writingChanged = writingGuidance.trim() !== (project?.world_blueprint?.writing_guidance || "")
    || writingReference.trim() !== (project?.world_blueprint?.writing_reference || "");

  const selectedType = useMemo(
    () => novelTypes.find((type) => type.id === selectedTypeId),
    [novelTypes, selectedTypeId],
  );
  const hasUnknownType = Boolean(selectedTypeId && !typesLoading && !typesError && !selectedType);

  async function saveNovelType(nextTypeId: string) {
    if (!project) return;
    const previousTypeId = selectedTypeId;
    const requestId = ++saveRequestIdRef.current;
    typeSelectionTouchedRef.current = true;
    setSelectedTypeId(nextTypeId);
    setSavingType(true);
    setTypeMessage(null);
    try {
      const nextBlueprint: ImportedWorldBlueprint = {
        genre_plugin_ids: [nextTypeId],
      };
      await updateProject(projectId, { world_blueprint: nextBlueprint }, { fallbackToMock: false });
      if (!mountedRef.current || requestId !== saveRequestIdRef.current) return;
      const nextTypeName = novelTypes.find((type) => type.id === nextTypeId)?.name ?? nextTypeId;
      setTypeMessage({
        kind: "success",
        text: `小说类型已保存为：${nextTypeName}。下一次推演和写作包会读取这个类型。`,
      });
      void refresh().catch(() => undefined);
    } catch {
      if (!mountedRef.current || requestId !== saveRequestIdRef.current) return;
      setSelectedTypeId(previousTypeId);
      setTypeMessage({ kind: "error", text: "保存失败，请检查服务后重试。" });
    } finally {
      if (mountedRef.current && requestId === saveRequestIdRef.current) setSavingType(false);
    }
  }

  async function saveWritingStyle(nextStyle: string) {
    if (!project) return;
    const previousStyle = selectedStyle;
    const requestId = ++saveStyleRequestIdRef.current;
    setSelectedStyle(nextStyle);
    setSavingStyle(true);
    setStyleMessage(null);
    try {
      const nextBlueprint: ImportedWorldBlueprint = {
        writing_style: nextStyle,
      };
      await updateProject(projectId, { world_blueprint: nextBlueprint }, { fallbackToMock: false });
      if (!mountedRef.current || requestId !== saveStyleRequestIdRef.current) return;
      setStyleMessage({
        kind: "success",
        text: nextStyle
          ? `文风已保存为：${nextStyle}。下一次写作会读取这个选择。`
          : "已清空文风选择。下一次写作不会注入额外文风。",
      });
      void refresh().catch(() => undefined);
    } catch {
      if (!mountedRef.current || requestId !== saveStyleRequestIdRef.current) return;
      setSelectedStyle(previousStyle);
      setStyleMessage({ kind: "error", text: "文风保存失败，请检查服务后重试。" });
    } finally {
      if (mountedRef.current && requestId === saveStyleRequestIdRef.current) setSavingStyle(false);
    }
  }

  async function saveWritingPreferences() {
    if (!project || savingWriting) return;
    const requestId = ++saveWritingRequestIdRef.current;
    setSavingWriting(true);
    setWritingMessage(null);
    try {
      const saved = await updateProject(projectId, {
        world_blueprint: {
          writing_guidance: writingGuidance.trim(),
          writing_reference: writingReference.trim(),
        },
      }, { fallbackToMock: false });
      if (!mountedRef.current || requestId !== saveWritingRequestIdRef.current) return;
      setWritingGuidance(saved.world_blueprint?.writing_guidance || "");
      setWritingReference(saved.world_blueprint?.writing_reference || "");
      writingDraftTouchedRef.current = false;
      setWritingMessage({ kind: "success", text: "写法已保存，续写、连写和重写都会读取。现有章节保持原样。" });
      void refresh({ invalidateChapter: false }).catch(() => undefined);
    } catch {
      if (!mountedRef.current || requestId !== saveWritingRequestIdRef.current) return;
      setWritingMessage({ kind: "error", text: "写法保存失败，输入已保留，请重试。" });
    } finally {
      if (mountedRef.current && requestId === saveWritingRequestIdRef.current) setSavingWriting(false);
    }
  }

  return (
    <div className="ws-page ws-page--narrow">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="项目设置"
        subtitle="查看当前项目的基础信息和运行状态。"
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{userFacingErrorMessage(error)}</p>
        </div>
      ) : (
        <>
          <section className="ws-card ws-novel-type-card">
            <div className="ws-section-head">
              <div>
                <p className="ws-card__title">小说类型</p>
                <p className="ws-card__hint">类型决定会加载哪套题材规则。网游的背包、铜币、掉落、任务规则只应该来自“网游升级”。</p>
              </div>
              <span className="ws-toolbar__meta">{selectedType?.name ?? (selectedTypeId || "未选择")}</span>
            </div>
            <label className="ws-character-mini ws-novel-type-field">
              <strong>当前类型</strong>
              <select
                className="ws-input"
                value={selectedTypeId}
                disabled={!project || projectLoading || typesLoading || Boolean(typesError) || novelTypes.length === 0 || savingType}
                onChange={(event) => void saveNovelType(event.target.value)}
              >
                {typesLoading ? <option value="">正在加载小说类型...</option> : null}
                {hasUnknownType ? <option value={selectedTypeId}>未知类型（{selectedTypeId}）</option> : null}
                {!typesLoading && novelTypes.length === 0 ? <option value="">暂无可用类型</option> : null}
                {novelTypes.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.name}
                  </option>
                ))}
              </select>
            </label>
            {selectedType ? <p className="ws-card__hint">{selectedType.description}</p> : null}
            {hasUnknownType ? (
              <p className="ws-project-create__error" role="alert">
                项目引用的小说类型 {selectedTypeId} 已不存在。请选择有效类型并保存。
              </p>
            ) : null}
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
                小说类型库为空，请先在全局小说类型库中添加类型。
              </p>
            ) : null}
            {typeMessage?.kind === "success" ? (
              <p className="ws-card__hint" role="status" aria-live="polite">
                {typeMessage.text}
              </p>
            ) : null}
            {typeMessage?.kind === "error" ? (
              <p className="ws-project-create__error" role="alert" aria-live="assertive">
                {typeMessage.text}
              </p>
            ) : null}
          </section>

          <section className="ws-card ws-novel-type-card">
            <div className="ws-section-head">
              <div>
                <p className="ws-card__title">文风</p>
                <p className="ws-card__hint">保存后用于续写、连写和重写。文风决定表达倾向，自定义写法和参考片段帮助保持本书的声音。</p>
              </div>
              <span className="ws-toolbar__meta">{selectedStyle || "未选择"}</span>
            </div>
            <label className="ws-character-mini ws-novel-type-field">
              <strong>当前文风</strong>
              <select
                className="ws-input"
                value={selectedStyle}
                disabled={!project || projectLoading || savingStyle || savingWriting}
                onChange={(event) => void saveWritingStyle(event.target.value)}
              >
                <option value="">未选择</option>
                {BOOK_STYLE_OPTIONS.map((style) => (
                  <option key={style} value={style}>
                    {style}
                  </option>
                ))}
              </select>
            </label>
            <label className="ws-project-create__field">
              <span>自定义写法</span>
              <textarea
                className="ws-input"
                rows={5}
                maxLength={2000}
                aria-label="自定义写法"
                value={writingGuidance}
                disabled={!project || projectLoading || savingWriting}
                placeholder="例如：口语自然，嘴上吐槽、行动谨慎；网络梗随处境出现，危险时先行动，缓过气再接话。"
                onChange={(event) => {
                  writingDraftTouchedRef.current = true;
                  setWritingGuidance(event.target.value);
                  setWritingMessage(null);
                }}
              />
              <small>写人物如何反应、怎样接话，以及希望避免的写法。可以单独使用，无需选择预设文风。{writingGuidance.length}/2000</small>
            </label>
            <label className="ws-project-create__field">
              <span>参考片段</span>
              <textarea
                className="ws-input"
                rows={6}
                maxLength={4000}
                aria-label="参考片段"
                value={writingReference}
                disabled={!project || projectLoading || savingWriting}
                placeholder="粘贴你认可的一小段对白或正文，也可以记录适合本书的接话和吐槽示例。"
                onChange={(event) => {
                  writingDraftTouchedRef.current = true;
                  setWritingReference(event.target.value);
                  setWritingMessage(null);
                }}
              />
              <small>参考语气和节奏，不照抄原句，不把片段中的事件当作本书事实。剧情创意请写进故事想法或大纲。{writingReference.length}/4000</small>
            </label>
            <div className="ws-toolbar">
              <button
                type="button"
                className="ws-btn ws-btn--primary"
                disabled={!project || projectLoading || savingStyle || savingWriting || !writingChanged}
                onClick={() => void saveWritingPreferences()}
              >
                {savingWriting ? "保存中..." : "保存写法"}
              </button>
              <span className="ws-toolbar__meta">{writingChanged ? "有未保存的写法" : "保存后从下一次写作生效"}</span>
            </div>
            {writingMessage ? (
              <p
                className={writingMessage.kind === "error" ? "ws-project-create__error" : "ws-card__hint"}
                role={writingMessage.kind === "error" ? "alert" : "status"}
                aria-live={writingMessage.kind === "error" ? "assertive" : "polite"}
              >
                {writingMessage.text}
              </p>
            ) : null}
            {styleMessage?.kind === "success" ? (
              <p className="ws-card__hint" role="status" aria-live="polite">
                {styleMessage.text}
              </p>
            ) : null}
            {styleMessage?.kind === "error" ? (
              <p className="ws-project-create__error" role="alert" aria-live="assertive">
                {styleMessage.text}
              </p>
            ) : null}
          </section>

          <div className="ws-detail-list">
            <div>
              <span>标题</span>
              <strong>{project?.title || "未载入"}</strong>
            </div>
            <div>
              <span>作品来源</span>
              <strong>{source}</strong>
            </div>
            <div>
              <span>当前章节</span>
              <strong>第 {story?.current_chapter ?? 0} 章</strong>
            </div>
            <div>
              <span>状态</span>
              <strong>{statusLabel(project?.status)}</strong>
            </div>
            <div>
              <span>路径</span>
              <strong>{project?.source_path || "未设置"}</strong>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
