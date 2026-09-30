"use client";

import { useEffect, useState } from "react";
import { createDemoAdapter } from "../../../components/longform/demo-adapter";
import { LongformWorkspace } from "../../../components/longform/Workspace";
import type { WorkspaceAdapter } from "../../../components/longform/product";

export default function LongformDemo() {
  const [adapter, setAdapter] = useState<WorkspaceAdapter>();
  useEffect(() => { const demo = createDemoAdapter(); setAdapter(demo); return () => demo.dispose(); }, []);
  return adapter ? <LongformWorkspace adapter={adapter} /> : <main aria-busy="true">正在打开模拟工作区…</main>;
}
