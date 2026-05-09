"use client";

import { useEffect } from "react";

export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[root] runtime error:", error);
  }, [error]);

  return (
    <div style={{ padding: 24, fontFamily: "ui-sans-serif, system-ui" }}>
      <h2 style={{ color: "#b91c1c", margin: "0 0 12px" }}>页面出错</h2>
      <p style={{ color: "#374151", margin: "0 0 12px" }}>{error.message || "未知错误"}</p>
      {error.digest ? (
        <p style={{ fontSize: 12, color: "#9ca3af" }}>digest: {error.digest}</p>
      ) : null}
      {error.stack ? (
        <pre
          style={{
            fontSize: 11,
            background: "#f6f6f7",
            padding: 12,
            borderRadius: 6,
            overflow: "auto",
            maxHeight: 360,
          }}
        >
          {error.stack}
        </pre>
      ) : null}
      <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
        <button
          onClick={reset}
          style={{
            padding: "6px 14px",
            background: "#111418",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            cursor: "pointer",
          }}
        >
          重试
        </button>
        <a
          href="/projects"
          style={{
            padding: "6px 14px",
            background: "#fff",
            color: "#111418",
            border: "1px solid #e5e7eb",
            borderRadius: 6,
            textDecoration: "none",
          }}
        >
          前往新版
        </a>
      </div>
    </div>
  );
}
