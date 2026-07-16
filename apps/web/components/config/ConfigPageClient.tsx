"use client";

import { useEffect, useRef, useState } from "react";

import {
  createDefaultRuntimeSettings,
  fetchCodexCLIInfo,
  fetchRuntimeSettings,
  runtimeStageLabel,
  saveRuntimeSettings,
  testRuntimeSettingsConnection,
  type CodexCLIInfo,
  type RuntimeSettings,
  type RuntimeStageName,
} from "../../lib/api";
import { GlobalApiConfigCard } from "./GlobalApiConfigCard";
import { RuntimeStrategyCard } from "./RuntimeStrategyCard";
import type { RuntimeConnectionMap } from "./types";

function createConnectionMap(): RuntimeConnectionMap {
  return {
    planner: { state: "idle", message: "" },
    writer: { state: "idle", message: "" },
    memory: { state: "idle", message: "" },
  };
}

export function ConfigPageClient() {
  const [settings, setSettings] = useState<RuntimeSettings>(createDefaultRuntimeSettings());
  const [cliInfo, setCliInfo] = useState<CodexCLIInfo | null>(null);
  const [connections, setConnections] = useState<RuntimeConnectionMap>(createConnectionMap());
  const [pageStatus, setPageStatus] = useState<"loading" | "idle" | "saving" | "success" | "error">("loading");
  const [pageMessage, setPageMessage] = useState("正在载入配置中心...");
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    void (async () => {
      try {
        const [nextSettings, nextCliInfo] = await Promise.all([
          fetchRuntimeSettings(),
          fetchCodexCLIInfo().catch(() => null),
        ]);
        if (!mounted.current) return;
        setSettings(nextSettings);
        setCliInfo(nextCliInfo);
        setPageStatus("idle");
        setPageMessage("配置已载入。");
      } catch (error) {
        if (!mounted.current) return;
        setPageStatus("error");
        setPageMessage(error instanceof Error ? error.message : "配置载入失败");
      }
    })();
    return () => {
      mounted.current = false;
    };
  }, []);

  async function testStage(stage: RuntimeStageName) {
    setConnections((current) => ({ ...current, [stage]: { state: "testing", message: "" } }));
    try {
      const result = await testRuntimeSettingsConnection(settings, stage);
      if (!mounted.current) return;
      setConnections((current) => ({
        ...current,
        [stage]: { state: result.ok ? "success" : "error", message: result.message },
      }));
    } catch (error) {
      if (!mounted.current) return;
      setConnections((current) => ({
        ...current,
        [stage]: {
          state: "error",
          message: error instanceof Error ? error.message : `${runtimeStageLabel(stage)}测试失败`,
        },
      }));
    }
  }

  async function saveAll() {
    const selected = settings.providers[settings.provider];
    const blankStage = (["planner", "writer", "memory"] as RuntimeStageName[]).find(
      (stage) => !selected[stage].trim(),
    );
    if (blankStage) {
      setPageStatus("error");
      setPageMessage(`${runtimeStageLabel(blankStage)}模型不能为空。`);
      return;
    }
    setPageStatus("saving");
    setPageMessage("正在保存配置...");
    try {
      const saved = await saveRuntimeSettings(settings);
      if (!mounted.current) return;
      setSettings(saved);
      setPageStatus("success");
      setPageMessage("配置已保存。下一次运行会使用当前阶段模型。");
    } catch (error) {
      if (!mounted.current) return;
      setPageStatus("error");
      setPageMessage(error instanceof Error ? error.message : "保存失败");
    }
  }

  return (
    <main className="config-shell">
      <div className="config-shell__primary">
        <GlobalApiConfigCard value={settings} cliInfo={cliInfo} onChange={setSettings} />
        <RuntimeStrategyCard
          value={settings}
          cliModels={cliInfo?.models ?? []}
          statuses={connections}
          onChange={setSettings}
          onTest={(stage) => void testStage(stage)}
        />

        <section className="config-card config-card--spacious" aria-label="统一保存">
          <div className="config-savebar">
            <button className="btn" type="button" onClick={() => void saveAll()} disabled={pageStatus === "saving"}>
              统一保存
            </button>
            <p className="config-status" aria-live="polite">
              <span className={`runtime-status__badge runtime-status__badge--${pageStatus === "loading" ? "idle" : pageStatus}`}>
                {pageStatus === "loading" ? "载入中" : pageStatus === "saving" ? "保存中" : pageStatus === "success" ? "已保存" : pageStatus === "error" ? "失败" : "待保存"}
              </span>
              <span className="runtime-status__text">{pageMessage}</span>
            </p>
          </div>
        </section>
      </div>
    </main>
  );
}
