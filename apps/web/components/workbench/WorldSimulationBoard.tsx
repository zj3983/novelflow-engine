"use client";

import type { ReactNode } from "react";
import type {
  ChapterBundle,
  ImportedCharacterProfile,
  ImportedRelationshipEdge,
  ImportedWorldBlueprint,
  ProjectResponse,
  StoryResponse,
} from "../../lib/api";
import { WorldSimulationSketch } from "./WorldSimulationSketch";

type WorldSimulationBoardProps = {
  project: ProjectResponse | null;
  story: StoryResponse | null;
  bundle: ChapterBundle | null;
};

function compactLines(text: string | undefined, limit: number): string[] {
  return (text ?? "")
    .split(/\r?\n/)
    .map((line) => line.trim().replace(/^[-*#\d.\s、]+/, "").replace(/\*\*/g, ""))
    .filter(Boolean)
    .slice(0, limit);
}

function firstNonEmpty(...values: Array<string | undefined | null>): string {
  return values.find((value) => value?.trim())?.trim() ?? "";
}

function importedWorld(project: ProjectResponse | null): ImportedWorldBlueprint {
  return project?.world_blueprint ?? {};
}

function importedProfiles(project: ProjectResponse | null): ImportedCharacterProfile[] {
  return project?.character_profiles ?? [];
}

function importedRelationships(project: ProjectResponse | null): ImportedRelationshipEdge[] {
  return project?.relationship_graph ?? project?.world_blueprint?.relationship_graph ?? [];
}

function relationSnapshot(story: StoryResponse | null): Array<{ name: string; text: string }> {
  if (!story?.characters.length) {
    return [];
  }

  const snapshots: Array<{ name: string; text: string }> = [];
  for (const character of story.characters) {
    const firstRelation = character.relationships ? Object.values(character.relationships)[0] : undefined;
    if (!firstRelation) {
      continue;
    }
    snapshots.push({
      name: character.name,
      text: `对 ${firstRelation.target} 的信任 ${firstRelation.trust.toFixed(2)}，紧张 ${firstRelation.tension.toFixed(2)}。`,
    });
    if (snapshots.length >= 3) {
      break;
    }
  }
  return snapshots;
}

function fallbackSummary(bundle: ChapterBundle | null): string {
  if (!bundle?.simulation_status) {
    return "当前还没有章节推演记录。";
  }
  if (bundle.simulation_status.ok) {
    return "本轮为完整推演，各代理都按正常链路参与了生成。";
  }
  const agents = (bundle.simulation_status.fallback_agents ?? []).join("、") || "未知代理";
  return `本轮触发降级推演：${agents} 使用了回退策略。`;
}

function CardList({
  empty,
  items,
  render,
}: {
  empty: string;
  items: unknown[];
  render: (item: any, index: number) => ReactNode;
}) {
  if (!items.length) {
    return <p className="simulation-card__detail">{empty}</p>;
  }
  return <div className="simulation-list">{items.map(render)}</div>;
}

export function WorldSimulationBoard({ project, story, bundle }: WorldSimulationBoardProps) {
  const hasGeneratedChapter = Boolean(story?.history.length || bundle);
  const world = importedWorld(project);
  const worldSystems = world.world_systems ?? {};
  const livingWorld = world.living_world ?? {};
  const npcSystem = world.npc_system ?? {};
  const questNetwork = world.quest_network ?? {};
  const serverRuntime = world.server_runtime ?? {};
  const mapEcology = world.map_ecology ?? {};
  const profiles = importedProfiles(project);
  const relationships = importedRelationships(project);
  const relationCards = relationSnapshot(story);
  const importedFocusLines = compactLines(project?.current_focus, 4);
  const importedOutlineLines = compactLines(project?.seed_outline, 4);
  const memoryFacts = bundle?.memory_constraints?.must_keep_facts ?? [];
  const unresolvedThreads = bundle?.memory_constraints?.unresolved_threads ?? [];
  const authorConstraints =
    bundle?.memory_constraints?.author_constraints ??
    world.constraints ??
    project?.author_constraints ??
    story?.author_constraints ??
    [];
  const worldRuleItems = [
    ...(world.world_rules ?? []),
    ...(world.progression_rules ?? []),
    ...(world.economy_rules ?? []),
    ...(world.quest_rules ?? []),
    ...(world.faction_rules ?? []),
    ...(world.panel_rules ?? []),
    ...(world.chapter_formula ?? []),
  ];
  const openingArc = world.opening_arc?.golden_three_chapters ?? {};
  const openingArcItems = [
    ...(openingArc.chapter_1?.purpose ? [{ title: "黄金三章第1章", text: openingArc.chapter_1.purpose }] : []),
    ...(openingArc.chapter_1?.exposition_beats ?? []).map((text) => ({ title: "第1章背景节拍", text })),
    ...(openingArc.chapter_2?.purpose ? [{ title: "黄金三章第2章", text: openingArc.chapter_2.purpose }] : []),
    ...(openingArc.chapter_3?.purpose ? [{ title: "黄金三章第3章", text: openingArc.chapter_3.purpose }] : []),
  ];
  const expositionItems = [
    ...(bundle?.event_plan?.exposition_beats ?? []).map((text) => ({ title: "本章背景节拍", text })),
    ...openingArcItems,
  ];
  const dailyWorldItems = [
    ...(livingWorld.daily_routines ?? []).map((text) => ({ title: "日常运转", text })),
    ...(livingWorld.economy?.resource_flow ?? []).map((text) => ({ title: "资源流动", text })),
    ...(livingWorld.economy?.pressure_points ?? []).map((text) => ({ title: "经济压力", text })),
  ];
  const worldSystemItems = [
    ...(worldSystems.material_base ?? []).map((text) => ({ title: "资源基础", text })),
    ...(worldSystems.institutions ?? []).map((entry) => ({ title: `制度机构：${entry.name}`, text: entry.description || entry.name })),
    ...(worldSystems.social_order ?? []).map((text) => ({ title: "社会秩序", text })),
    ...(worldSystems.conflict_engines ?? []).map((text) => ({ title: "冲突引擎", text })),
  ];
  const socialSystemItems = [
    ...(livingWorld.power_structure?.dominant_groups ?? []).map((text) => ({ title: "支配群体", text })),
    ...(livingWorld.power_structure?.control_methods ?? []).map((text) => ({ title: "控制方式", text })),
    ...(livingWorld.information_network?.channels ?? []).map((text) => ({ title: "消息渠道", text })),
    ...(livingWorld.information_network?.rumors ?? []).map((text) => ({ title: "正在流动的传闻", text })),
  ];
  const npcItems = [
    ...(npcSystem.npcs ?? []).map((npc) => ({
      title: `NPC：${npc.name}`,
      text: [
        npc.role,
        npc.location ? `位置：${npc.location}` : "",
        npc.services?.length ? `服务：${npc.services.slice(0, 3).join("、")}` : "",
        npc.knowledge_limit ? `边界：${npc.knowledge_limit}` : "",
      ]
        .filter(Boolean)
        .join("；"),
    })),
    ...(npcSystem.rules ?? []).map((text) => ({ title: "NPC规则", text })),
  ];
  const questItems = [
    ...(questNetwork.active_chains ?? []).map((chain) => ({
      title: `任务链：${chain.name}`,
      text: [
        chain.description,
        chain.stages?.length ? `阶段：${chain.stages.slice(0, 4).join(" -> ")}` : "",
        chain.npc_links?.length ? `关联NPC：${chain.npc_links.slice(0, 4).join("、")}` : "",
      ]
        .filter(Boolean)
        .join("；"),
    })),
    ...(questNetwork.quest_types ?? []).slice(0, 4).map((text) => ({ title: "任务类型", text })),
    ...(questNetwork.reward_rules ?? []).map((text) => ({ title: "奖励规则", text })),
  ];
  const runtimeItems = [
    ...(serverRuntime.phase ? [{ title: "服务器阶段", text: serverRuntime.phase }] : []),
    ...(serverRuntime.channels?.length ? [{ title: "信息频道", text: serverRuntime.channels.slice(0, 6).join("、") }] : []),
    ...(serverRuntime.announcement_rules ?? []).map((text) => ({ title: "公告规则", text })),
    ...(serverRuntime.anti_cheat_rules ?? []).map((text) => ({ title: "风控规则", text })),
    ...(serverRuntime.instance_rules ?? []).map((text) => ({ title: "副本门槛", text })),
  ];
  const mapItems = [
    ...(mapEcology.zones ?? []).map((zone) => ({
      title: `地图：${zone.name}`,
      text: [
        zone.description,
        zone.resources?.length ? `资源：${zone.resources.slice(0, 4).join("、")}` : "",
        zone.npcs?.length ? `NPC：${zone.npcs.slice(0, 4).join("、")}` : "",
        zone.risk ? `风险：${zone.risk}` : "",
      ]
        .filter(Boolean)
        .join("；"),
    })),
    ...(mapEcology.rules ?? []).map((text) => ({ title: "地图规则", text })),
  ];
  const reactionItems = [
    ...(bundle?.event_plan?.world_reactions ?? []).map((text) => ({ title: "本章世界反应", text })),
    ...(worldSystems.causal_loops ?? []).map((entry) => ({ title: `因果链：${entry.name}`, text: entry.description || entry.name })),
    ...(livingWorld.timeline ?? []).map((text) => ({ title: "时间推进", text })),
    ...(livingWorld.reaction_rules ?? []).map((text) => ({ title: "世界反应", text })),
    ...(livingWorld.location_functions ?? []).map((entry) => ({ title: `地点功能：${entry.name}`, text: entry.description || entry.name })),
  ];

  const worldSituation = firstNonEmpty(
    bundle?.event_plan?.pivot,
    bundle?.chapter_summary?.summary,
    world.current_arc,
    project?.world_summary,
    world.premise,
  ) || "导入材料已载入，等待确认世界档案后再开始第一章。";

  const chapterIntent = hasGeneratedChapter
    ? firstNonEmpty(
        bundle?.chapter_intent?.primary_conflict?.collision as string | undefined,
        bundle?.conflict_summary?.summary,
      ) || "当前章节还没有形成明确主冲突。"
    : "导入后先生成世界档案和角色档案，确认设定后再开始第一章。";

  const nextFocus = firstNonEmpty(
    bundle?.chapter_intent?.next_focus,
    bundle?.event_plan?.next_focus,
    project?.current_focus,
    bundle?.next_outline,
  ) || "等待下一轮推演种子。";

  const eventActions = bundle?.event_plan?.ordered_actions ?? [];

  return (
    <div className="panel simulation-board">
      <header className="panel__header">世界演化台</header>
      <div className="panel__body simulation-board__body">
        <section className="simulation-hero">
          <div className="simulation-hero__main">
            <p className="simulation-hero__eyebrow">{hasGeneratedChapter ? "当前世界局势" : "导入世界档案"}</p>
            <h3 className="simulation-hero__title">{project?.title ?? "未命名小说项目"}</h3>
            <p className="simulation-hero__summary">{worldSituation}</p>
          </div>
          <div className="simulation-hero__meta">
            <span className="simulation-pill">主线：{project?.active_story_id || story?.story_id || "尚未创建"}</span>
            <span className="simulation-pill">推进到：第 {story?.current_chapter ?? 0} 章</span>
            <span className="simulation-pill">
              推演模式：{hasGeneratedChapter ? (bundle?.simulation_status?.mode === "degraded" ? "降级推演" : "完整推演") : "世界观准备"}
            </span>
          </div>
        </section>

        <WorldSimulationSketch project={project} story={story} bundle={bundle} />

        <div className="simulation-grid">
          <article className="simulation-card simulation-card--focus">
            <p className="simulation-card__label">{hasGeneratedChapter ? "本章意图" : "导入意图"}</p>
            <h4 className="simulation-card__title">{chapterIntent}</h4>
            <p className="simulation-card__detail">下一焦点：{nextFocus}</p>
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">{hasGeneratedChapter ? "事件链" : "世界规则"}</p>
            {hasGeneratedChapter && eventActions.length ? (
              <CardList
                empty="还没有整理出明确的事件链。"
                items={eventActions.slice(0, 3)}
                render={(action, index) => (
                  <div key={`${action.name}-${index}`} className="simulation-list__item">
                    <span className="simulation-list__index">0{index + 1}</span>
                    <div>
                      <strong>{action.name || "未知角色"}</strong>
                      <p>{action.action || action.goal || "暂时没有动作说明"}</p>
                    </div>
                  </div>
                )}
              />
            ) : (
              <CardList
                empty="导入材料里还没有可识别的世界规则。"
                items={worldRuleItems.length ? worldRuleItems.slice(0, 4) : importedFocusLines}
                render={(item, index) => (
                  <div key={`${item}-${index}`} className="simulation-list__item">
                    <span className="simulation-list__index">0{index + 1}</span>
                    <div>
                      <strong>规则 {index + 1}</strong>
                      <p>{String(item)}</p>
                    </div>
                  </div>
                )}
              />
            )}
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">活世界日常</p>
            <CardList
              empty="还没有日常运转、资源流动或经济压力。"
              items={dailyWorldItems.slice(0, 4)}
              render={(item, index) => (
                <div key={`${item.title}-${index}`} className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.text}</p>
                  </div>
                </div>
              )}
            />
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">黄金三章</p>
            <CardList
              empty="还没有黄金三章职责或背景节拍。"
              items={expositionItems.slice(0, 5)}
              render={(item, index) => (
                <div key={`${item.title}-${index}`} className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.text}</p>
                  </div>
                </div>
              )}
            />
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">世界制度</p>
            <CardList
              empty="还没有资源基础、制度机构或冲突引擎。"
              items={worldSystemItems.slice(0, 4)}
              render={(item, index) => (
                <div key={`${item.title}-${index}`} className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.text}</p>
                  </div>
                </div>
              )}
            />
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">社会系统</p>
            <CardList
              empty="还没有权力结构或信息传播网络。"
              items={socialSystemItems.slice(0, 4)}
              render={(item, index) => (
                <div key={`${item.title}-${index}`} className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.text}</p>
                  </div>
                </div>
              )}
            />
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">NPC生态</p>
            <CardList
              empty="还没有 NPC 服务、信息边界或任务钩子。"
              items={npcItems.slice(0, 5)}
              render={(item, index) => (
                <div key={`${item.title}-${index}`} className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.text}</p>
                  </div>
                </div>
              )}
            />
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">任务网络</p>
            <CardList
              empty="还没有任务类型、任务链或奖励/失败规则。"
              items={questItems.slice(0, 5)}
              render={(item, index) => (
                <div key={`${item.title}-${index}`} className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.text}</p>
                  </div>
                </div>
              )}
            />
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">服务器规则</p>
            <CardList
              empty="还没有服务器阶段、公告频道或风控规则。"
              items={runtimeItems.slice(0, 5)}
              render={(item, index) => (
                <div key={`${item.title}-${index}`} className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.text}</p>
                  </div>
                </div>
              )}
            />
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">地图生态</p>
            <CardList
              empty="还没有地图资源、风险、玩家密度或地点产出。"
              items={mapItems.slice(0, 5)}
              render={(item, index) => (
                <div key={`${item.title}-${index}`} className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.text}</p>
                  </div>
                </div>
              )}
            />
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">连锁反应</p>
            <CardList
              empty="还没有时间推进或世界反应规则。"
              items={reactionItems.slice(0, 4)}
              render={(item, index) => (
                <div key={`${item.title}-${index}`} className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.text}</p>
                  </div>
                </div>
              )}
            />
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">{hasGeneratedChapter ? "关系变化" : "角色画像"}</p>
            {relationCards.length ? (
              <CardList
                empty="角色关系还没有形成可追踪变化。"
                items={relationCards}
                render={(item) => (
                  <div key={item.name} className="simulation-list__item simulation-list__item--soft">
                    <div>
                      <strong>{item.name}</strong>
                      <p>{item.text}</p>
                    </div>
                  </div>
                )}
              />
            ) : (
              <CardList
                empty="导入材料里还没有可识别的角色画像。"
                items={profiles.slice(0, 4)}
                render={(profile, index) => (
                  <div key={`${profile.name}-${index}`} className="simulation-list__item simulation-list__item--soft">
                    <div>
                      <strong>{profile.name}</strong>
                      <p>{firstNonEmpty(profile.current_state, profile.motivation, profile.role) || "等待补充角色动机。"}</p>
                    </div>
                  </div>
                )}
              />
            )}
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">世界结构</p>
            <CardList
              empty="还没有可展示的地点、阵营或力量体系。"
              items={[
                ...(world.power_system ?? []).slice(0, 2).map((text) => ({ title: "力量体系", text })),
                ...(world.progression_rules ?? []).slice(0, 1).map((text) => ({ title: "升级规则", text })),
                ...(world.economy_rules ?? []).slice(0, 1).map((text) => ({ title: "经济规则", text })),
                ...(world.faction_rules ?? []).slice(0, 1).map((text) => ({ title: "势力规则", text })),
                ...(world.locations ?? []).slice(0, 2).map((entry) => ({ title: `地点：${entry.name}`, text: entry.description || entry.name })),
                ...(world.factions ?? []).slice(0, 2).map((entry) => ({ title: `阵营：${entry.name}`, text: entry.description || entry.name })),
                ...(!world.power_system?.length &&
                !world.progression_rules?.length &&
                !world.economy_rules?.length &&
                !world.faction_rules?.length &&
                !world.locations?.length &&
                !world.factions?.length
                  ? importedOutlineLines.map((text, index) => ({ title: `设定 ${index + 1}`, text }))
                  : []),
              ].slice(0, 4)}
              render={(item, index) => (
                <div key={`${item.title}-${index}`} className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.text}</p>
                  </div>
                </div>
              )}
            />
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">关系网</p>
            <CardList
              empty="暂未识别出角色之间的明确关系，生成第一章前可继续补充角色档案。"
              items={relationships.slice(0, 4)}
              render={(edge, index) => (
                <div key={`${edge.source}-${edge.target}-${index}`} className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>
                      {edge.source} → {edge.target}
                    </strong>
                    <p>{edge.bond || "关系待确认"}</p>
                  </div>
                </div>
              )}
            />
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">记忆护栏</p>
            <div className="simulation-list">
              {memoryFacts.length ? (
                memoryFacts.slice(0, 2).map((fact) => (
                  <div key={fact} className="simulation-list__item simulation-list__item--soft">
                    <div>
                      <strong>必须保留</strong>
                      <p>{fact}</p>
                    </div>
                  </div>
                ))
              ) : (
                <p className="simulation-card__detail">当前还没有章节事实，先使用导入约束作为护栏。</p>
              )}
              {unresolvedThreads.length ? (
                <div className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>未收束线索</strong>
                    <p>{unresolvedThreads[0]}</p>
                  </div>
                </div>
              ) : null}
              {authorConstraints.length ? (
                <div className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>作者约束</strong>
                    <p>{authorConstraints.slice(0, 3).join(" / ")}</p>
                  </div>
                </div>
              ) : null}
            </div>
          </article>
        </div>

        <section className="simulation-footer">
          <div>
            <p className="simulation-card__label">运行说明</p>
            <p className="simulation-card__detail">
              {hasGeneratedChapter ? fallbackSummary(bundle) : "当前是导入后的世界观准备态，尚未运行章节生成。确认世界档案和角色画像后，再点击“开始生成第一章”。"}
            </p>
          </div>
          <div>
            <p className="simulation-card__label">项目背景</p>
            <p className="simulation-card__detail">
              {project?.seed_outline || project?.world_summary || project?.current_focus || "当前项目还没有完整的背景摘要。"}
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
