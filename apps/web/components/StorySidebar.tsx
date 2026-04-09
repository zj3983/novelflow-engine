export function StorySidebar() {
  return (
    <div className="field">
      <label htmlFor="outline-input">Seed</label>
      <textarea
        id="outline-input"
        placeholder="Paste your novel outline here. In Task 5, this will persist via the API."
        defaultValue="A detective prince uncovers palace crimes."
      />
      <p className="hint" style={{ marginTop: 10 }}>
        Tip: keep one paragraph per story arc.
      </p>
    </div>
  );
}
