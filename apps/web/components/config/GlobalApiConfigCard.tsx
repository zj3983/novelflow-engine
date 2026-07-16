import type { CodexCLIInfo, RuntimeSettings } from "../../lib/api";

type Props = {
  value: RuntimeSettings;
  cliInfo: CodexCLIInfo | null;
  onChange: (next: RuntimeSettings) => void;
};

export function GlobalApiConfigCard({ value, cliInfo, onChange }: Props) {
  const selected = value.providers[value.provider];
  const updateLabel =
    cliInfo?.update_status === "current"
      ? "已是最新版"
      : cliInfo?.update_status === "available"
        ? `有新版本 ${cliInfo.latest_version}`
        : "暂时无法检查更新";

  function updateSelected(patch: Partial<typeof selected>) {
    onChange({
      ...value,
      providers: {
        ...value.providers,
        [value.provider]: { ...selected, ...patch },
      },
    });
  }

  return (
    <section className="config-card config-card--spacious" aria-label="模型运行方式">
      <div className="config-card__header">
        <h2 className="config-card__title">模型运行方式</h2>
      </div>

      <div className="config-stack">
        <div className="field">
          <label htmlFor="config-global-provider">模型来源</label>
          <select
            id="config-global-provider"
            aria-label="模型来源"
            className="text-input"
            value={value.provider}
            onChange={(event) => onChange({ ...value, provider: event.target.value as RuntimeSettings["provider"] })}
          >
            <option value="codexcli">Codex CLI</option>
            <option value="openai">OpenAI 兼容 API</option>
          </select>
        </div>

        {value.provider === "codexcli" ? (
          <div className="config-grid config-grid--two-up">
            <div className="field">
              <label htmlFor="config-global-codex-command">Codex CLI 命令</label>
              <input
                id="config-global-codex-command"
                aria-label="Codex CLI 命令"
                className="text-input"
                value={selected.codex_command}
                onChange={(event) => updateSelected({ codex_command: event.target.value })}
                placeholder="codex"
              />
            </div>
            <div className="field">
              <label>CLI 版本</label>
              <div className="config-readonly" aria-label="CLI 版本">
                <span>{cliInfo?.available ? cliInfo.version : "未检测到"}</span>
                <span
                  className={`runtime-status__badge runtime-status__badge--${
                    cliInfo?.update_status === "current"
                      ? "success"
                      : cliInfo?.update_status === "available"
                        ? "warning"
                        : "idle"
                  }`}
                >
                  {updateLabel}
                </span>
              </div>
            </div>
          </div>
        ) : (
          <div className="config-grid config-grid--two-up">
            <div className="field">
              <label htmlFor="config-global-api-key">全局 API 密钥</label>
              <input
                id="config-global-api-key"
                aria-label="全局 API 密钥"
                type="password"
                className="text-input"
                value={selected.api_key}
                onChange={(event) => updateSelected({ api_key: event.target.value })}
              />
            </div>
            <div className="field">
              <label htmlFor="config-global-base-url">全局接口地址</label>
              <input
                id="config-global-base-url"
                aria-label="全局接口地址"
                className="text-input"
                value={selected.base_url}
                onChange={(event) => updateSelected({ base_url: event.target.value })}
              />
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
