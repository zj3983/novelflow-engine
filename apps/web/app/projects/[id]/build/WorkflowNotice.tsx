import type { ReactNode } from "react";
import styles from "./workflow.module.css";

const labels: Record<string, string> = {
  pending: "待生成", ready: "待执行", running: "进行中", stale: "已过期",
  blocked: "受阻", failed: "失败", validation_failed: "校验失败",
  review_required: "待审核", warning: "有警告", confirmed: "已确认", completed: "已完成",
};

export function WorkflowNotice({ status, title, children }: { status: string; title: string; children?: ReactNode }) {
  const tone = ["blocked", "failed", "validation_failed"].includes(status) ? "danger"
    : ["warning", "stale", "review_required"].includes(status) ? "warning"
      : ["confirmed", "completed"].includes(status) ? "success" : "neutral";
  return <section className={`${styles.notice} ${styles[tone]}`} aria-label={title} aria-live="polite">
    <div className={styles.heading}><strong>{title}</strong><span>{labels[status] ?? status}</span></div>
    {children}
  </section>;
}
