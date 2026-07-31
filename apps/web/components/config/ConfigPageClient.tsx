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
import { CoverImageConfigCard } from "./CoverImageConfigCard";
import { GlobalApiConfigCard } from "./GlobalApiConfigCard";
import { RuntimeStrategyCard } from "./RuntimeStrategyCard";
import type { RuntimeConnectionMap } from "./types";

type ImageField = "api_key" | "base_url" | "model";
type ImageValidationErrors = Partial<Record<ImageField, string>>;

function createConnectionMap(): RuntimeConnectionMap {
  return {
    planner: { state: "idle", message: "" },
    writer: { state: "idle", message: "" },
    memory: { state: "idle", message: "" },
  };
}

function validateImageField(settings: RuntimeSettings, field: ImageField): string {
  if (!settings.image.enabled) return "";
  if (field === "base_url") {
    if (!settings.image.base_url.trim()) return "封面图片 API 地址不能为空";
    if (!isHttpUrl(settings.image.base_url)) return "封面图片 API 地址格式不正确";
  }
  if (field === "model" && !settings.image.model.trim()) return "封面图片模型名称不能为空";
  if (field === "api_key" && !settings.image.api_key.trim()) return "封面图片 API 密钥不能为空";
  return "";
}

function validateImageSettings(settings: RuntimeSettings): ImageValidationErrors {
  if (!settings.image.enabled) return {};
  const errors: ImageValidationErrors = {};
  for (const field of ["base_url", "model", "api_key"] as ImageField[]) {
    const error = validateImageField(settings, field);
    if (error) errors[field] = error;
  }
  return errors;
}

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value.trim());
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

export function ConfigPageClient() {
  const [settings, setSettings] = useState<RuntimeSettings>(createDefaultRuntimeSettings());
  const [cliInfo, setCliInfo] = useState<CodexCLIInfo | null>(null);
  const [connections, setConnections] = useState<RuntimeConnectionMap>(createConnectionMap());
  const [imageErrors, setImageErrors] = useState<ImageValidationErrors>({});
  const [pageStatus, setPageStatus] = useState<"loading" | "idle" | "saving" | "success" | "error">("loading");
  const [pageMessage, setPageMessage] = useState("正在载入配置中心...");
  const mounted = useRef(true);
  const busy = pageStatus === "loading" || pageStatus === "saving";

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
    const nextImageErrors = validateImageSettings(settings);
    if (Object.keys(nextImageErrors).length > 0) {
      setImageErrors(nextImageErrors);
      setPageStatus("error");
      setPageMessage("请完善封面图片模型配置后再保存。");
      const firstInvalidField = (["base_url", "model", "api_key"] as ImageField[]).find(
        (field) => Boolean(nextImageErrors[field]),
      );
      window.requestAnimationFrame(() => {
        if (firstInvalidField) document.getElementById(`config-cover-image-${firstInvalidField.replace("_", "-")}`)?.focus();
      });
      return;
    }
    setImageErrors({});
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
    <main className="config-shell" aria-busy={busy}>
      <div className="config-shell__primary">
        <GlobalApiConfigCard value={settings} cliInfo={cliInfo} disabled={busy} onChange={setSettings} />
        <CoverImageConfigCard
          value={settings.image}
          errors={imageErrors}
          disabled={busy}
          onChange={(image, field) => {
            const nextSettings = { ...settings, image };
            if (field) {
              setImageErrors((current) => {
                const next = { ...current };
                const error = validateImageField(nextSettings, field);
                if (error) next[field] = error;
                else delete next[field];
                return next;
              });
            }
            setSettings((current) => ({ ...current, image }));
          }}
        />
        <RuntimeStrategyCard
          value={settings}
          cliModels={cliInfo?.models ?? []}
          statuses={connections}
          disabled={busy}
          onChange={setSettings}
          onTest={(stage) => void testStage(stage)}
        />

        <section className="config-card config-card--spacious" aria-label="统一保存" aria-busy={busy}>
          <div className="config-savebar">
            <button className="btn" type="button" onClick={() => void saveAll()} disabled={busy}>
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
