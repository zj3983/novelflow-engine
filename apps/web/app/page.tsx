import { StoryEditor } from "../components/StoryEditor";
import { StorySidebar } from "../components/StorySidebar";

export default function Page() {
  return (
    <main className="workbench">
      <section className="panel panel-outline" aria-label="Outline Panel">
        <header className="panel__header">Outline</header>
        <div className="panel__body">
          <StorySidebar />
        </div>
      </section>

      <section className="panel panel-draft" aria-label="Chapter Draft Panel">
        <header className="panel__header">Chapter Draft</header>
        <div className="panel__body">
          <StoryEditor />
        </div>
      </section>

      <section className="panel panel-state" aria-label="Character State Panel">
        <header className="panel__header">Character State</header>
        <div className="panel__body">
          <p className="hint">
            Placeholder: this panel will show character cards, relationships,
            foreshadowing, and timeline diffs.
          </p>
        </div>
      </section>

      <section className="panel panel-controls" aria-label="Controls Panel">
        <header className="panel__header">Controls</header>
        <div className="panel__body">
          <button className="btn" type="button" disabled>
            Generate Next Chapter
          </button>
          <button className="btn btn--ghost" type="button" disabled>
            Rollback Chapter
          </button>
          <p className="hint">
            This is a shell for Task 4. Wiring to the API happens in Task 5.
          </p>
        </div>
      </section>
    </main>
  );
}

