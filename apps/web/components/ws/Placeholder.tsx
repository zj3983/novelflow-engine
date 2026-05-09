"use client";

import Link from "next/link";

import { projectHref } from "../../lib/routing";
import { PageHeader } from "./PageHeader";

type PlaceholderProps = {
  projectId?: string;
  projectTitle?: string;
  pageTitle: string;
  hint: string;
  legacyHref?: string;
  legacyLabel?: string;
};

export function PagePlaceholder({
  projectId,
  projectTitle,
  pageTitle,
  hint,
  legacyHref = "/projects",
  legacyLabel = "返回项目列表",
}: PlaceholderProps) {
  const crumbs = projectId
    ? [
        { label: "我的作品", href: "/projects" },
        { label: projectTitle || projectId, href: projectHref(projectId) },
      ]
    : undefined;

  return (
    <div className="ws-page">
      <PageHeader crumbs={crumbs} title={pageTitle} />
      <div className="ws-placeholder">
        <p className="ws-placeholder__title">本页面正在重设计</p>
        <p className="ws-placeholder__hint">{hint}</p>
        <p style={{ marginTop: 16 }}>
          <Link href={legacyHref} className="ws-btn ws-btn--primary ws-btn--sm">
            {legacyLabel}
          </Link>
        </p>
      </div>
    </div>
  );
}
