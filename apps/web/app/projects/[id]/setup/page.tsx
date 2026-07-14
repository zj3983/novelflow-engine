"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

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
  ["hook", "开篇钩子"],
  ["protagonist_goal", "主角目标"],
  ["main_conflict", "主线冲突"],
  ["growth_path", "成长路径"],
  ["opening_promise", "开篇承诺"],
] as const;

export default function OpeningSetupPage() {
  const router = useRouter();
  const { project, encodedProjectId, projectId } = useProjectWorkspace();
  const [phase, setPhase] = useState<SetupPhase>("loading");
  const [setup, setSetup] = useState<OpeningSetup | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [pending, setPending] = useState<PendingRequest>(null);
  const [errorSource, setErrorSource] = useState<ErrorSource>(null);

  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    setErrorSource(null);

    fetchOpeningSetup(projectId)
      .then((response) => {
        if (cancelled) return;
        setSetup(response);
        if (response.selected_id) {
          setPhase("selected");
          router.replace(response.next_path);
          return;
        }
        setPhase(response.directions.length > 0 ? "candidates" : "no-candidates");
      })
      .catch(() => {
        if (!cancelled) {
          setErrorSource("load");
          setPhase("error");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, router]);

  async function generateDirections() {
    if (pending) return;
    setPending("generate");
    setErrorSource(null);
    try {
      const response = await generateOpeningDirections(projectId);
      setSetup(response);
      setSelectedId("");
      setPhase(response.directions.length > 0 ? "candidates" : "no-candidates");
    } catch {
      setErrorSource("generate");
      setPhase("error");
    } finally {
      setPending(null);
    }
  }

  async function adoptDirection() {
    if (pending || !selectedId) return;
    setPending("select");
    setErrorSource(null);
    try {
      const response = await selectOpeningDirection(projectId, selectedId);
      setSetup(response);
      setPhase("selected");
      router.push(response.next_path);
    } catch {
      setErrorSource("select");
      setPhase("error");
    } finally {
      setPending(null);
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
        title="选择开篇方向"
        subtitle="从原始灵感中选定故事的开篇承诺。"
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
            <legend>故事方向</legend>
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
                </dl>
              </section>
            ))}
          </fieldset>
        ) : null}

        {phase !== "loading" && phase !== "selected" ? (
          <div className="ws-opening-actions">
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
