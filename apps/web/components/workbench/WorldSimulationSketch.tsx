"use client";

import type { ChapterBundle, ProjectResponse, StoryResponse } from "../../lib/api";

type SketchNode = {
  id: string;
  label: string;
  sublabel: string;
  x: number;
  y: number;
  tone: "core" | "actor" | "event" | "memory" | "next";
};

type SketchEdge = {
  from: string;
  to: string;
  tone: "solid" | "soft" | "warning";
};

type WorldSimulationSketchProps = {
  project: ProjectResponse | null;
  story: StoryResponse | null;
  bundle: ChapterBundle | null;
};

function trimLabel(value: string | undefined | null, fallback: string, maxLength = 18): string {
  const normalized = (value ?? "").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return fallback;
  }
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 1)}...` : normalized;
}

function actionForCharacter(bundle: ChapterBundle | null, name: string): string {
  const move = bundle?.character_moves?.find((item) => item.name === name);
  const planned = bundle?.event_plan?.ordered_actions?.find((item) => item.name === name);
  return trimLabel(move?.action ?? planned?.action ?? move?.goal ?? planned?.goal, "等待行动", 16);
}

function nodeClass(tone: SketchNode["tone"]): string {
  return `simulation-sketch__node simulation-sketch__node--${tone}`;
}

function edgeClass(tone: SketchEdge["tone"]): string {
  return `simulation-sketch__edge simulation-sketch__edge--${tone}`;
}

export function WorldSimulationSketch({ project, story, bundle }: WorldSimulationSketchProps) {
  const activeMoveNames = Array.from(
    new Set(
      (bundle?.character_moves ?? [])
        .map((move) => move.name)
        .filter((name): name is string => Boolean(name)),
    ),
  );
  const chapterCharacters = activeMoveNames.map((name) => {
    const storyCharacter = story?.characters?.find((character) => character.name === name);
    const projectProfile = project?.character_profiles?.find((profile) => profile.name === name);
    return storyCharacter ?? {
      name,
      goals: [projectProfile?.goals?.[0] ?? projectProfile?.motivation ?? projectProfile?.current_state ?? ""],
    };
  });
  const characters = chapterCharacters.length
    ? chapterCharacters
    : story?.characters?.length
      ? story.characters
      : (project?.character_profiles ?? []).map((profile) => ({
          name: profile.name,
          goals: [profile.goals?.[0] ?? profile.motivation ?? profile.current_state ?? ""],
        }));
  const visibleCharacters = characters.slice(0, 5);
  const conflict = trimLabel(
    bundle?.event_plan?.collision ??
      (bundle?.chapter_intent?.primary_conflict?.collision as string | undefined) ??
      bundle?.conflict_summary?.summary,
    "主冲突待生成",
    22,
  );
  const nextFocus = trimLabel(
    bundle?.event_plan?.next_focus ??
      bundle?.chapter_intent?.next_focus ??
      project?.current_focus,
    "下一步焦点待定",
    20,
  );
  const memory = trimLabel(
    bundle?.memory_constraints?.must_keep_facts?.[0] ??
      bundle?.memory_constraints?.unresolved_threads?.[0] ??
      project?.author_constraints?.[0],
    "记忆护栏待建立",
    20,
  );
  const worldLabel = trimLabel(project?.title, "小说项目", 14);

  const actorPositions = [
    { x: 130, y: 102 },
    { x: 118, y: 238 },
    { x: 270, y: 58 },
    { x: 306, y: 286 },
    { x: 430, y: 112 },
  ];
  const actorNodes: SketchNode[] = visibleCharacters.map((character, index) => ({
    id: `actor-${index}`,
    label: trimLabel(character.name, `角色 ${index + 1}`, 10),
    sublabel: actionForCharacter(bundle, character.name ?? `角色 ${index + 1}`),
    x: actorPositions[index]?.x ?? 150 + index * 70,
    y: actorPositions[index]?.y ?? 120 + index * 32,
    tone: "actor",
  }));

  const nodes: SketchNode[] = [
    {
      id: "world",
      label: worldLabel,
      sublabel: trimLabel(project?.world_summary ?? project?.seed_outline, "世界状态", 22),
      x: 300,
      y: 176,
      tone: "core",
    },
    {
      id: "conflict",
      label: "冲突",
      sublabel: conflict,
      x: 520,
      y: 176,
      tone: "event",
    },
    {
      id: "memory",
      label: "记忆",
      sublabel: memory,
      x: 300,
      y: 330,
      tone: "memory",
    },
    {
      id: "next",
      label: "下一步",
      sublabel: nextFocus,
      x: 520,
      y: 330,
      tone: "next",
    },
    ...actorNodes,
  ];

  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const edges: SketchEdge[] = [
    ...actorNodes.map((node) => ({ from: node.id, to: "world", tone: "soft" as const })),
    { from: "world", to: "conflict", tone: "solid" },
    { from: "conflict", to: "next", tone: "warning" },
    { from: "memory", to: "world", tone: "solid" },
    { from: "memory", to: "next", tone: "soft" },
  ];

  return (
    <section className="simulation-sketch" aria-label="世界推演图">
      <div className="simulation-sketch__head">
        <div>
          <p className="simulation-card__label">世界推演图</p>
          <h4>角色、冲突与记忆的当前连线</h4>
        </div>
        <div className="simulation-sketch__legend" aria-hidden="true">
          <span><i className="simulation-sketch__legend-dot simulation-sketch__legend-dot--actor" />角色</span>
          <span><i className="simulation-sketch__legend-dot simulation-sketch__legend-dot--event" />事件</span>
          <span><i className="simulation-sketch__legend-dot simulation-sketch__legend-dot--memory" />记忆</span>
        </div>
      </div>

      <svg className="simulation-sketch__canvas" viewBox="0 0 640 420" role="img">
        <title>世界推演关系图</title>
        <defs>
          <marker id="simulation-arrow" markerHeight="8" markerWidth="8" orient="auto" refX="7" refY="4">
            <path d="M0,0 L8,4 L0,8 Z" />
          </marker>
        </defs>
        <g className="simulation-sketch__grid-lines">
          <path d="M80 70 H570" />
          <path d="M80 176 H570" />
          <path d="M80 330 H570" />
          <path d="M300 42 V368" />
          <path d="M520 78 V360" />
        </g>
        {edges.map((edge, index) => {
          const from = nodeById.get(edge.from);
          const to = nodeById.get(edge.to);
          if (!from || !to) {
            return null;
          }
          const curve = edge.from.startsWith("actor") ? 26 : 0;
          const path = `M ${from.x} ${from.y} C ${(from.x + to.x) / 2} ${from.y - curve}, ${(from.x + to.x) / 2} ${to.y + curve}, ${to.x} ${to.y}`;
          return <path key={`${edge.from}-${edge.to}-${index}`} className={edgeClass(edge.tone)} d={path} />;
        })}
        {nodes.map((node) => (
          <g key={node.id} className={nodeClass(node.tone)} transform={`translate(${node.x} ${node.y})`}>
            <circle r={node.tone === "core" ? 54 : 44} />
            <text className="simulation-sketch__node-label" textAnchor="middle" y="-5">{node.label}</text>
            <text className="simulation-sketch__node-sub" textAnchor="middle" y="17">{node.sublabel}</text>
          </g>
        ))}
      </svg>
    </section>
  );
}
