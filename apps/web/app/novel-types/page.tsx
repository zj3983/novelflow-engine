import { NovelTypeLibraryClient } from "../../components/novel-types/NovelTypeLibraryClient";
import { WorkspaceShell } from "../../components/ws/WorkspaceShell";

export default function NovelTypesPage() {
  return (
    <WorkspaceShell>
      <NovelTypeLibraryClient />
    </WorkspaceShell>
  );
}
