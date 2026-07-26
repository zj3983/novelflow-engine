import type { PowerSystemSpec } from "../../lib/api";
import styles from "./StructuredPowerSystem.module.css";

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function textList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map(text).filter(Boolean);
}

function recordList(value: unknown): UnknownRecord[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

export function hasStructuredPowerSystem(value: unknown): value is PowerSystemSpec {
  if (!hasPowerSystemDraft(value) || !text(value.name)) return false;

  const requiredLists = [
    "origin", "skills", "equipment", "resources", "advancement", "costs",
    "counters", "boundaries", "social_impact", "visibility", "continuity_ledger",
  ];
  return recordList(value.attributes).length > 0
    && recordList(value.stages).length >= 3
    && recordList(value.paths).length > 0
    && requiredLists.every((field) => textList(value[field]).length > 0);
}

export function hasPowerSystemDraft(value: unknown): value is UnknownRecord {
  return isRecord(value) && Object.keys(value).length > 0;
}

function TextList({ items, empty = "暂无" }: { items: string[]; empty?: string }) {
  return items.length ? (
    <ul className={styles.list}>{items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>
  ) : <p className={styles.empty}>{empty}</p>;
}

function Detail({ label, value }: { label: string; value: unknown }) {
  const values = Array.isArray(value) ? textList(value) : [text(value)].filter(Boolean);
  if (!values.length) return null;
  return (
    <div className={styles.detail}>
      <dt>{label}</dt>
      <dd>{values.join("；")}</dd>
    </div>
  );
}

function Branches({ value }: { value: unknown }) {
  const branches = textList(value);
  if (!branches.length) return null;
  return (
    <div className={styles.detail}>
      <dt>分支</dt>
      <dd><TextList items={branches} /></dd>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className={styles.section}>
      <h3>{title}</h3>
      {children}
    </section>
  );
}

export function StructuredPowerSystem({ spec }: { spec: unknown }) {
  if (!hasStructuredPowerSystem(spec)) return null;

  const stages = recordList(spec.stages);
  const paths = recordList(spec.paths);
  const attributes = recordList(spec.attributes);

  return (
    <div className={styles.root} aria-label="结构化力量体系">
      <Section title="体系总览">
        <p className={styles.overview}>{text(spec.name) || "未命名力量体系"}</p>
      </Section>

      <Section title="力量来源"><TextList items={textList(spec.origin)} /></Section>

      <Section title="属性">
        {attributes.length ? (
          <dl className={styles.attributeGrid}>
            {attributes.map((attribute, index) => (
              <div className={styles.attribute} key={`${text(attribute.name)}-${index}`}>
                <dt>{text(attribute.name) || "未命名属性"}</dt>
                <dd>{text(attribute.effect) || "暂无效果说明"}</dd>
              </div>
            ))}
          </dl>
        ) : <p className={styles.empty}>暂无</p>}
      </Section>

      <Section title="阶段与晋升">
        {stages.length ? (
          <ol className={styles.stageList}>
            {stages.map((stage, index) => (
              <li key={`${text(stage.name)}-${index}`}>
                <strong>{text(stage.name) || `阶段 ${index + 1}`}</strong>
                <dl className={styles.details}>
                  <Detail label="等级" value={typeof stage.level === "number" ? String(stage.level) : stage.level} />
                  <Detail label="进入条件" value={stage.entry} />
                  <Detail label="能力变化" value={stage.change} />
                  <Detail label="失败后果" value={stage.failure} />
                </dl>
              </li>
            ))}
          </ol>
        ) : <p className={styles.empty}>暂无阶段</p>}
        <div className={styles.subsection}>
          <h4>晋升规则</h4>
          <TextList items={textList(spec.advancement)} />
        </div>
      </Section>

      <Section title="职业与路线">
        {paths.length ? (
          <div className={styles.pathGrid}>
            {paths.map((path, index) => (
              <section className={styles.path} key={`${text(path.name)}-${index}`}>
                <h4>{text(path.name) || `路线 ${index + 1}`}</h4>
                <dl className={styles.details}>
                  <Detail label="职责" value={path.role} />
                  <Detail label="核心资源" value={path.core_resource} />
                  <Detail label="核心属性" value={path.core_attributes} />
                  <Detail label="武器" value={path.weapons} />
                  <Detail label="护甲" value={path.armor} />
                  <Detail label="技能类别" value={path.skill_categories} />
                  <Detail label="战斗循环" value={path.combat_loop} />
                  <Detail label="强项" value={path.strengths} />
                  <Detail label="弱项" value={path.weaknesses} />
                  <Branches value={path.branches} />
                  <Detail label="转职任务" value={path.transfer_task} />
                  <Detail label="晋升" value={path.advancement} />
                </dl>
              </section>
            ))}
          </div>
        ) : <p className={styles.empty}>暂无路线</p>}
      </Section>

      <Section title="技能与装备">
        <div className={styles.twoColumns}>
          <div><h4>技能</h4><TextList items={textList(spec.skills)} /></div>
          <div><h4>装备</h4><TextList items={textList(spec.equipment)} /></div>
        </div>
      </Section>

      <Section title="资源与代价">
        <div className={styles.twoColumns}>
          <div><h4>资源</h4><TextList items={textList(spec.resources)} /></div>
          <div><h4>代价</h4><TextList items={textList(spec.costs)} /></div>
        </div>
      </Section>

      <Section title="克制与边界">
        <div className={styles.twoColumns}>
          <div><h4>克制</h4><TextList items={textList(spec.counters)} /></div>
          <div><h4>边界</h4><TextList items={textList(spec.boundaries)} /></div>
        </div>
      </Section>

      <Section title="社会影响"><TextList items={textList(spec.social_impact)} /></Section>
      <Section title="信息可见性"><TextList items={textList(spec.visibility)} /></Section>
      <Section title="连续性账本"><TextList items={textList(spec.continuity_ledger)} /></Section>
    </div>
  );
}
