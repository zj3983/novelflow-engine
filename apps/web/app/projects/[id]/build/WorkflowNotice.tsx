import type { ReactNode } from "react";
import type { ProductStatus } from "./product-api";
import styles from "./workflow.module.css";

export function WorkflowNotice({ status, title, children }: { status: ProductStatus; title: string; children?: ReactNode }) {
  return <section className={`${styles.notice} ${styles[status.tone]}`} aria-label={title} aria-live="polite">
    <div className={styles.heading}><strong>{title}</strong><span>{status.label}</span></div>
    <p>{status.message}</p>
    {status.impact ? <p>{status.impact}</p> : null}
    {children}
  </section>;
}
