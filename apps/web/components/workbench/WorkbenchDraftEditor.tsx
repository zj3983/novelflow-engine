"use client";

import type { StoryDraft } from "../StorySidebar";

type WorkbenchDraftEditorProps = {
  draft: StoryDraft;
  onChange: (next: StoryDraft | ((current: StoryDraft) => StoryDraft)) => void;
  onAddCharacter: () => void;
};

export function WorkbenchDraftEditor({ draft, onChange, onAddCharacter }: WorkbenchDraftEditorProps) {
  function updateCharacter(
    index: number,
    next: StoryDraft["characters"][number],
  ) {
    onChange((currentDraft) => ({
      ...currentDraft,
      characters: currentDraft.characters.map((character, currentIndex) =>
        currentIndex === index ? next : character,
      ),
    }));
  }

  return (
    <section className="panel" aria-label="草稿编辑面板">
      <header className="panel__header">草稿编辑</header>
      <div className="panel__body">
        <p className="hint" style={{ marginBottom: 12 }}>
          这里保留大纲和角色编辑，方便在导入之前先把起点整理清楚。
        </p>

        <div className="field">
          <label htmlFor="outline-input">大纲输入</label>
          <textarea
            id="outline-input"
            aria-label="Outline Input"
            placeholder="把你的小说大纲写在这里。"
            value={draft.outline}
            onChange={(event) =>
              onChange((currentDraft) => ({ ...currentDraft, outline: event.target.value }))
            }
          />
        </div>

        {draft.characters.map((character, index) => (
          <section className="character-card" key={index}>
            <p className="character-card__title">角色 {index + 1}</p>

            <div className="field">
              <label htmlFor={`character-name-${index}`}>角色名称 {index + 1}</label>
              <input
                id={`character-name-${index}`}
                aria-label={`Character Name ${index + 1}`}
                className="text-input"
                value={character.name}
                onChange={(event) =>
                  updateCharacter(index, { ...character, name: event.target.value })
                }
              />
            </div>

            <div className="field">
              <label htmlFor={`character-goal-${index}`}>角色目标 {index + 1}</label>
              <input
                id={`character-goal-${index}`}
                aria-label={`Character Goal ${index + 1}`}
                className="text-input"
                value={character.goal}
                onChange={(event) =>
                  updateCharacter(index, { ...character, goal: event.target.value })
                }
              />
            </div>

            <label className="checkbox-row" htmlFor={`freeze-character-${index}`}>
              <input
                id={`freeze-character-${index}`}
                aria-label={index === 0 ? "Freeze Character" : `Freeze Character ${index + 1}`}
                type="checkbox"
                checked={character.frozen}
                onChange={(event) =>
                  updateCharacter(index, { ...character, frozen: event.target.checked })
                }
              />
              <span>冻结角色</span>
            </label>

            <div className="field">
              <label htmlFor={`relationship-target-${index}`}>关系对象 {index + 1}</label>
              <input
                id={`relationship-target-${index}`}
                aria-label={`Relationship Target ${index + 1}`}
                className="text-input"
                value={character.relationshipTarget}
                onChange={(event) =>
                  updateCharacter(index, { ...character, relationshipTarget: event.target.value })
                }
              />
            </div>

            <div className="field">
              <label htmlFor={`relationship-bond-${index}`}>关系类型 {index + 1}</label>
              <input
                id={`relationship-bond-${index}`}
                aria-label={`Relationship Bond ${index + 1}`}
                className="text-input"
                value={character.relationshipBond}
                onChange={(event) =>
                  updateCharacter(index, { ...character, relationshipBond: event.target.value })
                }
              />
            </div>

            <div className="field-row">
              <div className="field">
                <label htmlFor={`trust-level-${index}`}>信任值 {index + 1}</label>
                <input
                  id={`trust-level-${index}`}
                  aria-label={`Trust Level ${index + 1}`}
                  className="text-input"
                  value={character.trust}
                  onChange={(event) =>
                    updateCharacter(index, { ...character, trust: event.target.value })
                  }
                />
              </div>

              <div className="field">
                <label htmlFor={`tension-level-${index}`}>紧张值 {index + 1}</label>
                <input
                  id={`tension-level-${index}`}
                  aria-label={`Tension Level ${index + 1}`}
                  className="text-input"
                  value={character.tension}
                  onChange={(event) =>
                    updateCharacter(index, { ...character, tension: event.target.value })
                  }
                />
              </div>
            </div>
          </section>
        ))}

        <button className="btn btn--ghost" type="button" onClick={onAddCharacter}>
          添加角色
        </button>

        <p className="hint" style={{ marginTop: 10 }}>
          角色冻结后仍会保留当前状态，但剧情仍会继续围绕他们推进。
        </p>
      </div>
    </section>
  );
}
