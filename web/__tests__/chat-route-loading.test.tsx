import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ChatRouteLoading } from "@/components/chat/ChatRouteLoading";
import { setActiveConversationId } from "@/lib/session/active-session";
import { createConversation } from "@/lib/session/conversations";

describe("ChatRouteLoading", () => {
  beforeEach(() => {
    localStorage.clear();
    setActiveConversationId(null);
  });

  it("shows the active pending conversation instead of the root brand loader", () => {
    const created = createConversation({
      title: "First ask",
      messages: [{ id: "u1", role: "user", content: "First ask" }],
      draft: "",
      runStatus: "pending",
      requestStartedAt: Date.now(),
    });
    setActiveConversationId(created.id);

    render(<ChatRouteLoading />);

    expect(screen.getByText("First ask")).toBeInTheDocument();
    expect(screen.getByText("Thinking…")).toBeInTheDocument();
    expect(document.querySelector(".kern-chat-thinking-mark")).not.toBeNull();
    expect(screen.queryByText(/^loading$/i)).not.toBeInTheDocument();
  });
});
