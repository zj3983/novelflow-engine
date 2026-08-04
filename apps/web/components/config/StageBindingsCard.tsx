import type { RuntimeProviderDefinition, RuntimeSettings, RuntimeStageName } from "../../lib/api";

const STAGES: Array<{ key: RuntimeStageName; label: string; description: string }> = [
  { key: "planner", label: "剧情规划", description: "章节规划、分析和状态提取" },
  { key: "writer", label: "正文写作", description: "正文生成、扩写和改稿" },
];

type Props = {
  value: RuntimeSettings;
  providers: RuntimeProviderDefinition[];
  disabled: boolean;
  onChange: (next: RuntimeSettings) => void;
};

export function StageBindingsCard({ value, providers, disabled, onChange }: Props) {
  function update(stage: RuntimeStageName, patch: Partial<RuntimeSettings["stages"][RuntimeStageName]>) {
    onChange({ ...value, stages: { ...value.stages, [stage]: { ...value.stages[stage], ...patch } } });
  }

  return (
    <section className="config-card config-card--spacious" aria-label="写作阶段模型">
      <div className="config-card__header">
        <div>
          <h2 className="config-card__title">写作阶段模型</h2>
          <p className="config-card__subtitle">规划和正文可以使用不同供应商。状态提取跟随剧情规划，无需独立配置。</p>
        </div>
      </div>
      <div className="config-stage-list">
        {STAGES.map((stage) => {
          const binding = value.stages[stage.key];
          const provider = providers.find((item) => item.provider_id === binding.provider_id) ?? providers[0];
          const account = value.accounts[binding.provider_id];
          const presets = stage.key === "planner" ? provider?.planner_models ?? [] : provider?.writer_models ?? [];
          const models = Array.from(new Set([binding.model, ...presets, ...(account?.custom_models ?? [])].filter(Boolean)));
          return (
            <div className="config-stage-row config-stage-row--binding" key={stage.key}>
              <div className="config-stage-row__label">
                <strong>{stage.label}</strong>
                <span>{stage.description}</span>
              </div>
              <div className="field">
                <label htmlFor={`config-${stage.key}-provider`}>供应商</label>
                <select id={`config-${stage.key}-provider`} aria-label={`${stage.label}供应商`} className="text-input" value={binding.provider_id} disabled={disabled} onChange={(event) => {
                  const nextProvider = providers.find((item) => item.provider_id === event.target.value);
                  const nextModel = (stage.key === "planner" ? nextProvider?.planner_models[0] : nextProvider?.writer_models[0]) ?? value.accounts[event.target.value]?.custom_models[0] ?? "";
                  update(stage.key, { provider_id: event.target.value, model: nextModel });
                }}>
                  {providers.map((item) => <option value={item.provider_id} key={item.provider_id}>{item.name}</option>)}
                </select>
              </div>
              <div className="field">
                <label htmlFor={`config-${stage.key}-model`}>模型</label>
                <select id={`config-${stage.key}-model`} aria-label={`${stage.label}模型`} className="text-input" value={binding.model} disabled={disabled} onChange={(event) => update(stage.key, { model: event.target.value })}>
                  {models.length ? models.map((model) => <option value={model} key={model}>{model}</option>) : <option value="">请先添加自定义模型</option>}
                </select>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
