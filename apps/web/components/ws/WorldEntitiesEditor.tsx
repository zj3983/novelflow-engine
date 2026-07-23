"use client";

import { useEffect, useRef, useState } from "react";

import {
  updateProject,
  type ImportedWorldBlueprint,
  type ImportedWorldEntry,
  type ProjectResponse,
} from "../../lib/api";

export type WorldEntityField = "locations" | "factions";
export type WorldEntityTextField = "name" | "description";
type SaveStatus = "idle" | "saving" | "success" | "error";

type Props = {
  projectId: string;
  blueprint: ImportedWorldBlueprint;
  onSaved?: () => void;
};

export type WorldEntitiesEditorState = {
  drafts: Record<WorldEntityField, ImportedWorldEntry[]>;
  dirty: Record<WorldEntityField, boolean>;
  statuses: Record<WorldEntityField, SaveStatus>;
  errors: Partial<Record<WorldEntityField, string>>;
};

export type WorldEntitiesBlueprintStore = {
  current: ImportedWorldBlueprint;
  pending?: Partial<Record<WorldEntityField, ImportedWorldEntry[]>>;
};

type SaveWorldEntitiesArgs = Omit<Props, "blueprint"> & {
  field: WorldEntityField;
  entities: ImportedWorldEntry[];
  blueprintStore: WorldEntitiesBlueprintStore;
  updater?: typeof updateProject;
};

export function WorldEntitySaveStatus({ status, error }: { status: SaveStatus; error?: string }) {
  if (status === "saving" || status === "success") {
    return (
      <span role="status" aria-live="polite" style={{ color: status === "success" ? "var(--ws-success)" : undefined }}>
        {status === "saving" ? "保存中..." : "保存成功"}
      </span>
    );
  }
  if (status === "error") {
    return <span className="ws-error-text" role="alert">{`保存失败：${error ?? ""}`}</span>;
  }
  return null;
}

const ENTITY_SECTIONS: Array<{
  field: WorldEntityField;
  title: string;
  addLabel: string;
  saveLabel: string;
}> = [
  { field: "locations", title: "地点", addLabel: "新增地点", saveLabel: "保存地点" },
  { field: "factions", title: "阵营", addLabel: "新增阵营", saveLabel: "保存阵营" },
];

function cloneEntries(entries: ImportedWorldEntry[] | undefined): ImportedWorldEntry[] {
  return (entries ?? []).map((entry) => ({ ...entry }));
}

function sameEntries(left: ImportedWorldEntry[] | undefined, right: ImportedWorldEntry[] | undefined) {
  return JSON.stringify(left ?? []) === JSON.stringify(right ?? []);
}

export function createWorldEntitiesEditorState(blueprint: ImportedWorldBlueprint): WorldEntitiesEditorState {
  return {
    drafts: {
      locations: cloneEntries(blueprint.locations),
      factions: cloneEntries(blueprint.factions),
    },
    dirty: { locations: false, factions: false },
    statuses: { locations: "idle", factions: "idle" },
    errors: {},
  };
}

export function mergeWorldEntitiesProps(
  state: WorldEntitiesEditorState,
  blueprint: ImportedWorldBlueprint,
): WorldEntitiesEditorState {
  const drafts = { ...state.drafts };
  const dirty = { ...state.dirty };
  for (const { field } of ENTITY_SECTIONS) {
    if (!dirty[field] || sameEntries(drafts[field], blueprint[field])) {
      drafts[field] = cloneEntries(blueprint[field]);
      dirty[field] = false;
    }
  }
  return { ...state, drafts, dirty };
}

export function editWorldEntity(
  state: WorldEntitiesEditorState,
  field: WorldEntityField,
  index: number,
  key: WorldEntityTextField,
  value: string,
): WorldEntitiesEditorState {
  return {
    ...state,
    drafts: {
      ...state.drafts,
      [field]: state.drafts[field].map((entry, entryIndex) => (
        entryIndex === index ? { ...entry, [key]: value } : entry
      )),
    },
    dirty: { ...state.dirty, [field]: true },
    statuses: { ...state.statuses, [field]: "idle" },
    errors: { ...state.errors, [field]: undefined },
  };
}

export function addWorldEntity(
  state: WorldEntitiesEditorState,
  field: WorldEntityField,
): WorldEntitiesEditorState {
  return {
    ...state,
    drafts: {
      ...state.drafts,
      [field]: [...state.drafts[field], { name: "", description: "" }],
    },
    dirty: { ...state.dirty, [field]: true },
    statuses: { ...state.statuses, [field]: "idle" },
    errors: { ...state.errors, [field]: undefined },
  };
}

export function removeWorldEntity(
  state: WorldEntitiesEditorState,
  field: WorldEntityField,
  index: number,
): WorldEntitiesEditorState {
  return {
    ...state,
    drafts: {
      ...state.drafts,
      [field]: state.drafts[field].filter((_, entryIndex) => entryIndex !== index),
    },
    dirty: { ...state.dirty, [field]: true },
    statuses: { ...state.statuses, [field]: "idle" },
    errors: { ...state.errors, [field]: undefined },
  };
}

export function markWorldEntitiesSaved(
  state: WorldEntitiesEditorState,
  field: WorldEntityField,
  submitted: ImportedWorldEntry[],
): WorldEntitiesEditorState {
  const unchangedSinceSubmit = sameEntries(state.drafts[field], submitted);
  return {
    ...state,
    dirty: { ...state.dirty, [field]: unchangedSinceSubmit ? false : state.dirty[field] },
    statuses: { ...state.statuses, [field]: unchangedSinceSubmit ? "success" : "idle" },
    errors: { ...state.errors, [field]: undefined },
  };
}

export function syncWorldEntitiesBlueprintStore(
  store: WorldEntitiesBlueprintStore,
  incoming: ImportedWorldBlueprint,
): void {
  const pending = { ...(store.pending ?? {}) };
  const next: ImportedWorldBlueprint = { ...store.current, ...incoming };
  for (const { field } of ENTITY_SECTIONS) {
    const savedEntries = pending[field];
    if (!savedEntries) continue;
    if (sameEntries(incoming[field], savedEntries)) {
      delete pending[field];
    } else {
      next[field] = savedEntries;
    }
  }
  store.current = next;
  store.pending = pending;
}

export async function saveWorldEntities({
  projectId,
  field,
  entities,
  blueprintStore,
  onSaved,
  updater = updateProject,
}: SaveWorldEntitiesArgs): Promise<ProjectResponse> {
  const submitted = cloneEntries(entities);
  const nextBlueprint = { ...blueprintStore.current, [field]: submitted };
  const updated = await updater(
    projectId,
    { world_blueprint: { [field]: submitted } },
    { fallbackToMock: false },
  );
  blueprintStore.current = {
    ...nextBlueprint,
    ...(updated.world_blueprint ?? {}),
    [field]: submitted,
  };
  blueprintStore.pending = { ...(blueprintStore.pending ?? {}), [field]: submitted };
  onSaved?.();
  return updated;
}

export function WorldEntitiesEditor({ projectId, blueprint, onSaved }: Props) {
  const [state, setState] = useState(() => createWorldEntitiesEditorState(blueprint));
  const blueprintStore = useRef<WorldEntitiesBlueprintStore>({ current: blueprint });

  useEffect(() => {
    syncWorldEntitiesBlueprintStore(blueprintStore.current, blueprint);
    setState((current) => mergeWorldEntitiesProps(current, blueprintStore.current.current));
  }, [blueprint]);

  const save = async (field: WorldEntityField) => {
    const submitted = cloneEntries(state.drafts[field]);
    setState((current) => ({
      ...current,
      statuses: { ...current.statuses, [field]: "saving" },
      errors: { ...current.errors, [field]: undefined },
    }));
    try {
      await saveWorldEntities({ projectId, field, entities: submitted, blueprintStore: blueprintStore.current, onSaved });
      setState((current) => markWorldEntitiesSaved(current, field, submitted));
    } catch (error) {
      setState((current) => ({
        ...current,
        statuses: { ...current.statuses, [field]: "error" },
        errors: { ...current.errors, [field]: error instanceof Error ? error.message : String(error) },
      }));
    }
  };

  const anySaving = Object.values(state.statuses).includes("saving");

  return (
    <section className="ws-card" aria-labelledby="world-entities-title">
      <div className="ws-section-head">
        <div>
          <h2 className="ws-card__title" id="world-entities-title">地点与阵营</h2>
        </div>
      </div>

      <div className="ws-form-grid">
        {ENTITY_SECTIONS.map(({ field, title, addLabel, saveLabel }) => (
          <section key={field} aria-labelledby={`world-${field}-title`}>
            <div className="ws-section-head">
              <h3 id={`world-${field}-title`}>{title}</h3>
              <button type="button" className="ws-button" disabled={anySaving} onClick={() => setState((current) => addWorldEntity(current, field))}>
                {addLabel}
              </button>
            </div>

            <div className="ws-rule-list">
              {state.drafts[field].map((entry, index) => (
                <article className="ws-rule-item" key={`${field}-${index}`}>
                  <label className="ws-search">
                    <span>名称</span>
                    <input
                      className="ws-input"
                      value={entry.name}
                      onChange={(event) => setState((current) => editWorldEntity(current, field, index, "name", event.target.value))}
                    />
                  </label>
                  <label className="ws-search">
                    <span>描述</span>
                    <textarea
                      className="ws-input"
                      rows={3}
                      value={entry.description ?? ""}
                      onChange={(event) => setState((current) => editWorldEntity(current, field, index, "description", event.target.value))}
                    />
                  </label>
                  <button
                    type="button"
                    className="ws-button"
                    aria-label={`删除${entry.name || title}`}
                    disabled={anySaving}
                    onClick={() => setState((current) => removeWorldEntity(current, field, index))}
                  >
                    删除
                  </button>
                </article>
              ))}
              {state.drafts[field].length === 0 ? <p className="ws-card__hint">暂无{title}</p> : null}
            </div>

            <div className="ws-toolbar">
              <button type="button" className="ws-button ws-button--primary" disabled={anySaving} onClick={() => save(field)}>
                {saveLabel}
              </button>
              <WorldEntitySaveStatus status={state.statuses[field]} error={state.errors[field]} />
            </div>
          </section>
        ))}
      </div>
    </section>
  );
}
