import { TestDesignWorkspace } from "@/components/test-design/TestDesignWorkspace";

/** Same-origin BFF so kernector_session reaches FastAPI (#447). */
const BFF = "";

type Props = {
  params: Promise<{ draftId: string }>;
};

export default async function TestDesignPage({ params }: Props) {
  const { draftId } = await params;
  return <TestDesignWorkspace apiBaseUrl={BFF} draftId={draftId} />;
}
