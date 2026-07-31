"use client";

import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { fetchProjectOutline, updateProject, type ImportedRelationshipEdge, type ProjectOutline } from "../../../../lib/api";

type ViewMode = "protagonist" | "person" | "chapter" | "global";
type Position = { x: number; y: number };

function copyGraph(graph: ImportedRelationshipEdge[] | undefined): ImportedRelationshipEdge[] {
  return JSON.parse(JSON.stringify(graph ?? [])) as ImportedRelationshipEdge[];
}

function uniqueNames(values: Array<string | undefined>): string[] {
  return [...new Set(values.map((value) => String(value ?? "").trim()).filter(Boolean))];
}

function edgeLabel(edge: ImportedRelationshipEdge): string {
  return edge.relation_type || edge.bond || edge.current_state || "有关联";
}

function nodePositions(names: string[], centerName: string): Record<string, Position> {
  const positions: Record<string, Position> = {};
  if (names.length === 0) return positions;
  const center = names.includes(centerName) ? centerName : names[0];
  positions[center] = { x: 50, y: 50 };
  const others = names.filter((name) => name !== center);
  others.forEach((name, index) => {
    const angle = -Math.PI / 2 + (Math.PI * 2 * index) / Math.max(others.length, 1);
    positions[name] = { x: 50 + Math.cos(angle) * 36, y: 50 + Math.sin(angle) * 34 };
  });
  return positions;
}

export default function RelationshipsPage() {
  const { project, story, projectId, encodedProjectId, error, refresh } = useProjectWorkspace();
  const [draft, setDraft] = useState<ImportedRelationshipEdge[]>([]);
  const [outline, setOutline] = useState<ProjectOutline | null>(null);
  const [mode, setMode] = useState<ViewMode>("protagonist");
  const [selectedPerson, setSelectedPerson] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => setDraft(copyGraph(project?.relationship_graph)), [project?.relationship_graph]);
  useEffect(() => {
    let cancelled = false;
    fetchProjectOutline(projectId)
      .then((value) => { if (!cancelled) setOutline(value); })
      .catch(() => { if (!cancelled) setOutline(null); });
    return () => { cancelled = true; };
  }, [projectId]);

  const characters = useMemo(() => {
    const byName = new Map<string, { name: string; role?: string; character_tier?: string }>();
    [...(project?.character_profiles ?? []), ...(story?.characters ?? [])].forEach((character) => {
      const name = String(character.name ?? "").trim();
      if (name && !byName.has(name)) byName.set(name, character);
    });
    return [...byName.values()];
  }, [project?.character_profiles, story?.characters]);

  const protagonist = characters.find((character) =>
    character.character_tier === "protagonist" || ["protagonist", "主角"].includes(String(character.role ?? "").toLowerCase()),
  )?.name ?? characters[0]?.name ?? "";
  const activePerson = selectedPerson || protagonist;
  const targetChapter = Number(story?.current_chapter ?? 0) + 1;
  const chapterCast = outline?.chapters.find((chapter) => chapter.chapter_number === targetChapter)?.cast ?? [];

  const visibleEdges = useMemo(() => {
    if (mode === "global") return draft;
    if (mode === "chapter") {
      const cast = new Set(chapterCast);
      return draft.filter((edge) => cast.has(edge.source) && cast.has(edge.target));
    }
    const center = mode === "protagonist" ? protagonist : activePerson;
    return draft.filter((edge) => edge.source === center || edge.target === center);
  }, [activePerson, chapterCast, draft, mode, protagonist]);

  const visibleNames = useMemo(() => {
    const edgeNames = visibleEdges.flatMap((edge) => [edge.source, edge.target]);
    if (mode === "chapter") return uniqueNames([...chapterCast, ...edgeNames]);
    if (mode === "global") return uniqueNames(edgeNames);
    return uniqueNames([mode === "protagonist" ? protagonist : activePerson, ...edgeNames]);
  }, [activePerson, chapterCast, mode, protagonist, visibleEdges]);
  const layoutCenter = mode === "person" ? activePerson : protagonist;
  const positions = nodePositions(visibleNames, layoutCenter);

  const patchEdge = (index: number, patch: Partial<ImportedRelationshipEdge>) => {
    setDraft((current) => current.map((edge, edgeIndex) => edgeIndex === index ? { ...edge, ...patch } : edge));
  };

  const addEdge = () => {
    const source = protagonist || characters[0]?.name || "";
    const target = characters.find((character) => character.name !== source)?.name || "";
    if (!source || !target) {
      setMessage("至少需要两张角色卡才能新增关系。");
      return;
    }
    setDraft((current) => [...current, { source, target, relation_type: "", current_state: "", trust: 50, tension: 0 }]);
    setMode("global");
  };

  const save = async () => {
    setBusy(true);
    setMessage("");
    try {
      await updateProject(projectId, { relationship_graph: draft });
      setMessage("关系图已保存。");
      void refresh().catch(() => undefined);
    } catch (saveError) {
      setMessage(`保存失败：${saveError instanceof Error ? saveError.message : String(saveError)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[{ label: "我的作品", href: "/projects" }, { label: project?.title || "作品", href: `/projects/${encodedProjectId}` }]}
        title="人物关系"
        subtitle="关系图是人物关系的唯一记录。页面默认围绕主角查看，写作时只提取本章出场人物之间的关系。"
      />
      {error ? <p className="ws-error-text">加载失败：{error}</p> : null}
      {message ? <p className="ws-inline-message">{message}</p> : null}

      <section className="ws-relationship-toolbar" aria-label="关系图查看范围">
        <div className="ws-segmented-control">
          {([[
            "protagonist", "主角视角",
          ], ["person", "指定人物"], ["chapter", `第${targetChapter}章人物`], ["global", "全局"]] as Array<[ViewMode, string]>).map(([value, label]) => (
            <button key={value} type="button" aria-pressed={mode === value} onClick={() => setMode(value)}>{label}</button>
          ))}
        </div>
        {mode === "person" ? <label className="ws-relationship-person-select"><span>中心人物</span><select value={activePerson} onChange={(event) => setSelectedPerson(event.target.value)}>{characters.map((character) => <option key={character.name}>{character.name}</option>)}</select></label> : null}
        <div className="ws-relationship-actions">
          <button type="button" className="ws-btn" onClick={addEdge}>新增关系</button>
          <button type="button" className="ws-btn ws-btn--primary" disabled={busy} onClick={save}>保存关系图</button>
        </div>
      </section>

      <section className="ws-relationship-canvas" aria-label="人物关系图">
        {visibleEdges.length > 0 ? <svg className="ws-relationship-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">{visibleEdges.map((edge, index) => { const source = positions[edge.source]; const target = positions[edge.target]; return source && target ? <line key={`${edge.id ?? `${edge.source}-${edge.target}`}-${index}`} x1={source.x} y1={source.y} x2={target.x} y2={target.y} /> : null; })}</svg> : null}
        {visibleEdges.map((edge, index) => { const source = positions[edge.source]; const target = positions[edge.target]; if (!source || !target) return null; return <span className="ws-relationship-edge-label" key={`label-${edge.id ?? index}`} style={{ left: `${(source.x + target.x) / 2}%`, top: `${(source.y + target.y) / 2}%` }}>{edgeLabel(edge)}</span>; })}
        {visibleNames.map((name) => { const position = positions[name]; const isCenter = name === layoutCenter; return <button key={name} type="button" className={`ws-relationship-node${isCenter ? " is-center" : ""}`} style={{ left: `${position.x}%`, top: `${position.y}%` }} onClick={() => { setSelectedPerson(name); setMode("person"); }}>{name}</button>; })}
        {visibleNames.length === 0 ? <p className="ws-relationship-empty">当前范围还没有人物关系。</p> : null}
      </section>

      <section className="ws-relationship-editor">
        <div className="ws-section-heading"><div><h2>关系记录</h2><p>静态来历与当前状态分开记录，章节更新只改变当前状态。</p></div><span>{draft.length} 条</span></div>
        <div className="ws-relationship-list">
          {draft.map((edge, index) => (
            <article className="ws-relationship-row" key={edge.id ?? `${edge.source}-${edge.target}-${index}`}>
              <div className="ws-relationship-pair">
                <label><span>人物一</span><select value={edge.source} onChange={(event) => patchEdge(index, { source: event.target.value })}>{characters.map((character) => <option key={character.name}>{character.name}</option>)}</select></label>
                <span>与</span>
                <label><span>人物二</span><select value={edge.target} onChange={(event) => patchEdge(index, { target: event.target.value })}>{characters.map((character) => <option key={character.name}>{character.name}</option>)}</select></label>
              </div>
              <div className="ws-relationship-fields">
                <label><span>关系类型</span><input value={edge.relation_type ?? edge.bond ?? ""} onChange={(event) => patchEdge(index, { relation_type: event.target.value, bond: event.target.value })} /></label>
                <label><span>当前状态</span><input aria-label={`${edge.source}与${edge.target}的当前状态`} value={edge.current_state ?? ""} onChange={(event) => patchEdge(index, { current_state: event.target.value })} /></label>
                <label><span>信任</span><input type="number" min={0} max={100} value={edge.trust ?? 0} onChange={(event) => patchEdge(index, { trust: Number(event.target.value) })} /></label>
                <label><span>紧张</span><input type="number" min={0} max={100} value={edge.tension ?? 0} onChange={(event) => patchEdge(index, { tension: Number(event.target.value) })} /></label>
                <label className="is-wide"><span>共同利益或冲突</span><input value={edge.shared_interest_or_conflict ?? ""} onChange={(event) => patchEdge(index, { shared_interest_or_conflict: event.target.value })} /></label>
              </div>
              <button type="button" className="ws-link-button is-danger" onClick={() => setDraft((current) => current.filter((_, edgeIndex) => edgeIndex !== index))}>删除</button>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
