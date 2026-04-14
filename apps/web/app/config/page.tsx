"use client";

import { useState, useEffect, useRef } from "react";
import { fetchRuntimeSettings, saveRuntimeSettings, testRuntimeSettingsConnection, type RuntimeSettings, type RuntimeConnectionTarget } from "../../lib/api";

type LocalRuntimeSettings = {
  global: {
    apiKey: string;
    baseUrl: string;
  };
  agents: {
    character: {
      apiKey: string;
      baseUrl: string;
    };
    director: {
      apiKey: string;
      baseUrl: string;
    };
    writer: {
      apiKey: string;
      baseUrl: string;
    };
    memory: {
      apiKey: string;
      baseUrl: string;
    };
  };
};

function defaultRuntimeSettings(): LocalRuntimeSettings {
  return {
    global: {
      apiKey: "",
      baseUrl: "https://api.openai.com/v1",
    },
    agents: {
      character: { apiKey: "", baseUrl: "" },
      director: { apiKey: "", baseUrl: "" },
      writer: { apiKey: "", baseUrl: "" },
      memory: { apiKey: "", baseUrl: "" },
    },
  };
}

function fromApiRuntimeSettings(settings: RuntimeSettings | undefined): LocalRuntimeSettings {
  return {
    global: {
      apiKey: settings?.global?.api_key ?? "",
      baseUrl: settings?.global?.base_url ?? "https://api.openai.com/v1",
    },
    agents: {
      character: {
        apiKey: settings?.agents?.character?.api_key ?? "",
        baseUrl: settings?.agents?.character?.base_url ?? "",
      },
      director: {
        apiKey: settings?.agents?.director?.api_key ?? "",
        baseUrl: settings?.agents?.director?.base_url ?? "",
      },
      writer: {
        apiKey: settings?.agents?.writer?.api_key ?? "",
        baseUrl: settings?.agents?.writer?.base_url ?? "",
      },
      memory: {
        apiKey: settings?.agents?.memory?.api_key ?? "",
        baseUrl: settings?.agents?.memory?.base_url ?? "",
      },
    },
  };
}

function toApiRuntimeSettings(settings: LocalRuntimeSettings): RuntimeSettings {
  return {
    global: {
      api_key: settings.global.apiKey,
      base_url: settings.global.baseUrl,
    },
    agents: {
      character: {
        api_key: settings.agents.character.apiKey,
        base_url: settings.agents.character.baseUrl,
      },
      director: {
        api_key: settings.agents.director.apiKey,
        base_url: settings.agents.director.baseUrl,
      },
      writer: {
        api_key: settings.agents.writer.apiKey,
        base_url: settings.agents.writer.baseUrl,
      },
      memory: {
        api_key: settings.agents.memory.apiKey,
        base_url: settings.agents.memory.baseUrl,
      },
    },
  };
}

function runtimeBadgeTone(state: "idle" | "testing" | "success" | "error"): string {
  switch (state) {
    case "success":
      return "success";
    case "error":
      return "error";
    case "testing":
      return "warning";
    case "idle":
    default:
      return "neutral";
  }
}

export default function ConfigPage() {
  const [activeTab, setActiveTab] = useState<string>("api");
  const [runtimeSettings, setRuntimeSettings] = useState<LocalRuntimeSettings>(defaultRuntimeSettings());
  const [runtimeSettingsStatus, setRuntimeSettingsStatus] = useState<"idle" | "loading" | "saving" | "error">("idle");
  const [runtimeConnectionStatus, setRuntimeConnectionStatus] = useState<Record<RuntimeConnectionTarget, { state: "idle" | "testing" | "success" | "error"; message: string }>>({
    global: { state: "idle", message: "" },
    character: { state: "idle", message: "" },
    director: { state: "idle", message: "" },
    writer: { state: "idle", message: "" },
    memory: { state: "idle", message: "" },
  });
  const [isHydrated, setIsHydrated] = useState(false);
  const isMountedRef = useRef(true);

  useEffect(() => {
    setIsHydrated(true);
    void (async () => {
      try {
        const settings = await fetchRuntimeSettings();
        if (isMountedRef.current) {
          setRuntimeSettings(fromApiRuntimeSettings(settings));
        }
      } catch {
        if (isMountedRef.current) {
          setRuntimeSettingsStatus("error");
        }
      }
    })();

    return () => {
      isMountedRef.current = false;
    };
  }, []);

  function updateRuntimeSettings(next: Partial<LocalRuntimeSettings>) {
    setRuntimeSettings((prev) => ({ ...prev, ...next }));
  }

  const onSaveRuntimeSettings = async () => {
    if (!isHydrated) {
      return;
    }

    setRuntimeSettingsStatus("saving");
    try {
      await saveRuntimeSettings(toApiRuntimeSettings(runtimeSettings));
    } catch {
      if (isMountedRef.current) {
        setRuntimeSettingsStatus("error");
      }
    } finally {
      if (isMountedRef.current) {
        setRuntimeSettingsStatus("idle");
      }
    }
  };

  const onTestRuntimeSettings = async (target: RuntimeConnectionTarget) => {
    if (!isHydrated) {
      return;
    }

    setRuntimeConnectionStatus((prev) => ({
      ...prev,
      [target]: { state: "testing", message: "" },
    }));
    try {
      await testRuntimeSettingsConnection(toApiRuntimeSettings(runtimeSettings), target);
      if (isMountedRef.current) {
        setRuntimeConnectionStatus((prev) => ({
          ...prev,
          [target]: { state: "success", message: "连接成功" },
        }));
      }
    } catch (e: any) {
      if (isMountedRef.current) {
        setRuntimeConnectionStatus((prev) => ({
          ...prev,
          [target]: { state: "error", message: e.message ?? "测试失败" },
        }));
      }
    }
  };

  return (
    <div className="config-page">
      <header className="config-header">
        <div className="config-header__nav">
          <a href="/" className="config-header__back-link">
            ← 返回工作台
          </a>
        </div>
        <h1>配置中心</h1>
        <p>管理API配置和代理设置</p>
      </header>

      <div className="config-tabs">
        <button
          className={`config-tab ${activeTab === "api" ? "config-tab--active" : ""}`}
          onClick={() => setActiveTab("api")}
        >
          API 配置
        </button>
        <button
          className={`config-tab ${activeTab === "proxy" ? "config-tab--active" : ""}`}
          onClick={() => setActiveTab("proxy")}
        >
          代理设置
        </button>
        <button
          className={`config-tab ${activeTab === "system" ? "config-tab--active" : ""}`}
          onClick={() => setActiveTab("system")}
        >
          系统设置
        </button>
      </div>

      <main className="config-content">
        {activeTab === "api" && (
          <section className="config-section">
            <h2>API 配置</h2>
            <p className="hint" style={{ marginBottom: 10 }}>
              这里保存的是全局默认 API。下面每个代理都可以单独覆盖，留空则回退到全局默认。
            </p>

            <div className="field">
              <label htmlFor="runtime-global-api-key">全局 API 密钥</label>
              <input
                id="runtime-global-api-key"
                aria-label="全局 API 密钥"
                type="password"
                className="text-input"
                value={runtimeSettings.global.apiKey}
                onChange={(event) =>
                  updateRuntimeSettings({
                    global: { ...runtimeSettings.global, apiKey: event.target.value },
                  })
                }
              />
            </div>

            <div className="field">
              <label htmlFor="runtime-global-base-url">全局接口地址</label>
              <input
                id="runtime-global-base-url"
                aria-label="全局接口地址"
                className="text-input"
                value={runtimeSettings.global.baseUrl}
                onChange={(event) =>
                  updateRuntimeSettings({
                    global: { ...runtimeSettings.global, baseUrl: event.target.value },
                  })
                }
              />
            </div>

            <button
              className="btn btn--ghost"
              type="button"
              aria-label="测试全局连接"
              onClick={() => onTestRuntimeSettings("global")}
            >
              测试全局连接
            </button>
            <p className="hint runtime-status" style={{ marginTop: 8 }}>
              <span
                className={`runtime-status__badge runtime-status__badge--${runtimeBadgeTone(
                  runtimeConnectionStatus.global.state,
                )}`}
              >
                {runtimeConnectionStatus.global.state === "testing"
                  ? "测试中"
                  : runtimeConnectionStatus.global.state === "success"
                    ? "正常"
                    : runtimeConnectionStatus.global.state === "error"
                      ? "失败"
                      : "待测"}
              </span>
              <span className="runtime-status__text">
                {runtimeConnectionStatus.global.state === "testing"
                  ? "正在测试全局连接..."
                  : runtimeConnectionStatus.global.message || "点一下测试，确认全局默认 API 是否可用。"}
              </span>
            </p>

            <div className="config-section__summary" aria-label="代理运行覆盖配置">
              <p className="hint">下面这些字段只覆盖对应代理；留空时会自动使用全局默认。</p>
            </div>

            <div className="config-section__grid">
              {([["character", "角色代理"], ["director", "导演代理"], ["writer", "写作代理"], ["memory", "记忆代理"]] as Array<[keyof LocalRuntimeSettings["agents"], string]>).map(([agentKey, agentLabel]) => (
                <section className="character-card" key={agentKey}>
                  <p className="character-card__title">{agentLabel} API</p>
                  <p className="hint">留空则回退到全局默认。</p>

                  <div className="field">
                    <label htmlFor={`runtime-${agentKey}-api-key`}>{agentLabel} API 密钥</label>
                    <input
                      id={`runtime-${agentKey}-api-key`}
                      aria-label={`${agentLabel} API 密钥`}
                      type="password"
                      className="text-input"
                      value={runtimeSettings.agents[agentKey].apiKey}
                      onChange={(event) =>
                        updateRuntimeSettings({
                          agents: {
                            ...runtimeSettings.agents,
                            [agentKey]: {
                              ...runtimeSettings.agents[agentKey],
                              apiKey: event.target.value,
                            },
                          },
                        })
                      }
                    />
                  </div>

                  <div className="field">
                    <label htmlFor={`runtime-${agentKey}-base-url`}>{agentLabel} 接口地址</label>
                    <input
                      id={`runtime-${agentKey}-base-url`}
                      aria-label={`${agentLabel} 接口地址`}
                      className="text-input"
                      value={runtimeSettings.agents[agentKey].baseUrl}
                      onChange={(event) =>
                        updateRuntimeSettings({
                          agents: {
                            ...runtimeSettings.agents,
                            [agentKey]: {
                              ...runtimeSettings.agents[agentKey],
                              baseUrl: event.target.value,
                            },
                          },
                        })
                      }
                    />
                  </div>

                  <button
                    className="btn btn--ghost"
                    type="button"
                    aria-label={`${agentLabel} 测试连接`}
                    onClick={() => onTestRuntimeSettings(agentKey)}
                  >
                    测试连接
                  </button>
                  <p className="hint runtime-status" style={{ marginTop: 8 }}>
                    <span
                      className={`runtime-status__badge runtime-status__badge--${runtimeBadgeTone(
                        runtimeConnectionStatus[agentKey].state,
                      )}`}
                    >
                      {runtimeConnectionStatus[agentKey].state === "testing"
                        ? "测试中"
                        : runtimeConnectionStatus[agentKey].state === "success"
                          ? "正常"
                          : runtimeConnectionStatus[agentKey].state === "error"
                            ? "失败"
                            : "待测"}
                    </span>
                    <span className="runtime-status__text">
                      {runtimeConnectionStatus[agentKey].state === "testing"
                        ? `正在测试${agentLabel}连接...`
                        : runtimeConnectionStatus[agentKey].message || `点一下测试，确认该代理专用 API 是否可用。`}
                    </span>
                  </p>
                </section>
              ))}
            </div>

            <button className="btn btn--ghost" type="button" onClick={onSaveRuntimeSettings}>
              保存 API 配置
            </button>

            <p className="hint">
              {runtimeSettingsStatus === "saving"
                ? "正在保存 API 配置..."
                : runtimeSettingsStatus === "error"
                  ? "API 配置保存失败"
                  : "保存后会立刻影响后端的 LLM 协助模式。"}
            </p>
          </section>
        )}

        {activeTab === "proxy" && (
          <section className="config-section">
            <h2>代理设置</h2>
            <p className="hint">这里可以配置代理服务器设置，用于连接外部 API。</p>
            <div className="field">
              <label htmlFor="proxy-url">代理服务器 URL</label>
              <input
                id="proxy-url"
                aria-label="代理服务器 URL"
                className="text-input"
                placeholder="例如：http://localhost:7890"
              />
            </div>
            <button className="btn btn--ghost" type="button">
              保存代理设置
            </button>
          </section>
        )}

        {activeTab === "system" && (
          <section className="config-section">
            <h2>系统设置</h2>
            <p className="hint">这里可以配置系统级别的设置。</p>
            <div className="field">
              <label htmlFor="system-language">系统语言</label>
              <select id="system-language" className="text-input">
                <option value="zh-CN">简体中文</option>
                <option value="en-US">English</option>
              </select>
            </div>
            <button className="btn btn--ghost" type="button">
              保存系统设置
            </button>
          </section>
        )}
      </main>
    </div>
  );
}