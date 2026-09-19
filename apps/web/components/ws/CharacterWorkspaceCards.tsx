import type { ReactNode } from "react";

import type { DisplayCharacter } from "../../lib/worldDisplay";

export type CharacterWorkspaceCharacter = DisplayCharacter & {
  importance?: string;
  narrative_function?: string;
  profile_status?: string;
  profile_completeness?: number;
};

export type CharacterGroup = {
  key: string;
  title: string;
  characters: CharacterWorkspaceCharacter[];
  protagonist?: boolean;
};

export function CharacterGroupSection({
  group,
  children,
}: {
  group: CharacterGroup;
  children: ReactNode;
}) {
  return (
    <section className="ws-character-group" aria-labelledby={`character-group-${group.key}`}>
      <div className="ws-character-group__head">
        <h3 id={`character-group-${group.key}`}>{group.title}</h3>
        <span>{group.characters.length} 人</span>
      </div>
      <div className={group.protagonist ? "ws-character-group__list ws-character-group__list--hero" : "ws-character-group__list"}>
        {children}
      </div>
    </section>
  );
}

export function CharacterSummaryCard({
  character,
  importanceLabel,
  narrativeLabel,
  isHero,
  expanded,
  onToggle,
  onEdit,
  onComplete,
  busy,
}: {
  character: CharacterWorkspaceCharacter;
  importanceLabel: string;
  narrativeLabel: string;
  isHero?: boolean;
  expanded: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onComplete: () => void;
  busy: boolean;
}) {
  const identity = character.identity_profile?.current_identity || character.identity_profile?.occupation;
  const occupation = character.identity_profile?.occupation && character.identity_profile.current_identity
    ? character.identity_profile.occupation
    : "";
  const goal = character.story_drive?.immediate_goal;
  const status = character.profile_status === "ready" ? "已就绪" : character.profile_status === "stub" ? "待补全" : "档案状态待确认";
  const completeness = typeof character.profile_completeness === "number"
    ? `完整度 ${Math.round(character.profile_completeness <= 1 ? character.profile_completeness * 100 : character.profile_completeness)}%`
    : "";

  return (
    <article className={`ws-character-card ws-character-summary-card${isHero ? " ws-character-summary-card--hero" : ""}`} data-testid={`character-card-${isHero ? "protagonist" : character.character_tier === "minor" ? "minor" : character.role === "supporting" ? "supporting" : "summary"}`}>
      <div className="ws-character-card__head">
        <div>
          <h2>{character.name}</h2>
          <p>{importanceLabel} · {isHero ? "主角" : narrativeLabel}</p>
        </div>
        <div className="ws-character-card__actions">
          <span>{status}{completeness ? ` · ${completeness}` : ""}</span>
          <button type="button" className="ws-button" onClick={onEdit}>编辑</button>
          <button type="button" className="ws-button" disabled={busy} onClick={onComplete}>补全基础侧写</button>
        </div>
      </div>
      <dl className="ws-character-summary-card__facts">
        {identity ? <div><dt>当前身份</dt><dd>{identity}</dd></div> : null}
        {occupation && occupation !== identity ? <div><dt>职业</dt><dd>{occupation}</dd></div> : null}
        {goal ? <div><dt>当前目标</dt><dd>{goal}</dd></div> : null}
        {character.current_life_profile?.immediate_problem ? <div><dt>状态摘要</dt><dd>{character.current_life_profile.immediate_problem}</dd></div> : null}
      </dl>
      {!isHero ? (
        <button type="button" className="ws-character-summary-card__toggle" aria-expanded={expanded} onClick={onToggle}>
          {expanded ? "收起详情" : "查看详情"}
        </button>
      ) : null}
    </article>
  );
}
