"use client";

import { useEffect, useState } from "react";

import {
  updateProject,
  type ImportedWorldBlueprint,
  type ProjectResponse,
} from "../../lib/api";

type Props = {
  projectId: string;
  worldSummary: string;
  blueprint: ImportedWorldBlueprint;
  onSaved?: () => void;
};

type SaveWorldBackgroundArgs = Props & {
  premise: string;
  updater?: typeof updateProject;
};

export const WORLD_BACKGROUND_FIELDS = [
  { field: "world_summary", label: "项目摘要" },
  { field: "premise", label: "世界前提" },
] as const;

export type WorldBackgroundField = (typeof WORLD_BACKGROUND_FIELDS)[number]["field"];

export type WorldBackgroundEditorState = {
  values: Record<WorldBackgroundField, string>;
  dirty: Record<WorldBackgroundField, boolean>;
  status: "idle" | "saving" | "success" | "error";
  error: string;
};

function backgroundValues(worldSummary: string, blueprint: ImportedWorldBlueprint) {
  return {
    world_summary: worldSummary,
    premise: blueprint.premise ?? "",
  };
}

export function createWorldBackgroundEditorState(
  worldSummary: string,
  blueprint: ImportedWorldBlueprint,
): WorldBackgroundEditorState {
  return {
    values: backgroundValues(worldSummary, blueprint),
    dirty: { world_summary: false, premise: false },
    status: "idle",
    error: "",
  };
}

export function mergeWorldBackgroundProps(
  state: WorldBackgroundEditorState,
  worldSummary: string,
  blueprint: ImportedWorldBlueprint,
): WorldBackgroundEditorState {
  const incoming = backgroundValues(worldSummary, blueprint);
  const values = { ...state.values };
  const dirty = { ...state.dirty };
  for (const { field } of WORLD_BACKGROUND_FIELDS) {
    if (!dirty[field]) {
      values[field] = incoming[field];
    } else if (incoming[field] === values[field]) {
      dirty[field] = false;
    }
  }
  return { ...state, values, dirty };
}

export function editWorldBackgroundField(
  state: WorldBackgroundEditorState,
  field: WorldBackgroundField,
  value: string,
): WorldBackgroundEditorState {
  return {
    ...state,
    values: { ...state.values, [field]: value },
    dirty: { ...state.dirty, [field]: true },
    status: "idle",
    error: "",
  };
}

export function markWorldBackgroundSaved(
  state: WorldBackgroundEditorState,
  submittedValues: Record<WorldBackgroundField, string>,
): WorldBackgroundEditorState {
  const unchangedSinceSubmit = WORLD_BACKGROUND_FIELDS.every(
    ({ field }) => state.values[field] === submittedValues[field],
  );
  return {
    ...state,
    status: unchangedSinceSubmit ? "success" : "idle",
    error: "",
  };
}

export async function saveWorldBackground({
  projectId,
  worldSummary,
  premise,
  blueprint,
  onSaved,
  updater = updateProject,
}: SaveWorldBackgroundArgs): Promise<ProjectResponse> {
  const updated = await updater(
    projectId,
    {
      world_summary: worldSummary,
      world_blueprint: {
        premise,
      },
    },
    { fallbackToMock: false },
  );
  onSaved?.();
  return updated;
}

export function WorldBackgroundEditor({ projectId, worldSummary, blueprint, onSaved }: Props) {
  const [editorState, setEditorState] = useState(() => createWorldBackgroundEditorState(worldSummary, blueprint));

  useEffect(() => {
    setEditorState((current) => mergeWorldBackgroundProps(current, worldSummary, blueprint));
  }, [worldSummary, blueprint]);

  const save = async () => {
    const submittedValues = { ...editorState.values };
    setEditorState((current) => ({ ...current, status: "saving", error: "" }));
    try {
      await saveWorldBackground({
        projectId,
        worldSummary: submittedValues.world_summary,
        premise: submittedValues.premise,
        blueprint,
        onSaved,
      });
      setEditorState((current) => markWorldBackgroundSaved(current, submittedValues));
    } catch (err) {
      setEditorState((current) => ({
        ...current,
        error: err instanceof Error ? err.message : String(err),
        status: "error",
      }));
    }
  };

  const edit = (field: WorldBackgroundField, value: string) => {
    setEditorState((current) => editWorldBackgroundField(current, field, value));
  };

  return (
    <section className="ws-card" aria-labelledby="world-background-title">
      <div className="ws-section-head">
        <div>
          <h2 className="ws-card__title" id="world-background-title">世界背景</h2>
          <p className="ws-card__hint">维护不会随章节变化的项目摘要与世界前提。</p>
        </div>
        <button type="button" className="ws-button ws-button--primary" disabled={editorState.status === "saving"} onClick={save}>
          {editorState.status === "saving" ? "保存中..." : "保存世界背景"}
        </button>
      </div>

      <div className="ws-form-grid">
        <label className="ws-search ws-form-grid__wide">
          <span>{WORLD_BACKGROUND_FIELDS[0].label}</span>
          <textarea className="ws-input" rows={4} value={editorState.values.world_summary} onChange={(event) => edit("world_summary", event.target.value)} />
        </label>
        <label className="ws-search ws-form-grid__wide">
          <span>{WORLD_BACKGROUND_FIELDS[1].label}</span>
          <textarea className="ws-input" rows={5} value={editorState.values.premise} onChange={(event) => edit("premise", event.target.value)} />
        </label>
      </div>

      {editorState.status === "saving" ? <p className="ws-inline-message" role="status" aria-live="polite" style={{ marginTop: 14 }}>保存中...</p> : null}
      {editorState.status === "success" ? <p className="ws-inline-message" role="status" aria-live="polite" style={{ color: "var(--ws-success)", marginTop: 14 }}>保存成功</p> : null}
      {editorState.status === "error" ? <p className="ws-error-text" role="alert" style={{ marginTop: 14 }}>保存失败：{editorState.error}</p> : null}
    </section>
  );
}
