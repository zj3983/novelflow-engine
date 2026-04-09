export type StoryDraft = {
  outline: string;
  characterName: string;
  characterGoal: string;
  freezeCharacter: boolean;
};

type StorySidebarProps = {
  draft: StoryDraft;
  onChange: (next: StoryDraft) => void;
};

export function StorySidebar({ draft, onChange }: StorySidebarProps) {
  return (
    <div className="sidebar-fields">
      <div className="field">
        <label htmlFor="outline-input">Outline Input</label>
        <textarea
          id="outline-input"
          aria-label="Outline Input"
          placeholder="Paste your novel outline here."
          value={draft.outline}
          onChange={(event) => onChange({ ...draft, outline: event.target.value })}
        />
      </div>

      <div className="field">
        <label htmlFor="character-name">Character Name</label>
        <input
          id="character-name"
          aria-label="Character Name"
          className="text-input"
          value={draft.characterName}
          onChange={(event) => onChange({ ...draft, characterName: event.target.value })}
        />
      </div>

      <div className="field">
        <label htmlFor="character-goal">Character Goal</label>
        <input
          id="character-goal"
          aria-label="Character Goal"
          className="text-input"
          value={draft.characterGoal}
          onChange={(event) => onChange({ ...draft, characterGoal: event.target.value })}
        />
      </div>

      <label className="checkbox-row" htmlFor="freeze-character">
        <input
          id="freeze-character"
          aria-label="Freeze Character"
          type="checkbox"
          checked={draft.freezeCharacter}
          onChange={(event) => onChange({ ...draft, freezeCharacter: event.target.checked })}
        />
        <span>Freeze Character</span>
      </label>

      <p className="hint">
        Frozen protagonists keep their current emotion, location, and memory
        untouched while the plot keeps moving around them.
      </p>
    </div>
  );
}
