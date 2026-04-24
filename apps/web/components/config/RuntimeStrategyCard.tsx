import type { RuntimeStrategySettings } from "./types";

type RuntimeStrategyCardProps = {
  value: RuntimeStrategySettings;
  onChange: (next: RuntimeStrategySettings) => void;
};

function updateStrategy(
  current: RuntimeStrategySettings,
  patch: Partial<RuntimeStrategySettings>,
): RuntimeStrategySettings {
  return {
    ...current,
    ...patch,
  };
}

export function RuntimeStrategyCard({ value, onChange }: RuntimeStrategyCardProps) {
  return (
    <section className="config-card config-card--spacious" aria-label="运行策略">
      <div className="config-card__header">
        <div>
          <p className="config-card__eyebrow">运行策略</p>
          <h2 className="config-card__title">运行策略</h2>
        </div>
        <p className="config-card__subtitle">这里只配置 LLM 协助模式下各个代理的模型与新角色审核策略。</p>
      </div>

      <div className="config-stack">
        <div className="config-card__note" aria-label="模式说明">
          <p className="hint">当前仅支持 LLM 协助模式，规则模式已移除。</p>
          <p className="hint">全局模型为空时，会回退到默认值。</p>
        </div>

        <div className="field">
          <label htmlFor="config-global-model">全局默认模型</label>
          <input
            id="config-global-model"
            aria-label="全局默认模型"
            className="text-input"
            value={value.global_model}
            onChange={(event) => onChange(updateStrategy(value, { global_model: event.target.value }))}
          />
        </div>

        <div className="config-grid config-grid--two-up">
          <div className="field">
            <label htmlFor="config-character-model">角色代理模型</label>
            <input
              id="config-character-model"
              aria-label="角色代理模型"
              className="text-input"
              value={value.character_model}
              onChange={(event) => onChange(updateStrategy(value, { character_model: event.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="config-director-model">导演代理模型</label>
            <input
              id="config-director-model"
              aria-label="导演代理模型"
              className="text-input"
              value={value.director_model}
              onChange={(event) => onChange(updateStrategy(value, { director_model: event.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="config-writer-model">写作代理模型</label>
            <input
              id="config-writer-model"
              aria-label="写作代理模型"
              className="text-input"
              value={value.writer_model}
              onChange={(event) => onChange(updateStrategy(value, { writer_model: event.target.value }))}
            />
          </div>
          <div className="field">
            <label htmlFor="config-memory-model">记忆代理模型</label>
            <input
              id="config-memory-model"
              aria-label="记忆代理模型"
              className="text-input"
              value={value.memory_model}
              onChange={(event) => onChange(updateStrategy(value, { memory_model: event.target.value }))}
            />
          </div>
        </div>

        <div className="field">
          <label htmlFor="config-new-character-policy">新角色策略</label>
          <select
            id="config-new-character-policy"
            aria-label="新角色策略"
            className="text-input"
            value={value.new_character_policy}
            onChange={(event) =>
              onChange(
                updateStrategy(value, {
                  new_character_policy: event.target.value as RuntimeStrategySettings["new_character_policy"],
                }),
              )
            }
          >
            <option value="Director review">导演审核</option>
            <option value="Auto-approve named candidates">自动通过具名候选</option>
            <option value="Manual review">人工审核</option>
          </select>
        </div>

        <div className="config-card__note" aria-label="运行策略摘要">
          <p className="hint">模式：LLM 协助模式</p>
          <p className="hint">默认模型：{value.global_model || "未填写"}</p>
          <p className="hint">角色 / 导演 / 写作 / 记忆模型会分别覆盖对应 Agent 的默认值。</p>
          <p className="hint">新角色策略：{value.new_character_policy}</p>
        </div>
      </div>
    </section>
  );
}
