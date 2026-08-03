import type { PowerSystemSpec } from "../../lib/api";
import styles from "./StructuredPowerSystem.module.css";

type UnknownRecord = Record<string, unknown>;

const GAME_POWER_LABELS = {
  pathsTitle: "职业与路线",
  role: "职责",
  weapons: "武器",
  armor: "护甲",
  skillCategories: "技能类别",
  combatLoop: "战斗循环",
  transferTask: "转职任务",
  pathAdvancement: "晋升",
  skillsAndEquipmentTitle: "技能与装备",
  skills: "技能",
  equipment: "装备",
  stageLevel: "等级",
  continuityTitle: "连续性账本",
};

const XIANXIA_POWER_LABELS: typeof GAME_POWER_LABELS = {
  pathsTitle: "修炼道路",
  role: "道路定位",
  weapons: "常用手段",
  armor: "防护手段",
  skillCategories: "术法与能力",
  combatLoop: "斗法方式",
  transferTask: "立道条件",
  pathAdvancement: "修炼路径",
  skillsAndEquipmentTitle: "术法与器物",
  skills: "术法与能力",
  equipment: "法宝与器物",
  stageLevel: "阶段序位",
  continuityTitle: "连续性记录",
};

export function structuredPowerLabels(genrePluginIds: unknown) {
  const ids = Array.isArray(genrePluginIds)
    ? genrePluginIds.map((id) => String(id).trim().toLowerCase())
    : [];
  return ids.includes("xianxia") ? XIANXIA_POWER_LABELS : GAME_POWER_LABELS;
}

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

function isIntegerInRange(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= minimum && value <= maximum;
}

function baseAttributes(value: unknown): Array<[string, number]> | null {
  if (!isRecord(value)) return null;
  const entries = Object.entries(value);
  if (entries.length < 1 || entries.length > 16) return null;
  const result: Array<[string, number]> = [];
  for (const [name, points] of entries) {
    if (!text(name) || !isIntegerInRange(points, 0, 10_000)) {
      return null;
    }
    result.push([name, points]);
  }
  return result;
}

function attributeAllocation(value: unknown): UnknownRecord | null {
  if (!isRecord(value) || text(value.mode).toLowerCase() !== "free") return null;
  if (!isIntegerInRange(value.points_per_level, 1, 100)) {
    return null;
  }
  if (!isIntegerInRange(value.starting_level, 1, 1_000_000)) {
    return null;
  }
  if (baseAttributes(value.base_attributes) === null) return null;
  if (typeof value.allow_carry !== "boolean" || !text(value.respec_rule)) return null;
  return value;
}

function isGameGenre(genrePluginIds: unknown) {
  return Array.isArray(genrePluginIds)
    && genrePluginIds.some((id) => String(id).trim().toLowerCase() === "game_webnovel");
}

function hasCompleteGameAdvancement(value: UnknownRecord, paths: UnknownRecord[]) {
  const expected = [10, 30, 60];
  const tiers = recordList(value.class_advancement_tiers);
  if (tiers.length !== expected.length || tiers.some((tier, index) => (
    tier.level !== expected[index]
    || !text(tier.name)
    || !text(tier.purpose)
    || !text(tier.failure_rule)
    || textList(tier.common_requirements).length === 0
  ))) return false;

  return paths.every((path) => {
    const nodes = recordList(path.advancement_tree);
    return nodes.length === expected.length && nodes.every((node, index) => {
      const choices = recordList(node.options);
      return node.level === expected[index]
        && text(node.tier_name).length > 0
        && choices.length > 0
        && choices.every((choice) => (
          text(choice.name).length > 0
          && text(choice.transfer_task).length > 0
          && textList(choice.ability_changes).length > 0
        ));
    });
  });
}

export function hasStructuredPowerSystem(value: unknown, genrePluginIds: unknown = []): value is PowerSystemSpec {
  if (!hasPowerSystemDraft(value) || !text(value.name)) return false;

  const attributes = recordList(value.attributes);
  const stages = recordList(value.stages);
  const paths = recordList(value.paths);
  const requiredLists = [
    "origin", "skills", "equipment", "resources", "advancement", "costs",
    "counters", "boundaries", "social_impact", "visibility", "continuity_ledger",
  ];
  const baseComplete = attributes.length > 0
    && attributes.every((attribute) => text(attribute.name) && text(attribute.effect))
    && stages.length >= 3
    && stages.every((stage) => text(stage.name) && text(stage.entry) && text(stage.change) && text(stage.failure))
    && paths.length >= 2
    && paths.every((path) => text(path.name) && new Set(textList(path.branches).map((branch) => branch.toLocaleLowerCase())).size >= 2)
    && textList(value.continuity_ledger).length >= 4
    && requiredLists.every((field) => textList(value[field]).length > 0);
  return baseComplete && (!isGameGenre(genrePluginIds) || hasCompleteGameAdvancement(value, paths));
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

function ClassAdvancementTree({ spec }: { spec: PowerSystemSpec }) {
  const tiers = recordList(spec.class_advancement_tiers);
  const paths = recordList(spec.paths);
  if (!tiers.length) return null;
  return (
    <section className={styles.classTree} aria-label="职业转职树">
      <h3>职业转职树</h3>
      <div className={styles.tierList}>
        {tiers.map((tier) => {
          const level = typeof tier.level === "number" ? tier.level : 0;
          return (
            <section className={styles.tier} key={level}>
              <div className={styles.tierHead}>
                <h4>{`Lv.${level} ${text(tier.name)}`}</h4>
                <p>{text(tier.purpose)}</p>
              </div>
              <dl className={styles.tierRules}>
                <Detail label="共通条件" value={tier.common_requirements} />
                <Detail label="失败规则" value={tier.failure_rule} />
              </dl>
              <div className={styles.tierPaths}>
                {paths.map((path) => {
                  const node = recordList(path.advancement_tree).find((item) => item.level === level);
                  if (!node) return null;
                  return (
                    <section className={styles.tierPath} key={`${level}-${text(path.name)}`}>
                      <h5>{text(path.name)}</h5>
                      {recordList(node.options).map((option) => (
                        <div className={styles.classOption} key={`${level}-${text(path.name)}-${text(option.name)}`}>
                          <strong>{text(option.name)}</strong>
                          <dl className={styles.details}>
                            <Detail label="定位" value={option.role} />
                            <Detail label="前置条件" value={option.requirements} />
                            <Detail label="转职任务" value={option.transfer_task} />
                            <Detail label="能力变化" value={option.ability_changes} />
                            <Detail label="新增资源" value={option.new_resources} />
                            <Detail label="装备权限" value={option.equipment_permissions} />
                            <Detail label="失败后果" value={option.failure_consequence} />
                            <Detail label="后续去向" value={option.next_options} />
                          </dl>
                        </div>
                      ))}
                    </section>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
    </section>
  );
}

export function StructuredPowerSystem({ spec, genrePluginIds = [] }: { spec: unknown; genrePluginIds?: unknown }) {
  if (!hasStructuredPowerSystem(spec, genrePluginIds)) return null;

  const stages = recordList(spec.stages);
  const paths = recordList(spec.paths);
  const attributes = recordList(spec.attributes);
  const allocation = attributeAllocation(spec.attribute_allocation);
  const baseAttributeValues = allocation ? baseAttributes(allocation.base_attributes) ?? [] : [];
  const labels = structuredPowerLabels(genrePluginIds);

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

      {allocation ? (
        <Section title="属性分配">
          <dl className={styles.details}>
            <Detail label="模式" value="自由分配" />
            <Detail label="每级点数" value={typeof allocation.points_per_level === "number" ? String(allocation.points_per_level) : ""} />
            <Detail label="起始等级" value={typeof allocation.starting_level === "number" ? String(allocation.starting_level) : ""} />
            <Detail label="允许保留" value={typeof allocation.allow_carry === "boolean" ? (allocation.allow_carry ? "是" : "否") : ""} />
            <Detail label="洗点规则" value={allocation.respec_rule} />
          </dl>
          {baseAttributeValues.length ? (
            <div className={styles.subsection}>
              <h4>初始值</h4>
              <dl className={styles.attributeGrid}>
                {baseAttributeValues.map(([name, points]) => (
                  <div className={styles.attribute} key={name}>
                    <dt>{name}</dt>
                    <dd>{points}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : null}
        </Section>
      ) : null}

      <Section title="阶段与晋升">
        {stages.length ? (
          <ol className={styles.stageList}>
            {stages.map((stage, index) => (
              <li key={`${text(stage.name)}-${index}`}>
                <strong>{text(stage.name) || `阶段 ${index + 1}`}</strong>
                <dl className={styles.details}>
                  <Detail label={labels.stageLevel} value={typeof stage.level === "number" ? String(stage.level) : stage.level} />
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

      {isGameGenre(genrePluginIds) ? <ClassAdvancementTree spec={spec} /> : null}

      <Section title={labels.pathsTitle}>
        {paths.length ? (
          <div className={styles.pathGrid}>
            {paths.map((path, index) => (
              <section className={styles.path} key={`${text(path.name)}-${index}`}>
                <h4>{text(path.name) || `路线 ${index + 1}`}</h4>
                <dl className={styles.details}>
                  <Detail label={labels.role} value={path.role} />
                  <Detail label="核心资源" value={path.core_resource} />
                  <Detail label="核心属性" value={path.core_attributes} />
                  <Detail label={labels.weapons} value={path.weapons} />
                  <Detail label={labels.armor} value={path.armor} />
                  <Detail label={labels.skillCategories} value={path.skill_categories} />
                  <Detail label={labels.combatLoop} value={path.combat_loop} />
                  <Detail label="强项" value={path.strengths} />
                  <Detail label="弱项" value={path.weaknesses} />
                  <Branches value={path.branches} />
                  <Detail label={labels.transferTask} value={path.transfer_task} />
                  <Detail label={labels.pathAdvancement} value={path.advancement} />
                </dl>
              </section>
            ))}
          </div>
        ) : <p className={styles.empty}>暂无路线</p>}
      </Section>

      <Section title={labels.skillsAndEquipmentTitle}>
        <div className={styles.twoColumns}>
          <div><h4>{labels.skills}</h4><TextList items={textList(spec.skills)} /></div>
          <div><h4>{labels.equipment}</h4><TextList items={textList(spec.equipment)} /></div>
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
      <Section title={labels.continuityTitle}><TextList items={textList(spec.continuity_ledger)} /></Section>
    </div>
  );
}
