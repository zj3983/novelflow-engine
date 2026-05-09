"use client";

import { useEffect } from "react";

export default function ProjectsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[/projects] runtime error:", error);
  }, [error]);

  return (
    <div className="ws-page">
      <div className="ws-card" style={{ borderColor: "var(--ws-danger)", maxWidth: 720 }}>
        <h2 style={{ margin: "0 0 8px", color: "var(--ws-danger)", fontSize: 16 }}>
          页面出错
        </h2>
        <p style={{ margin: "0 0 12px", color: "var(--ws-ink-soft)" }}>
          {error.message || "未知错误"}
        </p>
        {error.digest ? (
          <p style={{ margin: "0 0 12px", fontSize: 12, color: "var(--ws-ink-muted)" }}>
            digest: {error.digest}
          </p>
        ) : null}
        {error.stack ? (
          <pre
            style={{
              fontSize: 11.5,
              background: "#fafbfc",
              padding: 12,
              borderRadius: 6,
              overflow: "auto",
              maxHeight: 280,
              color: "var(--ws-ink-soft)",
              margin: 0,
            }}
          >
            {error.stack}
          </pre>
        ) : null}
        <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
          <button onClick={reset} className="ws-btn ws-btn--primary">
            重试
          </button>
          <a href="/projects" className="ws-btn">
            返回项目列表
          </a>
        </div>
      </div>
    </div>
  );
}
