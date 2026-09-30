"use client";
import Link from "next/link";
import { useState } from "react";
import type { ProductAction, ProductForm, ProductIssue } from "./product-api";
import styles from "./build.module.css";

export type ProductActionHandler = (action: ProductAction, values?: Record<string, string>) => Promise<boolean>;

export function ProductActions({ actions, busy, onAction, values }: { actions: ProductAction[]; busy: boolean; onAction: ProductActionHandler; values?: Record<string, string> }) {
  return <div className={styles.actions}>{actions.map((action) => <div key={action.token || action.href || action.label}>
    {action.href && action.enabled && !busy ? <Link className="ws-btn ws-btn--sm" href={action.href}>{action.label}</Link>
      : <button className="ws-btn ws-btn--sm" type="button" disabled={busy || !action.enabled} onClick={() => void onAction(action, values)}>{action.label}</button>}
    {action.reason ? <p className="ws-card__hint">{action.reason}</p> : null}
  </div>)}</div>;
}

export function ProductIssues({ issues }: { issues: ProductIssue[] }) {
  if (!issues.length) return null;
  const list = <ul className={styles.issues}>{issues.map((issue, index) => <li key={index} className={styles[issue.tone]}>
    <p>{issue.message}</p>{issue.suggestion ? <p>建议：{issue.suggestion}</p> : null}
  </li>)}</ul>;
  return issues.length > 3 ? <details><summary>查看全部审查建议（{issues.length}）</summary>{list}</details> : list;
}

export function ProductEditor({ form, busy, onAction, onDirty }: { form: ProductForm; busy: boolean; onAction: ProductActionHandler; onDirty?: (dirty: boolean) => void }) {
  const initial = Object.fromEntries(form.fields.map((field) => [field.key, field.value]));
  const [values, setValues] = useState<Record<string, string>>(initial);
  const [open, setOpen] = useState(false);
  const apply: ProductActionHandler = async (action) => {
    const successful = await onAction(action, values);
    if (successful) { setOpen(false); onDirty?.(false); }
    return successful;
  };
  return <section className={styles.editor} aria-label={form.title}>
    <button className="ws-btn ws-btn--sm" type="button" disabled={busy || open} onClick={() => { setOpen(true); setValues(initial); onDirty?.(true); }}>{form.title}</button>
    {open ? <div className={styles.fields}>
      {form.description ? <p className="ws-card__hint">{form.description}</p> : null}
      {form.fields.map((field) => <label key={field.key}><span>{field.label}</span>
        {field.type === "textarea" ? <textarea aria-label={field.label} className="ws-textarea" value={values[field.key] ?? ""} required={field.required} onChange={(event) => { setValues({ ...values, [field.key]: event.target.value }); onDirty?.(true); }} />
          : <input aria-label={field.label} className="ws-input" type={field.type} value={values[field.key] ?? ""} required={field.required} onChange={(event) => { setValues({ ...values, [field.key]: event.target.value }); onDirty?.(true); }} />}
      </label>)}
      <ProductActions actions={form.actions} busy={busy} onAction={apply} values={values} />
      <button className="ws-btn ws-btn--sm" type="button" disabled={busy} onClick={() => { setValues(initial); setOpen(false); onDirty?.(false); }}>取消修改</button>
    </div> : null}
  </section>;
}
