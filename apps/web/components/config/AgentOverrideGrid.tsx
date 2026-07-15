import type { RuntimeSettingsSnapshot } from "./types";
import { AgentConfigCard } from "./AgentConfigCard";

export type AgentOverrideMeta = {
  key: keyof RuntimeSettingsSnapshot["agents"];
  label: string;
  modelName: string;
};

type AgentOverrideGridProps = {
  agents: RuntimeSettingsSnapshot["agents"];
  inherited: RuntimeSettingsSnapshot["global"];
  statuses: Record<
    keyof RuntimeSettingsSnapshot["agents"],
    {
      state: "idle" | "testing" | "success" | "error";
      message: string;
    }
  >;
  onChange: (agent: keyof RuntimeSettingsSnapshot["agents"], next: RuntimeSettingsSnapshot["agents"][keyof RuntimeSettingsSnapshot["agents"]]) => void;
  onTest: (agent: keyof RuntimeSettingsSnapshot["agents"]) => void;
  meta: AgentOverrideMeta[];
};

export function AgentOverrideGrid({
  agents,
  inherited,
  statuses,
  onChange,
  onTest,
  meta,
}: AgentOverrideGridProps) {
  return (
    <details className="config-card config-card--grid config-advanced" aria-label="Agent 独立覆盖">
      <summary className="config-advanced__summary" role="button" aria-label="Agent 覆盖（高级）">
        <span>
          <span className="config-card__title">Agent 覆盖（高级）</span>
          <span className="config-card__subtitle">只在单个 Agent 需要不同 API 时使用。</span>
        </span>
        <span className="config-advanced__chevron" aria-hidden="true">展开</span>
      </summary>

      <div className="config-grid">
        {meta.map(({ key, label, modelName }) => (
          <AgentConfigCard
            key={key}
            label={label}
            value={agents[key]}
            inherited={inherited}
            status={statuses[key].state}
            statusMessage={statuses[key].message}
            modelName={modelName}
            onChange={(next) => onChange(key, next)}
            onTest={() => onTest(key)}
          />
        ))}
      </div>
    </details>
  );
}
