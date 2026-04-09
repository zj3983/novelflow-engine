export function StoryEditor() {
  return (
    <div className="field">
      <label htmlFor="draft-output">Draft</label>
      <textarea
        id="draft-output"
        placeholder="Generated chapter text will appear here."
        defaultValue="Chapter 1 body."
        readOnly
      />
      <p className="hint" style={{ marginTop: 10 }}>
        This is a placeholder draft area for the shell UI.
      </p>
    </div>
  );
}

