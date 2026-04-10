import { useState } from "react";

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

export type AgentMode = "Rule-based" | "LLM-assisted";

export type NewCharacterPolicy = "Director review" | "Auto-approve named candidates" | "Manual review";

export type AgentSettings = {
  mode: AgentMode;
  characterModel: string;
  directorModel: string;
  writerModel: string;
  temperature: string;
  newCharacterPolicy: NewCharacterPolicy;
};

type StorySidebarProps = {
  draft: StoryDraft;
  agentSettings: AgentSettings;
  onChange: (next: StoryDraft) => void;
  onAgentSettingsChange: (next: AgentSettings) => void;
};

export function StorySidebar({
  draft,
  agentSettings,
  onChange,
  onAgentSettingsChange,
}: StorySidebarProps) {
  const [isAgentSettingsOpen, setIsAgentSettingsOpen] = useState(true);

  function updateCharacter(index: number, next: StoryCharacterDraft) {
    const characters = draft.characters.map((character, currentIndex) =>
      currentIndex === index ? next : character,
    );
    onChange({ ...draft, characters });
  }

  function updateAgentSettings(next: Partial<AgentSettings>) {
    onAgentSettingsChange({ ...agentSettings, ...next });
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
      <section className="agent-settings">
        <button
          className="agent-settings__toggle"
          type="button"
          onClick={() => setIsAgentSettingsOpen((value) => !value)}
          aria-expanded={isAgentSettingsOpen}
        >
          Agent Settings
        </button>
        {isAgentSettingsOpen ? (
          <div className="agent-settings__body">
          <div className="agent-settings__grid">
            <div className="field">
              <label htmlFor="agent-mode">Agent Mode</label>
              <select
                id="agent-mode"
                aria-label="Agent Mode"
                className="text-input"
                value={agentSettings.mode}
                onChange={(event) =>
                  updateAgentSettings({
                    mode: event.target.value as AgentMode,
                  })
                }
              >
                <option value="Rule-based">Rule-based</option>
                <option value="LLM-assisted">LLM-assisted</option>
              </select>
            </div>

            <div className="field">
              <label htmlFor="new-character-policy">New Character Policy</label>
              <select
                id="new-character-policy"
                aria-label="New Character Policy"
                className="text-input"
                value={agentSettings.newCharacterPolicy}
                onChange={(event) =>
                  updateAgentSettings({
                    newCharacterPolicy: event.target.value as NewCharacterPolicy,
                  })
                }
              >
                <option value="Director review">Director review</option>
                <option value="Auto-approve named candidates">Auto-approve named candidates</option>
                <option value="Manual review">Manual review</option>
              </select>
            </div>
          </div>

          <div className="field">
            <label htmlFor="character-model">Character Model</label>
            <input
              id="character-model"
              aria-label="Character Model"
              className="text-input"
              value={agentSettings.characterModel}
              onChange={(event) =>
                updateAgentSettings({ characterModel: event.target.value })
              }
            />
          </div>

          <div className="field">
            <label htmlFor="director-model">Director Model</label>
            <input
              id="director-model"
              aria-label="Director Model"
              className="text-input"
              value={agentSettings.directorModel}
              onChange={(event) =>
                updateAgentSettings({ directorModel: event.target.value })
              }
            />
          </div>

          <div className="field">
            <label htmlFor="writer-model">Writer Model</label>
            <input
              id="writer-model"
              aria-label="Writer Model"
              className="text-input"
              value={agentSettings.writerModel}
              onChange={(event) =>
                updateAgentSettings({ writerModel: event.target.value })
              }
            />
          </div>

          <div className="field">
            <label htmlFor="agent-temperature">Temperature</label>
            <input
              id="agent-temperature"
              aria-label="Temperature"
              className="text-input"
              inputMode="decimal"
              value={agentSettings.temperature}
              onChange={(event) =>
                updateAgentSettings({ temperature: event.target.value })
              }
            />
          </div>

          <div className="agent-settings__summary" aria-label="Agent Settings Summary">
            <p className="hint">Mode: {agentSettings.mode}</p>
            <p className="hint">Character model: {agentSettings.characterModel}</p>
            <p className="hint">Director model: {agentSettings.directorModel}</p>
            <p className="hint">Writer model: {agentSettings.writerModel}</p>
            <p className="hint">Temperature: {agentSettings.temperature}</p>
            <p className="hint">New character policy: {agentSettings.newCharacterPolicy}</p>
          </div>
          </div>
        ) : null}
      </section>

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
