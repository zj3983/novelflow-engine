export type StoryCharacterDraft = {
  name: string;
  goal: string;
  frozen: boolean;
};

export type StoryDraft = {
  outline: string;
  characters: StoryCharacterDraft[];
};

type StorySidebarProps = {
  draft: StoryDraft;
  onChange: (next: StoryDraft) => void;
};

export function StorySidebar({ draft, onChange }: StorySidebarProps) {
  function updateCharacter(index: number, next: StoryCharacterDraft) {
    const characters = draft.characters.map((character, currentIndex) =>
      currentIndex === index ? next : character,
    );
    onChange({ ...draft, characters });
  }

  function addCharacter() {
    onChange({
      ...draft,
      characters: [
        ...draft.characters,
        { name: "", goal: "", frozen: false },
      ],
    });
  }

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

      {draft.characters.map((character, index) => (
        <section className="character-card" key={index}>
          <p className="character-card__title">Character {index + 1}</p>

          <div className="field">
            <label htmlFor={`character-name-${index}`}>Character Name {index + 1}</label>
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
            <label htmlFor={`character-goal-${index}`}>Character Goal {index + 1}</label>
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
            <span>Freeze Character</span>
          </label>
        </section>
      ))}

      <button className="btn btn--ghost" type="button" onClick={addCharacter}>
        Add Character
      </button>

      <p className="hint">
        Frozen protagonists keep their current emotion, location, and memory
        untouched while the plot keeps moving around them.
      </p>
    </div>
  );
}
