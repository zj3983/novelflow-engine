"use client";

import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { updateProject, type ImportedWorldBlueprint } from "../../../../lib/api";
import { buildRuleCards } from "../../../../lib/ruleCards";
import { cleanLines, compactRecord, mergeCharacters, panelRows, richProfileEntries, shortStatus } from "../../../../lib/worldDisplay";

type ChapterBeat = {
  chapter?: number;
  title?: string;
  required_payoff?: string;
  ending_hook?: string;
};

function linesFromText(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function asChapterBeats(value: unknown): ChapterBeat[] {
  return Array.isArray(value)
    ? value
        .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
        .map((item) => ({
          chapter: Number(item.chapter || 0) || undefined,
          title: typeof item.title === "string" ? item.title : "",
          required_payoff: typeof item.required_payoff === "string" ? item.required_payoff : "",
          ending_hook: typeof item.ending_hook === "string" ? item.ending_hook : "",
        }))
    : [];
}

function characterCardBadge(state: string | undefined): string {
  if (state === "proposed") return "待出场卡";
  if (state === "active") return "确定性角色卡";
  return "记录卡";
}

export default function WorldPage() {
  const { project, story, error, encodedProjectId, projectId, refresh } = useProjectWorkspace();
  const characters = mergeCharacters(project?.character_profiles, story?.characters);
  const worldFacts = cleanLines(story?.world_facts, 14);
  const constraints = cleanLines(project?.author_constraints ?? story?.author_constraints, 10);
  const ruleCards = buildRuleCards(story?.history, story?.world_facts);
  const blueprint = project?.world_blueprint ?? {};
  const openingArc = blueprint.opening_arc ?? {};
  const chapterBeats = useMemo(() => asChapterBeats((openingArc as { chapter_beats?: unknown }).chapter_beats), [openingArc]);
  const forbiddenBreaks = cleanLines(blueprint.forbidden_breaks, 8);
  const progressionRules = cleanLines(blueprint.progression_rules, 8);
  const [editingOutline, setEditingOutline] = useState(false);
  const [savingOutline, setSavingOutline] = useState(false);
  const [outlineMessage, setOutlineMessage] = useState("");
  const [draftArc, setDraftArc] = useState("");
  const [draftFocus, setDraftFocus] = useState("");
  const [draftForbidden, setDraftForbidden] = useState("");
  const [draftBeats, setDraftBeats] = useState<ChapterBeat[]>([]);

  useEffect(() => {
    setDraftArc(String(blueprint.current_arc ?? ""));
    setDraftFocus(project?.current_focus ?? "");
    setDraftForbidden((blueprint.forbidden_breaks ?? []).join("\n"));
    setDraftBeats(chapterBeats);
  }, [blueprint.current_arc, blueprint.forbidden_breaks, chapterBeats, project?.current_focus]);

  function updateDraftBeat(index: number, patch: Partial<ChapterBeat>) {
    setDraftBeats((current) => current.map((beat, beatIndex) => (beatIndex === index ? { ...beat, ...patch } : beat)));
  }

  function addDraftBeat() {
    const nextChapter = Math.max(0, ...draftBeats.map((beat) => Number(beat.chapter || 0))) + 1;
    setDraftBeats((current) => [...current, { chapter: nextChapter, title: "", required_payoff: "", ending_hook: "" }]);
  }

  function removeDraftBeat(index: number) {
    setDraftBeats((current) => current.filter((_, beatIndex) => beatIndex !== index));
  }

  async function saveOutline() {
    if (!project) return;
    setSavingOutline(true);
    setOutlineMessage("");
    try {
      const nextBlueprint: ImportedWorldBlueprint = {
        ...blueprint,
        current_arc: draftArc.trim(),
        forbidden_breaks: linesFromText(draftForbidden),
        opening_arc: {
          ...(openingArc as Record<string, unknown>),
          chapter_beats: draftBeats
            .filter((beat) => beat.chapter || beat.title || beat.required_payoff || beat.ending_hook)
            .map((beat) => ({
              chapter: Number(beat.chapter || 0),
              title: beat.title?.trim() ?? "",
              required_payoff: beat.required_payoff?.trim() ?? "",
              ending_hook: beat.ending_hook?.trim() ?? "",
            })),
        } as ImportedWorldBlueprint["opening_arc"],
      };
      await updateProject(projectId, {
        current_focus: draftFocus.trim(),
        seed_outline: draftArc.trim() || project.seed_outline,
        world_blueprint: nextBlueprint,
      });
      setEditingOutline(false);
      setOutlineMessage("大纲已保存，下一次推演和写作包会读取这版大纲。");
      refresh();
    } catch (err) {
      setOutlineMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setSavingOutline(false);
    }
  }

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="人物 / 世界"
        subtitle={project?.world_summary || "维护角色卡、世界事实和作者约束。"}
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : (
        <div className="ws-editor-layout">
          <section className="ws-card">
            <p className="ws-card__title">角色卡</p>
            {characters.length > 0 ? (
              <div className="ws-character-list">
                {characters.map((character) => {
                  const panel = character.game_panel;
                  const rows = panelRows(panel);
                  const attributes = compactRecord(panel?.attributes);
                  const equipment = compactRecord(panel?.equipment);
                  const inventory = compactRecord(panel?.inventory);
                  const motiveRows = [
                    ["人设类型", character.character_type],
                    ["核心动机", character.core_motivation],
                    ["行为逻辑", character.behavior_logic],
                    ["互动模式", character.interaction_mode],
                    ["故事功能", character.story_function],
                    ["本章作用", character.chapter_role],
                  ].filter(([, value]) => typeof value === "string" && value.trim());
                  const socialRows = richProfileEntries(character.social_profile);
                  const psychRows = richProfileEntries(character.psychological_profile);
                  const moralRows = richProfileEntries(character.moral_profile);
                  const poisonPoints = cleanLines(character.poison_points, 8);

                  return (
                    <article className="ws-character-card" key={character.name}>
                      <div className="ws-character-card__head">
                        <div>
                          <h2>{character.name}</h2>
                          <p>
                            {[character.role, character.game_id || panel?.game_id, character.lifecycle_state]
                              .filter(Boolean)
                              .join(" / ") || "角色"}
                          </p>
                        </div>
                        <span>
                          {characterCardBadge(character.lifecycle_state)}
                          {panel?.updated_chapter ? ` · 第 ${panel.updated_chapter} 章更新` : ""}
                        </span>
                      </div>

                      <p className="ws-character-card__status">{shortStatus(character)}</p>

                      {rows.length > 0 ? (
                        <dl className="ws-panel-grid">
                          {rows.map(([label, value]) => (
                            <div key={label}>
                              <dt>{label}</dt>
                              <dd>{value}</dd>
                            </div>
                          ))}
                        </dl>
                      ) : null}

                      {motiveRows.length > 0 ? (
                        <div className="ws-character-section-grid">
                          {motiveRows.map(([label, value]) => (
                            <section className="ws-character-mini" key={label}>
                              <strong>{label}</strong>
                              <p>{value}</p>
                            </section>
                          ))}
                        </div>
                      ) : null}

                      {[socialRows, psychRows, moralRows].some((rows) => rows.length > 0) ? (
                        <div className="ws-character-block">
                          <strong>三维档案</strong>
                          <div className="ws-profile-columns">
                            {[
                              ["社会面", socialRows],
                              ["心理面", psychRows],
                              ["底线面", moralRows],
                            ].map(([title, entries]) =>
                              Array.isArray(entries) && entries.length > 0 ? (
                                <section className="ws-profile-column" key={title as string}>
                                  <b>{title as string}</b>
                                  <dl>
                                    {entries.map(([label, value]) => (
                                      <div key={label}>
                                        <dt>{label}</dt>
                                        <dd>{value}</dd>
                                      </div>
                                    ))}
                                  </dl>
                                </section>
                              ) : null,
                            )}
                          </div>
                        </div>
                      ) : null}

                      {poisonPoints.length > 0 ? (
                        <div className="ws-character-block">
                          <strong>毒点</strong>
                          <div className="ws-tag-row">
                            {poisonPoints.map((point, index) => (
                              <span className="ws-danger-tag" key={`${point}-${index}`}>
                                {point}
                              </span>
                            ))}
                          </div>
                        </div>
                      ) : null}

                      {character.goals?.length ? (
                        <div className="ws-character-block">
                          <strong>目标</strong>
                          <ul>
                            {character.goals.slice(0, 4).map((goal, index) => (
                              <li key={`${goal}-${index}`}>{goal}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}

                      {character.memory?.length ? (
                        <div className="ws-character-block">
                          <strong>记忆</strong>
                          <ul>
                            {cleanLines(character.memory, 3).map((memory, index) => (
                              <li key={`${memory}-${index}`}>{memory}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}

                      {[...attributes, ...equipment, ...inventory].length > 0 ? (
                        <div className="ws-character-block">
                          <strong>面板细节</strong>
                          <ul>
                            {[...attributes, ...equipment, ...inventory].slice(0, 8).map((item, index) => (
                              <li key={`${item}-${index}`}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            ) : (
              <p className="ws-card__hint">暂无角色档案。</p>
            )}

            <div className="ws-character-block">
              <div className="ws-section-head">
                <div>
                  <p className="ws-card__title">大纲</p>
                  <p className="ws-card__hint">保存后会写回文件项目，下一次剧情推演和写作包会读取这里的章节节拍。</p>
                </div>
                <div className="ws-toolbar">
                  {editingOutline ? (
                    <>
                      <button className="ws-btn ws-btn--sm" type="button" onClick={() => setEditingOutline(false)} disabled={savingOutline}>
                        取消
                      </button>
                      <button className="ws-btn ws-btn--sm ws-btn--primary" type="button" onClick={() => void saveOutline()} disabled={savingOutline}>
                        {savingOutline ? "保存中..." : "保存大纲"}
                      </button>
                    </>
                  ) : (
                    <button className="ws-btn ws-btn--sm" type="button" onClick={() => setEditingOutline(true)}>
                      编辑大纲
                    </button>
                  )}
                </div>
              </div>
              {outlineMessage ? <p className="ws-card__hint">{outlineMessage}</p> : null}

              {editingOutline ? (
                <div className="ws-character-section-grid">
                  <label className="ws-character-mini">
                    <strong>当前主线</strong>
                    <textarea className="ws-input" value={draftArc} onChange={(event) => setDraftArc(event.target.value)} rows={4} />
                  </label>
                  <label className="ws-character-mini">
                    <strong>下一章目标</strong>
                    <textarea className="ws-input" value={draftFocus} onChange={(event) => setDraftFocus(event.target.value)} rows={4} />
                  </label>
                  <label className="ws-character-mini">
                    <strong>禁写项</strong>
                    <textarea className="ws-input" value={draftForbidden} onChange={(event) => setDraftForbidden(event.target.value)} rows={5} />
                  </label>
                  <section className="ws-character-mini">
                    <strong>章节节拍</strong>
                    <div className="ws-rule-list">
                      {draftBeats.map((beat, index) => (
                        <article className="ws-rule-item" key={`${beat.chapter}-${index}`}>
                          <div className="ws-panel-grid">
                            <label>
                              <dt>章</dt>
                              <input
                                className="ws-input"
                                type="number"
                                value={beat.chapter ?? ""}
                                onChange={(event) => updateDraftBeat(index, { chapter: Number(event.target.value || 0) })}
                              />
                            </label>
                            <label>
                              <dt>标题</dt>
                              <input className="ws-input" value={beat.title ?? ""} onChange={(event) => updateDraftBeat(index, { title: event.target.value })} />
                            </label>
                          </div>
                          <label>
                            <dt>必须兑现</dt>
                            <input
                              className="ws-input"
                              value={beat.required_payoff ?? ""}
                              onChange={(event) => updateDraftBeat(index, { required_payoff: event.target.value })}
                            />
                          </label>
                          <label>
                            <dt>章末钩子</dt>
                            <input
                              className="ws-input"
                              value={beat.ending_hook ?? ""}
                              onChange={(event) => updateDraftBeat(index, { ending_hook: event.target.value })}
                            />
                          </label>
                          <button className="ws-btn ws-btn--sm" type="button" onClick={() => removeDraftBeat(index)}>
                            删除
                          </button>
                        </article>
                      ))}
                    </div>
                    <button className="ws-btn ws-btn--sm" type="button" onClick={addDraftBeat}>
                      新增章节节拍
                    </button>
                  </section>
                </div>
              ) : (
                <>
                  <div className="ws-character-section-grid">
                    <section className="ws-character-mini">
                      <strong>当前主线</strong>
                      <p>{blueprint.current_arc || "暂无当前主线。"}</p>
                    </section>
                    <section className="ws-character-mini">
                      <strong>下一章目标</strong>
                      <p>{project?.current_focus || "暂无下一章目标。"}</p>
                    </section>
                  </div>
                  {chapterBeats.length > 0 ? (
                    <div className="ws-rule-list">
                      {chapterBeats.map((beat, index) => (
                        <article className="ws-rule-item" key={`${beat.chapter}-${index}`}>
                          <div>
                            <strong>
                              第 {beat.chapter ?? "?"} 章 {beat.title || ""}
                            </strong>
                            <span>{beat.required_payoff || "暂无必须兑现"}</span>
                          </div>
                          <p>{beat.ending_hook || "暂无章末钩子。"}</p>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p className="ws-card__hint">暂无章节节拍。</p>
                  )}
                  {progressionRules.length ? (
                    <div className="ws-character-block">
                      <strong>推进规则</strong>
                      <ul>
                        {progressionRules.map((rule, index) => (
                          <li key={`${rule}-${index}`}>{rule}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {forbiddenBreaks.length ? (
                    <div className="ws-character-block">
                      <strong>禁写项</strong>
                      <ul>
                        {forbiddenBreaks.map((item, index) => (
                          <li key={`${item}-${index}`}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </section>

          <aside className="ws-sidepanel">
            <section className="ws-card">
              <div className="ws-section-head">
                <p className="ws-card__title">规则卡</p>
                <span className="ws-toolbar__meta">{ruleCards.length} 条</span>
              </div>
              {ruleCards.length > 0 ? (
                <div className="ws-rule-list">
                  {ruleCards.map((card) => (
                    <article className="ws-rule-item" key={card.id}>
                      <div>
                        <strong>{card.title}</strong>
                        <span>
                          {card.category} · 第 {card.firstChapter} 章
                        </span>
                      </div>
                      <p>{card.rule}</p>
                    </article>
                  ))}
                </div>
              ) : (
                <p className="ws-card__hint">暂无规则卡。</p>
              )}
            </section>
            <section className="ws-card">
              <p className="ws-card__title">世界事实</p>
              {worldFacts.length > 0 ? (
                <ul className="ws-plain-list">
                  {worldFacts.map((fact, index) => (
                    <li key={`${fact}-${index}`}>{fact}</li>
                  ))}
                </ul>
              ) : (
                <p className="ws-card__hint">暂无可读世界事实。</p>
              )}
            </section>
            <section className="ws-card">
              <p className="ws-card__title">作者约束</p>
              {constraints.length > 0 ? (
                <ul className="ws-plain-list">
                  {constraints.map((constraint, index) => (
                    <li key={`${constraint}-${index}`}>{constraint}</li>
                  ))}
                </ul>
              ) : (
                <p className="ws-card__hint">暂无作者约束。</p>
              )}
            </section>
          </aside>
        </div>
      )}
    </div>
  );
}
