"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import {
  fetchOpeningSetup,
  generateOpeningDirections,
  selectOpeningDirection,
  type OpeningSetup,
} from "../../../../lib/api";

type SetupPhase = "loading" | "no-candidates" | "candidates" | "error" | "selected";
type PendingRequest = "generate" | "select" | null;
type ErrorSource = "load" | "generate" | "select" | null;

const directionFields = [
  ["logline", "一句话简介"],
  ["protagonist_profile", "主角起点"],
  ["inciting_incident", "故事契机"],
  ["protagonist_goal", "主角目标"],
  ["failure_stakes", "失败后果"],
  ["main_conflict", "主线冲突"],
  ["growth_path", "成长方向"],
  ["excitement_point", "创作兴奋点"],
  ["target_audience", "目标读者"],
  ["reader_promise", "核心阅读期待"],
  ["ending_direction", "结局方向"],
] as const;

const openingCoreFields = [
  ["core_advantage", "核心优势"],
  ["central_mystery", "核心谜团"],
  ["initial_drive", "初始驱动力"],
] as const;

function coreSummary(value: Record<string, string | string[]>): string {
  return Object.values(value)
    .flatMap((item) => Array.isArray(item) ? item : [item])
    .map((item) => item.trim())
    .filter(Boolean)
    .join("；");
}

export default function OpeningSetupPage() {
  const router = useRouter();
  const { project, encodedProjectId, projectId } = useProjectWorkspace();
  const [phase, setPhase] = useState<SetupPhase>("loading");
  const [setup, setSetup] = useState<OpeningSetup | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [guidance, setGuidance] = useState("");
  const [pending, setPending] = useState<PendingRequest>(null);
  const [errorSource, setErrorSource] = useState<ErrorSource>(null);
  const mountedRef = useRef(false);
  const requestTokenRef = useRef(0);
  const currentProjectIdRef = useRef(projectId);
  currentProjectIdRef.current = projectId;

  const isCurrentRequest = useCallback((requestToken: number, requestProjectId: string) => {
    return (
      mountedRef.current &&
      requestTokenRef.current === requestToken &&
      currentProjectIdRef.current === requestProjectId
    );
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestTokenRef.current += 1;
    };
  }, []);

  useEffect(() => {
    const requestProjectId = projectId;
    const requestToken = ++requestTokenRef.current;
    setPhase("loading");
    setErrorSource(null);
    setGuidance("");

    fetchOpeningSetup(projectId)
      .then((response) => {
        if (!isCurrentRequest(requestToken, requestProjectId)) return;
        setSetup(response);
        if (response.selected_id) {
          setPhase("selected");
          router.replace(response.next_path);
          return;
        }
        setPhase(response.directions.length > 0 ? "candidates" : "no-candidates");
      })
      .catch(() => {
        if (!isCurrentRequest(requestToken, requestProjectId)) return;
        setErrorSource("load");
        setPhase("error");
      });

    return () => {
      if (requestTokenRef.current === requestToken) {
        requestTokenRef.current += 1;
      }
    };
  }, [isCurrentRequest, projectId, router]);

  async function generateDirections() {
    if (pending) return;
    const requestProjectId = projectId;
    const requestToken = ++requestTokenRef.current;
    setPending("generate");
    setErrorSource(null);
    try {
      const response = await generateOpeningDirections(projectId, guidance.trim());
      if (!isCurrentRequest(requestToken, requestProjectId)) return;
      setSetup(response);
      setSelectedId("");
      setGuidance("");
      setPhase(response.directions.length > 0 ? "candidates" : "no-candidates");
    } catch {
      if (!isCurrentRequest(requestToken, requestProjectId)) return;
      setErrorSource("generate");
      setPhase("error");
    } finally {
      if (isCurrentRequest(requestToken, requestProjectId)) {
        setPending(null);
      }
    }
  }

  async function adoptDirection() {
    if (pending || !selectedId) return;
    const requestProjectId = projectId;
    const requestToken = ++requestTokenRef.current;
    setPending("select");
    setErrorSource(null);
    try {
      const response = await selectOpeningDirection(projectId, selectedId);
      if (!isCurrentRequest(requestToken, requestProjectId)) return;
      setSetup(response);
      setPhase("selected");
      router.push(response.next_path);
    } catch {
      if (!isCurrentRequest(requestToken, requestProjectId)) return;
      setErrorSource("select");
      setPhase("error");
    } finally {
      if (isCurrentRequest(requestToken, requestProjectId)) {
        setPending(null);
      }
    }
  }

  const directions = setup?.directions ?? [];
  const requestPending = pending !== null;
  const manualOutlinePath = `/projects/${encodedProjectId}/outline`;

  return (
    <div className="ws-page ws-page--narrow">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="选择故事核心"
        subtitle="选定主角、冲突、失败后果和全书持续兑现的阅读体验。"
      />

      <div className="ws-opening-setup">
        {phase === "loading" ? (
          <p className="ws-card__hint" aria-live="polite">
            正在读取开篇信息...
          </p>
        ) : null}

        {setup ? (
          <section className="ws-opening-brief" aria-labelledby="opening-brief-title">
            <h2 id="opening-brief-title">原始灵感</h2>
            <p>{setup.brief.idea}</p>
          </section>
        ) : null}

        {errorSource ? (
          <p className="ws-opening-error" role="alert">
            {errorSource === "load"
              ? "暂时无法读取开篇信息，请刷新页面重试。"
              : errorSource === "generate"
                ? "故事方向暂时生成失败，请稍后重新试一次。"
                : "这个方向暂时无法采用，请重新选择后再试。"}
          </p>
        ) : null}

        {directions.length > 0 ? (
          <fieldset className="ws-opening-directions">
            <legend>故事核心候选</legend>
            {directions.map((direction, index) => (
              <section className="ws-opening-direction" key={direction.id}>
                <label className="ws-opening-direction__choice">
                  <input
                    type="radio"
                    name="opening-direction"
                    value={direction.id}
                    checked={selectedId === direction.id}
                    disabled={requestPending}
                    onChange={() => setSelectedId(direction.id)}
                  />
                  <span>
                    <small>方向 {index + 1}</small>
                    <strong>{direction.title}</strong>
                  </span>
                </label>
                <dl className="ws-opening-direction__fields">
                  {directionFields.map(([field, label]) => (
                    <div key={field}>
                      <dt>{label}</dt>
                      <dd>{direction[field]}</dd>
                    </div>
                  ))}
                  {openingCoreFields.map(([field, label]) => (
                    <div key={field}>
                      <dt>{label}</dt>
                      <dd>{coreSummary(direction[field]) || "尚未填写"}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            ))}
          </fieldset>
        ) : null}

        {phase !== "loading" && phase !== "selected" ? (
          <div className="ws-opening-actions">
            {directions.length > 0 || errorSource === "generate" ? (
              <label className="ws-opening-guidance">
                <span>本次补充要求</span>
                <textarea
                  className="ws-input ws-opening-guidance__input"
                  value={guidance}
                  maxLength={1000}
                  rows={3}
                  disabled={requestPending}
                  onChange={(event) => setGuidance(event.target.value)}
                  placeholder="例如：增强悬念，减少背景说明"
                />
              </label>
            ) : null}
            <button
              className="ws-btn"
              type="button"
              disabled={requestPending}
              onClick={() => void generateDirections()}
            >
              {pending === "generate"
                ? "生成中..."
                : errorSource === "generate" || directions.length > 0
                  ? "重新生成"
                  : "生成故事方向"}
            </button>
            {directions.length > 0 ? (
              <button
                className="ws-btn ws-btn--primary"
                type="button"
                disabled={requestPending || !selectedId}
                onClick={() => void adoptDirection()}
              >
                {pending === "select" ? "采用中..." : "采用这个方向"}
              </button>
            ) : null}
            {errorSource === "generate" ? (
              <Link className="ws-text-link" href={manualOutlinePath}>
                手动填写总纲
              </Link>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
