import { AppShell } from "../../components/AppShell";
import { ConfigPageClient } from "../../components/config/ConfigPageClient";

export default function ConfigPage() {
  return (
    <AppShell
      title="配置中心"
      description="全局 API、单个代理覆盖和运行策略都在这里统一管理，写作页不再被系统配置打断。"
    >
      <ConfigPageClient />
    </AppShell>
  );
}
