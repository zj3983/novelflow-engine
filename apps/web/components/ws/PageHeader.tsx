import Link from "next/link";
import type { ReactNode } from "react";

type Crumb = { label: string; href?: string };

type PageHeaderProps = {
  crumbs?: Crumb[];
  title: string;
  subtitle?: string;
  actions?: ReactNode;
};

export function PageHeader({ crumbs, title, subtitle, actions }: PageHeaderProps) {
  return (
    <header className="ws-page__head">
      <div>
        {crumbs && crumbs.length > 0 ? (
          <div className="ws-page__crumb">
            {crumbs.map((c, i) => (
              <span key={i}>
                {c.href ? <Link href={c.href}>{c.label}</Link> : c.label}
                {i < crumbs.length - 1 ? " / " : ""}
              </span>
            ))}
          </div>
        ) : null}
        <h1 className="ws-page__title">{title}</h1>
        {subtitle ? <p className="ws-page__subtitle">{subtitle}</p> : null}
      </div>
      {actions ? <div className="ws-page__actions">{actions}</div> : null}
    </header>
  );
}
