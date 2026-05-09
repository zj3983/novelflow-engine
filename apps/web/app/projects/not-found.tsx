import Link from "next/link";

export default function ProjectsNotFound() {
  return (
    <div className="ws-page">
      <div className="ws-empty">
        <div className="ws-empty__icon">?</div>
        <p className="ws-empty__title">页面不存在</p>
        <p className="ws-empty__hint">
          检查一下 URL，或回到 <Link href="/projects">作品列表</Link>。
        </p>
      </div>
    </div>
  );
}
