"use client";
import { useEffect, useState } from "react";
import { createLiveAdapter } from "../../components/longform/live-adapter";
import { LongformWorkspace } from "../../components/longform/Workspace";
import type { WorkspaceAdapter } from "../../components/longform/product";
export default function AuthorWorkspace() {
  const [adapter, setAdapter] = useState<WorkspaceAdapter>();
  useEffect(() => { const live = createLiveAdapter(); setAdapter(live); return () => live.dispose(); }, []);
  return adapter ? <LongformWorkspace adapter={adapter} /> : <main aria-busy="true">正在打开写作工作区…</main>;
}
