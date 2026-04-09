export type StoryCharacterDraft = {
  name: string;
  goal: string;
  frozen: boolean;
  relationshipTarget: string;
  relationshipBond: string;
  trust: string;
  tension: string;
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
        {
          name: "",
          goal: "",
          frozen: false,
          relationshipTarget: "",
          relationshipBond: "",
          trust: "0.0",
          tension: "0.0",
        },
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

          <div className="field">
            <label htmlFor={`relationship-target-${index}`}>Relationship Target {index + 1}</label>
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
            <label htmlFor={`relationship-bond-${index}`}>Relationship Bond {index + 1}</label>
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
              <label htmlFor={`trust-level-${index}`}>Trust Level {index + 1}</label>
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
              <label htmlFor={`tension-level-${index}`}>Tension Level {index + 1}</label>
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
