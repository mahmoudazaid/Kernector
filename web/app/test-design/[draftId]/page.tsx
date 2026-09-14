import { loadPublicEnv } from "@/lib/env";
import { TestDesignWorkspace } from "@/components/test-design/TestDesignWorkspace";

type Props = {
  params: Promise<{ draftId: string }>;
};

export default async function TestDesignPage({ params }: Props) {
  const { draftId } = await params;
  const env = loadPublicEnv();
  return (
    <TestDesignWorkspace
      apiBaseUrl={env.NEXT_PUBLIC_API_BASE_URL}
      draftId={draftId}
    />
  );
}
