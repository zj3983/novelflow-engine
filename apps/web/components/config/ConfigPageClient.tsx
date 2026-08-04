"use client";

import { useEffect, useRef, useState } from "react";

import {
  createDefaultRuntimeSettings,
  fetchRuntimeProviderCatalog,
  fetchRuntimeSettings,
  saveRuntimeSettings,
  testRuntimeSettingsConnection,
  type RuntimeProviderDefinition,
  type RuntimeSettings,
} from "../../lib/api";
import { CoverImageConfigCard } from "./CoverImageConfigCard";
import { ProviderAccountsCard } from "./ProviderAccountsCard";
import { StageBindingsCard } from "./StageBindingsCard";
import type { RuntimeConnectionMap } from "./types";

type ImageField = "api_key" | "base_url" | "model";
type ImageValidationErrors = Partial<Record<ImageField, string>>;

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value.trim());
    return (url.protocol === "http:" || url.protocol === "https:") && Boolean(url.hostname);
  } catch {
    return false;
  }
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
  const errors: ImageValidationErrors = {};
  for (const field of ["base_url", "model", "api_key"] as ImageField[]) {
    const error = validateImageField(settings, field);
    if (error) errors[field] = error;
  }
  return errors;
}

function validateTextSettings(settings: RuntimeSettings, providers: RuntimeProviderDefinition[]): string {
  for (const stage of ["planner", "writer"] as const) {
    const binding = settings.stages[stage];
    const provider = providers.find((item) => item.provider_id === binding.provider_id);
    const account = settings.accounts[binding.provider_id];
    if (!provider || !account) return `${stage === "planner" ? "剧情规划" : "正文写作"}供应商账号不存在`;
    const error = validateProviderAccount(provider, account, binding.model);
    if (error) return error;
  }
  return "";
}

function validateProviderAccount(
  provider: RuntimeProviderDefinition,
  account: RuntimeSettings["accounts"][string],
  model: string,
): string {
  if (!model.trim()) return `${provider.name} 模型不能为空`;
  if (provider.requires_api_key && !account.api_key.trim()) return `${provider.name} API 密钥不能为空`;
  if (provider.protocol.endsWith("_cli") && !account.codex_command.trim()) return `${provider.name} 命令不能为空`;
  if (!provider.protocol.endsWith("_cli") && !isHttpUrl(account.base_url)) return `${provider.name} API 地址格式不正确`;
  return "";
}

function addMissingProviderAccounts(settings: RuntimeSettings, providers: RuntimeProviderDefinition[]): RuntimeSettings {
  const accounts = { ...settings.accounts };
  for (const provider of providers) {
    if (!accounts[provider.provider_id]) {
      accounts[provider.provider_id] = {
        api_key: "",
        base_url: provider.default_base_url,
        custom_models: [],
        codex_command: provider.protocol === "codex_cli" ? "codex" : provider.protocol === "antigravity_cli" ? "agy" : "",
      };
    }
  }
  return { ...settings, accounts };
}

export function ConfigPageClient() {
  const [settings, setSettings] = useState<RuntimeSettings>(createDefaultRuntimeSettings());
  const [providers, setProviders] = useState<RuntimeProviderDefinition[]>([]);
  const [connections, setConnections] = useState<RuntimeConnectionMap>({});
  const [imageErrors, setImageErrors] = useState<ImageValidationErrors>({});
  const [pageStatus, setPageStatus] = useState<"loading" | "idle" | "saving" | "success" | "error">("loading");
  const [pageMessage, setPageMessage] = useState("正在载入配置中心...");
  const mounted = useRef(true);
  const busy = pageStatus === "loading" || pageStatus === "saving";

  useEffect(() => {
    mounted.current = true;
    void (async () => {
      try {
        const [nextSettings, catalog] = await Promise.all([fetchRuntimeSettings(), fetchRuntimeProviderCatalog()]);
        if (!mounted.current) return;
        setSettings(addMissingProviderAccounts(nextSettings, catalog.providers));
        setProviders(catalog.providers);
        setPageStatus("idle");
        setPageMessage("配置已载入。");
      } catch (error) {
        if (!mounted.current) return;
        setPageStatus("error");
        setPageMessage(error instanceof Error ? error.message : "配置载入失败");
      }
    })();
    return () => { mounted.current = false; };
  }, []);

  async function testProvider(providerId: string, modelOverride?: string) {
    const provider = providers.find((item) => item.provider_id === providerId);
    const account = settings.accounts[providerId] ?? (provider ? { api_key: "", base_url: provider.default_base_url, custom_models: [], codex_command: provider.protocol === "codex_cli" ? "codex" : provider.protocol === "antigravity_cli" ? "agy" : "" } : null);
    if (!provider || !account) return;
    const currentStage = (["planner", "writer"] as const).find((stage) => settings.stages[stage].provider_id === providerId) ?? "planner";
    const model = modelOverride || (settings.stages[currentStage].provider_id === providerId
      ? settings.stages[currentStage].model
      : (provider.planner_models[0] ?? account.custom_models[0] ?? ""));
    const candidate: RuntimeSettings = {
      ...settings,
      accounts: { ...settings.accounts, [providerId]: account },
      stages: { ...settings.stages, [currentStage]: { provider_id: providerId, model } },
    };
    const validation = validateProviderAccount(provider, account, model);
    if (validation) {
      setConnections((current) => ({ ...current, [providerId]: { state: "error", message: validation } }));
      return;
    }
    setConnections((current) => ({ ...current, [providerId]: { state: "testing", message: "" } }));
    try {
      const result = await testRuntimeSettingsConnection(candidate, currentStage);
      if (!mounted.current) return;
      setConnections((current) => ({ ...current, [providerId]: { state: result.ok ? "success" : "error", message: result.message } }));
    } catch (error) {
      if (!mounted.current) return;
      setConnections((current) => ({ ...current, [providerId]: { state: "error", message: error instanceof Error ? error.message : "连接测试失败" } }));
    }
  }

  async function saveAll() {
    const textError = validateTextSettings(settings, providers);
    if (textError) {
      setPageStatus("error");
      setPageMessage(textError);
      return;
    }
    const nextImageErrors = validateImageSettings(settings);
    if (Object.keys(nextImageErrors).length > 0) {
      setImageErrors(nextImageErrors);
      setPageStatus("error");
      setPageMessage("请完善封面图片模型配置后再保存。");
      const first = (["base_url", "model", "api_key"] as ImageField[]).find((field) => Boolean(nextImageErrors[field]));
      window.requestAnimationFrame(() => first && document.getElementById(`config-cover-image-${first.replace("_", "-")}`)?.focus());
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
      setPageMessage("配置已保存，后续任务会使用当前阶段绑定。");
    } catch (error) {
      if (!mounted.current) return;
      setPageStatus("error");
      setPageMessage(error instanceof Error ? error.message : "保存失败");
    }
  }

  return (
    <main className="config-shell" aria-busy={busy}>
      <div className="config-shell__primary">
        <ProviderAccountsCard value={settings} providers={providers} statuses={connections} disabled={busy} onChange={setSettings} onTest={(providerId, model) => void testProvider(providerId, model)} />
        <StageBindingsCard value={settings} providers={providers} disabled={busy} onChange={setSettings} />
        <CoverImageConfigCard
          value={settings.image}
          errors={imageErrors}
          disabled={busy}
          onChange={(image, field) => {
            const next = { ...settings, image };
            if (!image.enabled) setImageErrors({});
            else if (field) setImageErrors((current) => {
              const updated = { ...current };
              const error = validateImageField(next, field);
              if (error) updated[field] = error;
              else delete updated[field];
              return updated;
            });
            setSettings((current) => ({ ...current, image }));
          }}
        />
        <section className="config-card config-card--spacious" aria-label="统一保存">
          <div className="config-savebar">
            <button className="btn" type="button" onClick={() => void saveAll()} disabled={busy}>统一保存</button>
            <p className="config-status" aria-live="polite">
              <span className={`runtime-status__badge runtime-status__badge--${pageStatus === "loading" ? "idle" : pageStatus}`}>{pageStatus === "loading" ? "载入中" : pageStatus === "saving" ? "保存中" : pageStatus === "success" ? "已保存" : pageStatus === "error" ? "失败" : "待保存"}</span>
              <span className="runtime-status__text">{pageMessage}</span>
            </p>
          </div>
        </section>
      </div>
    </main>
  );
}
