import type { RuntimeSettings, RuntimeStageName } from "../../lib/api";
import type { RuntimeConnectionMap } from "./types";

const STAGES: Array<{ key: RuntimeStageName; label: string; description: string }> = [
  { key: "planner", label: "剧情规划", description: "章节意图、人物行动和事件计划" },
  { key: "writer", label: "正文写作", description: "正文生成、扩写与改稿" },
  { key: "memory", label: "记忆回写", description: "事实、人物变化和未决线索" },
];

type Props = {
  value: RuntimeSettings;
  cliModels: string[];
  statuses: RuntimeConnectionMap;
  onChange: (next: RuntimeSettings) => void;
  onTest: (stage: RuntimeStageName) => void;
};

export function RuntimeStrategyCard({ value, cliModels, statuses, onChange, onTest }: Props) {
  const selected = value.providers[value.provider];

  function updateModel(stage: RuntimeStageName, model: string) {
    onChange({
      ...value,
      providers: {
        ...value.providers,
        [value.provider]: { ...selected, [stage]: model },
      },
    });
  }

  return (
    <section className="config-card config-card--spacious" aria-label="写作阶段模型">
      <div className="config-card__header">
        <h2 className="config-card__title">写作阶段模型</h2>
      </div>
      <div className="config-stage-list">
        {STAGES.map((stage) => {
          const status = statuses[stage.key];
          const currentModel = selected[stage.key];
          const modelOptions = cliModels.includes(currentModel) ? cliModels : [currentModel, ...cliModels];
          return (
            <div className="config-stage-row" key={stage.key}>
              <div className="config-stage-row__label">
                <label htmlFor={`config-${stage.key}-model`}>{stage.label}模型</label>
                <span>{stage.description}</span>
              </div>
              {value.provider === "codexcli" ? (
                <select
                  id={`config-${stage.key}-model`}
                  aria-label={`${stage.label}模型`}
                  className="text-input"
                  value={currentModel}
                  onChange={(event) => updateModel(stage.key, event.target.value)}
                >
                  {modelOptions.map((model) => (
                    <option key={model} value={model}>{model}</option>
                  ))}
                </select>
              ) : (
                <input
                  id={`config-${stage.key}-model`}
                  aria-label={`${stage.label}模型`}
                  className="text-input"
                  value={currentModel}
                  onChange={(event) => updateModel(stage.key, event.target.value)}
                />
              )}
              <button className="btn btn--ghost" type="button" onClick={() => onTest(stage.key)} disabled={status.state === "testing"}>
                测试{stage.label}
              </button>
              <p className="config-status" aria-live="polite">
                <span className={`runtime-status__badge runtime-status__badge--${status.state}`}>
                  {status.state === "idle" ? "待测" : status.state === "testing" ? "测试中" : status.state === "success" ? "正常" : "失败"}
                </span>
                {status.message ? <span className="runtime-status__text">{status.message}</span> : null}
              </p>
            </div>
          );
        })}
      </div>
    </section>
  );
}
