"use client";

import { useEffect, useRef, useState } from "react";

import {
  createDefaultAgentSettings,
  createDefaultRuntimeSettings,
  fetchRuntimeSettings,
  fetchRuntimeStrategy,
  runtimeTargetLabel,
  saveRuntimeSettings,
  saveRuntimeStrategy,
  testRuntimeSettingsConnection,
  type RuntimeConnectionTarget,
  type RuntimeSettings,
  type RuntimeStrategySettings,
} from "../../lib/api";
import { AgentOverrideGrid, type AgentOverrideMeta } from "./AgentOverrideGrid";
import { GlobalApiConfigCard } from "./GlobalApiConfigCard";
import { RuntimeStrategyCard } from "./RuntimeStrategyCard";
import type { RuntimeConnectionMap } from "./types";

const AGENT_META: Array<Omit<AgentOverrideMeta, "modelName">> = [
  { key: "character", label: "角色代理" },
  { key: "director", label: "导演代理" },
  { key: "writer", label: "写作代理" },
  { key: "memory", label: "记忆代理" },
];

function createConnectionMap(): RuntimeConnectionMap {
  return {
    global: { state: "idle", message: "" },
    character: { state: "idle", message: "" },
    director: { state: "idle", message: "" },
    writer: { state: "idle", message: "" },
    memory: { state: "idle", message: "" },
  };
}

function runtimeStrategyModelForTarget(
  target: RuntimeConnectionTarget,
  strategy: RuntimeStrategySettings,
): string {
  if (target === "character") return strategy.character_model || strategy.global_model;
  if (target === "director") return strategy.director_model || strategy.global_model;
  if (target === "writer") return strategy.writer_model || strategy.global_model;
  if (target === "memory") return strategy.memory_model || strategy.global_model;
  return strategy.global_model;
}

export function ConfigPageClient() {
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSettings>(createDefaultRuntimeSettings());
  const [runtimeStrategy, setRuntimeStrategy] = useState<RuntimeStrategySettings>(createDefaultAgentSettings());
  const [connectionMap, setConnectionMap] = useState<RuntimeConnectionMap>(createConnectionMap());
  const [pageStatus, setPageStatus] = useState<"loading" | "idle" | "saving" | "success" | "error">("loading");
  const [pageMessage, setPageMessage] = useState("正在载入配置中心...");
  const isMountedRef = useRef(true);
  const saveResetTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let active = true;
    isMountedRef.current = true;

    void (async () => {
      try {
        const [settings, strategy] = await Promise.all([fetchRuntimeSettings(), fetchRuntimeStrategy()]);
        if (!active) {
          return;
        }
        setRuntimeSettings(settings);
        setRuntimeStrategy(strategy);
        setPageStatus("idle");
        setPageMessage("配置已载入。");
      } catch (error) {
        if (!active) {
          return;
        }
        setPageStatus("error");
        setPageMessage(error instanceof Error ? error.message : "配置载入失败");
      }
    })();

    return () => {
      active = false;
      isMountedRef.current = false;
      if (saveResetTimeoutRef.current !== null) {
        clearTimeout(saveResetTimeoutRef.current);
        saveResetTimeoutRef.current = null;
      }
    };
  }, []);

  function updateGlobal(next: RuntimeSettings["global"]) {
    setRuntimeSettings((current) => ({ ...current, global: next }));
  }

  function updateAgent(
    agent: keyof RuntimeSettings["agents"],
    next: RuntimeSettings["agents"][keyof RuntimeSettings["agents"]],
  ) {
    setRuntimeSettings((current) => ({
      ...current,
      agents: {
        ...current.agents,
        [agent]: next,
      },
    }));
  }

  async function testConnection(target: RuntimeConnectionTarget) {
    setConnectionMap((current) => ({
      ...current,
      [target]: { state: "testing", message: "" },
    }));

    try {
      const result = await testRuntimeSettingsConnection(
        runtimeSettings,
        target,
        runtimeStrategyModelForTarget(target, runtimeStrategy),
      );
      if (!isMountedRef.current) {
        return;
      }
      setConnectionMap((current) => ({
        ...current,
        [target]: {
          state: result.ok ? "success" : "error",
          message: result.message,
        },
      }));
    } catch (error) {
      if (!isMountedRef.current) {
        return;
      }
      setConnectionMap((current) => ({
        ...current,
        [target]: {
          state: "error",
          message: error instanceof Error ? error.message : `${runtimeTargetLabel(target)} 测试失败`,
        },
      }));
    }
  }

  async function saveAll() {
    if (saveResetTimeoutRef.current !== null) {
      clearTimeout(saveResetTimeoutRef.current);
      saveResetTimeoutRef.current = null;
    }

    setPageStatus("saving");
    setPageMessage("正在统一保存配置...");

    try {
      await Promise.all([saveRuntimeSettings(runtimeSettings), saveRuntimeStrategy(runtimeStrategy)]);
      if (!isMountedRef.current) {
        return;
      }
      setPageStatus("success");
      setPageMessage("配置已保存。");
      saveResetTimeoutRef.current = setTimeout(() => {
        if (isMountedRef.current) {
          setPageStatus("idle");
          setPageMessage("配置已保存。");
        }
        saveResetTimeoutRef.current = null;
      }, 2500);
    } catch (error) {
      if (!isMountedRef.current) {
        return;
      }
      setPageStatus("error");
      setPageMessage(error instanceof Error ? error.message : "统一保存失败");
    }
  }

  const agentCards = AGENT_META.map((meta) => ({
    ...meta,
    modelName:
      meta.key === "character"
        ? runtimeStrategy.character_model
        : meta.key === "director"
          ? runtimeStrategy.director_model
          : meta.key === "writer"
            ? runtimeStrategy.writer_model
            : runtimeStrategy.memory_model,
  }));
  const usesOpenAICompatibleApi = runtimeSettings.global.provider === "openai";

  return (
    <main className="config-shell">
      <div className="config-shell__primary">
        <GlobalApiConfigCard
          value={runtimeSettings.global}
          status={connectionMap.global.state}
          statusMessage={connectionMap.global.message}
          onChange={updateGlobal}
          onTest={() => void testConnection("global")}
        />

        {usesOpenAICompatibleApi ? (
          <RuntimeStrategyCard value={runtimeStrategy} onChange={setRuntimeStrategy} />
        ) : null}

        <section className="config-card config-card--spacious" aria-label="统一保存">
          <div className="config-card__header">
            <div>
              <h2 className="config-card__title">统一保存</h2>
            </div>
          </div>

          <div className="config-savebar">
            <button className="btn" type="button" onClick={() => void saveAll()} disabled={pageStatus === "saving"}>
              统一保存
            </button>
            <p className="config-status" aria-live="polite">
              <span className={`runtime-status__badge runtime-status__badge--${pageStatus === "loading" ? "idle" : pageStatus}`}>
                {pageStatus === "loading"
                  ? "载入中"
                  : pageStatus === "saving"
                    ? "保存中"
                    : pageStatus === "success"
                      ? "已保存"
                      : pageStatus === "error"
                        ? "失败"
                        : "待保存"}
              </span>
              <span className="runtime-status__text">{pageMessage}</span>
            </p>
          </div>
        </section>
      </div>

      {usesOpenAICompatibleApi ? (
        <div className="config-shell__secondary">
          <AgentOverrideGrid
            agents={runtimeSettings.agents}
            inherited={runtimeSettings.global}
            statuses={connectionMap}
            meta={agentCards}
            onChange={updateAgent}
            onTest={(agent) => void testConnection(agent)}
          />
        </div>
      ) : null}
    </main>
  );
}
