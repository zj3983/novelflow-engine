import { useState } from "react";

import { BookImportPanel } from "./BookImportPanel";
import type { BookImportBootstrapResponse } from "../lib/api";

export type StoryCharacterDraft = {
  name: string;
  goal: string;
  frozen: boolean;
  relationshipTarget: string;
  relationshipBond: string;
  trust: string;
  tension: string;
};

export type StoryDraft = {
  outline: string;
  characters: StoryCharacterDraft[];
};

export type RuntimeEndpoint = {
  apiKey: string;
  baseUrl: string;
};

export type AgentRuntimeName = "character" | "director" | "writer" | "memory";
export type RuntimeConnectionTarget = "global" | AgentRuntimeName;

export type RuntimeSettings = {
  global: RuntimeEndpoint;
  agents: Record<AgentRuntimeName, RuntimeEndpoint>;
};

export type AgentMode = "Rule-based" | "LLM-assisted";

export type NewCharacterPolicy = "Director review" | "Auto-approve named candidates" | "Manual review";

export type AgentSettings = {
  mode: AgentMode;
  globalModel: string;
  characterModel: string;
  directorModel: string;
  writerModel: string;
  memoryModel: string;
  temperature: string;
  newCharacterPolicy: NewCharacterPolicy;
};

type StorySidebarProps = {
  draft: StoryDraft;
  agentSettings: AgentSettings;
  runtimeSettings: RuntimeSettings;
  runtimeSettingsStatus: "idle" | "saved" | "error";
  runtimeConnectionStatus: Record<
    RuntimeConnectionTarget,
    { state: "idle" | "testing" | "success" | "error"; message: string }
  >;
  onChange: (next: StoryDraft) => void;
  onAgentSettingsChange: (next: AgentSettings) => void;
  onRuntimeSettingsChange: (next: RuntimeSettings) => void;
  onSaveRuntimeSettings: () => void;
  onTestRuntimeSettings: (target: RuntimeConnectionTarget) => void;
};

export function StorySidebar({
  draft,
  agentSettings,
  runtimeSettings,
  runtimeSettingsStatus,
  runtimeConnectionStatus,
  onChange,
  onAgentSettingsChange,
  onRuntimeSettingsChange,
  onSaveRuntimeSettings,
  onTestRuntimeSettings,
}: StorySidebarProps) {
  const [isRuntimeSettingsOpen, setIsRuntimeSettingsOpen] = useState(true);
  const [isAgentSettingsOpen, setIsAgentSettingsOpen] = useState(true);
  const AGENT_RUNTIME_LABELS: Record<AgentRuntimeName, string> = {
    character: "角色代理",
    director: "导演代理",
    writer: "写作代理",
    memory: "记忆代理",
  };
  const runtimeMode =
    agentSettings.mode === "LLM-assisted"
      ? "LLM 协助模式，失败时自动回退到规则路径"
      : "纯规则模式";
  const agentRuntimeLabel =
    agentSettings.mode === "LLM-assisted" ? "LLM 协助模式" : "纯规则模式";

  function updateCharacter(index: number, next: StoryCharacterDraft) {
    const characters = draft.characters.map((character, currentIndex) =>
      currentIndex === index ? next : character,
    );
    onChange({ ...draft, characters });
  }

  function updateAgentSettings(next: Partial<AgentSettings>) {
    onAgentSettingsChange({ ...agentSettings, ...next });
  }

  function modeLabel(mode: AgentMode): string {
    return mode === "LLM-assisted" ? "LLM 协助模式" : "纯规则模式";
  }

  function policyLabel(policy: NewCharacterPolicy): string {
    if (policy === "Auto-approve named candidates") {
      return "自动通过命名候选";
    }
    if (policy === "Manual review") {
      return "手动审核";
    }
    return "导演审核";
  }

  function runtimeBadgeTone(state: "idle" | "testing" | "success" | "error"): string {
    if (state === "testing") {
      return "warning";
    }
    if (state === "success") {
      return "success";
    }
    if (state === "error") {
      return "error";
    }
    return "idle";
  }

  function addCharacter() {
    onChange({
      ...draft,
      characters: [
        ...draft.characters,
        {
          name: "",
          goal: "",
          frozen: false,
          relationshipTarget: "",
          relationshipBond: "",
          trust: "0.0",
          tension: "0.0",
        },
      ],
    });
  }

  function updateRuntimeSettings(next: Partial<RuntimeSettings>) {
    onRuntimeSettingsChange({
      global: next.global ? { ...runtimeSettings.global, ...next.global } : runtimeSettings.global,
      agents: next.agents ? { ...runtimeSettings.agents, ...next.agents } : runtimeSettings.agents,
    });
  }

  function onBootstrapDraft(payload: BookImportBootstrapResponse["draft"]) {
    const nextCharacters = (payload.characters ?? []).length
      ? payload.characters.map((name) => ({
          name,
          goal: "待补全",
          frozen: false,
          relationshipTarget: "",
          relationshipBond: "",
          trust: "0.0",
          tension: "0.0",
        }))
      : draft.characters;

    onChange({
      ...draft,
      outline: payload.outline ?? draft.outline,
      characters: nextCharacters.length ? nextCharacters : draft.characters,
    });
  }

  return (
    <div className="sidebar-fields">
      <BookImportPanel onBootstrapDraft={onBootstrapDraft} />

      <section className="agent-settings">
        <button
          className="agent-settings__toggle"
          type="button"
          onClick={() => setIsRuntimeSettingsOpen((value) => !value)}
          aria-expanded={isRuntimeSettingsOpen}
        >
          API 配置
        </button>
        {isRuntimeSettingsOpen ? (
          <div className="agent-settings__body">
            <p className="hint" style={{ marginBottom: 10 }}>
              这里保存的是全局默认 API。下面每个代理都可以单独覆盖，留空则回退全局默认。
            </p>
            <div className="field">
              <label htmlFor="runtime-global-api-key">全局 API 密钥</label>
              <input
                id="runtime-global-api-key"
                aria-label="OpenAI API Key"
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
                aria-label="OpenAI Base URL"
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
              aria-label="全局 API 测试连接"
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
                  : runtimeConnectionStatus.global.message ||
                    "点一下测试，确认全局默认 API 是否可用。"}
              </span>
            </p>

            <div className="agent-settings__summary" aria-label="Agent Runtime Overrides">
              <p className="hint">下面这些字段只覆盖对应代理；留空时会自动使用全局默认。</p>
            </div>

            <div className="agent-settings__grid">
              {(Object.entries(AGENT_RUNTIME_LABELS) as Array<[AgentRuntimeName, string]>).map(
                ([agentKey, agentLabel]) => (
                  <section className="character-card" key={agentKey}>
                    <p className="character-card__title">{agentLabel} API</p>
                    <p className="hint">留空则回退到全局默认。</p>

                    <div className="field">
                      <label htmlFor={`runtime-${agentKey}-api-key`}>{agentLabel} API 密钥</label>
                      <input
                        id={`runtime-${agentKey}-api-key`}
                        aria-label={`${agentLabel} API Key`}
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
                        aria-label={`${agentLabel} Base URL`}
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
                          ? "正在测试连接..."
                          : runtimeConnectionStatus[agentKey].message ||
                            "点一下测试，确认这组专属 API 是否可用。"}
                      </span>
                    </p>
                  </section>
                ),
              )}
            </div>

            <button className="btn btn--ghost" type="button" onClick={onSaveRuntimeSettings}>
              保存 API 配置
            </button>

            <p className="hint">
              {runtimeSettingsStatus === "saved"
                ? "API 配置已保存"
                : runtimeSettingsStatus === "error"
                  ? "API 配置保存失败"
                  : "保存后会立即影响后端的 LLM 协助模式。"}
            </p>
          </div>
        ) : null}
      </section>

      <section className="agent-settings">
        <button
          className="agent-settings__toggle"
          type="button"
          onClick={() => setIsAgentSettingsOpen((value) => !value)}
          aria-expanded={isAgentSettingsOpen}
        >
          代理设置
        </button>
        {isAgentSettingsOpen ? (
          <div className="agent-settings__body">
            <p className="hint" style={{ marginBottom: 10 }}>
              模型配置：这里可以直接填写角色、导演、写作所用的模型名。
            </p>
            <div className="agent-settings__grid">
              <div className="field">
                <label htmlFor="agent-mode">代理模式</label>
                <select
                  id="agent-mode"
                  aria-label="Agent Mode"
                  className="text-input"
                  value={agentSettings.mode}
                  onChange={(event) =>
                    updateAgentSettings({
                      mode: event.target.value as AgentMode,
                    })
                  }
                >
                  <option value="Rule-based">纯规则模式</option>
                  <option value="LLM-assisted">LLM 协助模式</option>
                  </select>
              </div>

              <div className="field">
                <label htmlFor="new-character-policy">新角色策略</label>
                <select
                  id="new-character-policy"
                  aria-label="New Character Policy"
                  className="text-input"
                  value={agentSettings.newCharacterPolicy}
                  onChange={(event) =>
                    updateAgentSettings({
                      newCharacterPolicy: event.target.value as NewCharacterPolicy,
                    })
                  }
                >
                  <option value="Director review">导演审核</option>
                  <option value="Auto-approve named candidates">自动通过命名候选</option>
                  <option value="Manual review">手动审核</option>
                </select>
              </div>
            </div>

            <div className="field">
              <label htmlFor="global-model">全局默认模型</label>
              <input
                id="global-model"
                aria-label="全局默认模型"
                className="text-input"
                value={agentSettings.globalModel}
                onChange={(event) =>
                  updateAgentSettings({ globalModel: event.target.value })
                }
              />
            </div>

            <div className="field">
              <label htmlFor="character-model">角色模型</label>
              <input
                id="character-model"
                aria-label="Character Model"
                className="text-input"
                value={agentSettings.characterModel}
                onChange={(event) =>
                  updateAgentSettings({ characterModel: event.target.value })
                }
              />
            </div>

            <div className="field">
              <label htmlFor="director-model">导演模型</label>
              <input
                id="director-model"
                aria-label="Director Model"
                className="text-input"
                value={agentSettings.directorModel}
                onChange={(event) =>
                  updateAgentSettings({ directorModel: event.target.value })
                }
              />
            </div>

            <div className="field">
              <label htmlFor="writer-model">写作模型</label>
              <input
                id="writer-model"
                aria-label="Writer Model"
                className="text-input"
                value={agentSettings.writerModel}
                onChange={(event) =>
                  updateAgentSettings({ writerModel: event.target.value })
                }
                />
            </div>

            <div className="field">
              <label htmlFor="memory-model">记忆代理模型</label>
              <input
                id="memory-model"
                aria-label="Memory Model"
                className="text-input"
                value={agentSettings.memoryModel}
                onChange={(event) =>
                  updateAgentSettings({ memoryModel: event.target.value })
                }
              />
            </div>

            <div className="field">
              <label htmlFor="agent-temperature">温度</label>
              <input
                id="agent-temperature"
                aria-label="Temperature"
                className="text-input"
                inputMode="decimal"
                value={agentSettings.temperature}
                onChange={(event) =>
                  updateAgentSettings({ temperature: event.target.value })
                }
              />
            </div>

            <div className="agent-settings__summary" aria-label="Agent Settings Summary">
              <p className="hint">模式：{modeLabel(agentSettings.mode)}</p>
              <p className="hint">角色模型：{agentSettings.characterModel}</p>
              <p className="hint">导演模型：{agentSettings.directorModel}</p>
              <p className="hint">写作模型：{agentSettings.writerModel}</p>
              <p className="hint">记忆模型：{agentSettings.memoryModel}</p>
              <p className="hint">温度：{agentSettings.temperature}</p>
              <p className="hint">新角色策略：{policyLabel(agentSettings.newCharacterPolicy)}</p>
            </div>

            <div className="agent-settings__summary" aria-label="Agent Runtime Status">
              <p className="hint">运行状态</p>
              <p className="hint">运行模式：{runtimeMode}</p>
              <p className="hint">角色代理：{agentRuntimeLabel}</p>
              <p className="hint">导演代理：{agentRuntimeLabel}</p>
              <p className="hint">写作代理：{agentRuntimeLabel}</p>
              <p className="hint">记忆代理：{agentRuntimeLabel}</p>
            </div>
          </div>
        ) : null}
      </section>

      <div className="field">
        <label htmlFor="outline-input">大纲输入</label>
        <textarea
          id="outline-input"
          aria-label="Outline Input"
          placeholder="把你的小说大纲贴在这里。"
          value={draft.outline}
          onChange={(event) => onChange({ ...draft, outline: event.target.value })}
        />
      </div>

      {draft.characters.map((character, index) => (
        <section className="character-card" key={index}>
          <p className="character-card__title">角色 {index + 1}</p>

          <div className="field">
            <label htmlFor={`character-name-${index}`}>角色名称 {index + 1}</label>
            <input
              id={`character-name-${index}`}
              aria-label={`Character Name ${index + 1}`}
              className="text-input"
              value={character.name}
              onChange={(event) =>
                updateCharacter(index, { ...character, name: event.target.value })
              }
            />
          </div>

          <div className="field">
            <label htmlFor={`character-goal-${index}`}>角色目标 {index + 1}</label>
            <input
              id={`character-goal-${index}`}
              aria-label={`Character Goal ${index + 1}`}
              className="text-input"
              value={character.goal}
              onChange={(event) =>
                updateCharacter(index, { ...character, goal: event.target.value })
              }
            />
          </div>

          <label className="checkbox-row" htmlFor={`freeze-character-${index}`}>
            <input
              id={`freeze-character-${index}`}
              aria-label={index === 0 ? "Freeze Character" : `Freeze Character ${index + 1}`}
              type="checkbox"
              checked={character.frozen}
              onChange={(event) =>
                updateCharacter(index, { ...character, frozen: event.target.checked })
              }
            />
            <span>冻结角色</span>
          </label>

          <div className="field">
            <label htmlFor={`relationship-target-${index}`}>关系对象 {index + 1}</label>
            <input
              id={`relationship-target-${index}`}
              aria-label={`Relationship Target ${index + 1}`}
              className="text-input"
              value={character.relationshipTarget}
              onChange={(event) =>
                updateCharacter(index, { ...character, relationshipTarget: event.target.value })
              }
            />
          </div>

          <div className="field">
            <label htmlFor={`relationship-bond-${index}`}>关系类型 {index + 1}</label>
            <input
              id={`relationship-bond-${index}`}
              aria-label={`Relationship Bond ${index + 1}`}
              className="text-input"
              value={character.relationshipBond}
              onChange={(event) =>
                updateCharacter(index, { ...character, relationshipBond: event.target.value })
              }
            />
          </div>

          <div className="field-row">
            <div className="field">
              <label htmlFor={`trust-level-${index}`}>信任值 {index + 1}</label>
              <input
                id={`trust-level-${index}`}
                aria-label={`Trust Level ${index + 1}`}
                className="text-input"
                value={character.trust}
                onChange={(event) =>
                  updateCharacter(index, { ...character, trust: event.target.value })
                }
              />
            </div>

            <div className="field">
              <label htmlFor={`tension-level-${index}`}>紧张值 {index + 1}</label>
              <input
                id={`tension-level-${index}`}
                aria-label={`Tension Level ${index + 1}`}
                className="text-input"
                value={character.tension}
                onChange={(event) =>
                  updateCharacter(index, { ...character, tension: event.target.value })
                }
              />
            </div>
          </div>
        </section>
      ))}

      <button className="btn btn--ghost" type="button" onClick={addCharacter}>
        添加角色
      </button>

      <p className="hint">
        冻结角色会保留当前情绪、位置和记忆不变，但剧情仍会继续围绕他们推进。
      </p>
    </div>
  );
}
