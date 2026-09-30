"use client";

import { useEffect, useRef, useState } from "react";
import { readModelStatus, testModel, type RuntimeSettings, type RuntimeStageName, type ModelUsability } from "../../lib/config-capabilities";

function ModelStatus({ settings, stage, disabled }: { settings: RuntimeSettings; stage: RuntimeStageName; disabled: boolean }) {
  const [view, setView] = useState<ModelUsability | null>(null);
  const [message, setMessage] = useState("");
  const [testing, setTesting] = useState(false);
  const generation = useRef(0);
  const stageName = stage === "planner" ? "剧情规划" : "正文写作";
  const snapshot = JSON.stringify(settings);
  useEffect(() => {
    const current = ++generation.current;
    setView(null); setMessage("正在读取模型状态…"); setTesting(false);
    if (disabled) return;
    const timer = setTimeout(() => {
      void readModelStatus(JSON.parse(snapshot), stage).then((next) => {
        if (current !== generation.current) return;
        setView(next); setMessage("");
      }).catch(() => {
        if (current === generation.current) setMessage("暂时无法读取模型状态，请稍后重试。");
      });
    }, 200);
    return () => { clearTimeout(timer); generation.current++; };
  }, [snapshot, stage, disabled]);

  async function act(action: ModelUsability["actions"][number]) {
    if (action.id === "edit_connection") {
      document.querySelector<HTMLButtonElement>(`[data-provider-id="${CSS.escape(settings.stages[stage].provider_id)}"]`)?.click();
      requestAnimationFrame(() => document.querySelector<HTMLElement>('[aria-label="供应商账号"] input')?.focus()); return;
    }
    if (action.id === "choose_model") {
      document.getElementById(`config-${stage}-model`)?.focus(); return;
    }
    const current = ++generation.current;
    setTesting(true); setMessage("正在测试模型，请稍候…");
    try {
      const next = await testModel(settings, stage);
      if (current !== generation.current) return;
      setView(next); setMessage("");
    } catch {
      if (current === generation.current) setMessage("暂时无法完成检测，请稍后重试。");
    } finally { if (current === generation.current) setTesting(false); }
  }
  return <section aria-label={`${stageName}使用状态`}>
    <h3>{stageName} · {settings.stages[stage].model}</h3>
    {view && !message && <><strong>{view.heading}</strong><p>{view.message}</p></>}
    <p role="status">{message}</p>
    {view?.actions.map((action) => <button key={action.id} className="btn btn--secondary" type="button" disabled={disabled || testing} onClick={() => void act(action)}>{action.label}</button>)}
  </section>;
}

export function CapabilityPanel({ settings, disabled }: { settings: RuntimeSettings; disabled: boolean }) {
  return <section className="config-card config-card--spacious" aria-label="模型使用状态">
    <h2>模型使用状态</h2>
    <p>测试会发送简短请求，可能产生少量费用。修改连接设置或模型后，请重新检测。</p>
    {(["planner", "writer"] as const).map((stage) => <ModelStatus key={stage} settings={settings} stage={stage} disabled={disabled} />)}
  </section>;
}
