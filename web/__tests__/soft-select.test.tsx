import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SoftSelect } from "@/components/ui/SoftSelect";

describe("SoftSelect", () => {
  it("moves highlight with arrows and commits only on Enter", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SoftSelect
        id="model"
        label="Model"
        value="a"
        options={["a", "b", "c"]}
        onChange={onChange}
      />,
    );

    const trigger = screen.getByLabelText(/^Model$/i);
    await user.click(trigger);
    expect(screen.getByRole("listbox")).toHaveFocus();

    await user.keyboard("{ArrowDown}{ArrowDown}");
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("listbox")).toHaveAttribute(
      "aria-activedescendant",
      expect.stringMatching(/-2$/),
    );

    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("c");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("keeps the highlight after a parent re-render with inline options", async () => {
    const user = userEvent.setup();

    function Host({ options }: { options: string[] }) {
      return (
        <SoftSelect
          id="model"
          label="Model"
          value="a"
          options={options}
          onChange={() => undefined}
        />
      );
    }

    const { rerender } = render(<Host options={["a", "b", "c"]} />);

    await user.click(screen.getByLabelText(/^Model$/i));
    await user.keyboard("{ArrowDown}{ArrowDown}");
    const before = screen
      .getByRole("listbox")
      .getAttribute("aria-activedescendant");
    expect(before).toMatch(/-2$/);

    rerender(<Host options={["a", "b", "c"]} />);
    expect(screen.getByRole("listbox")).toHaveAttribute(
      "aria-activedescendant",
      before,
    );

    const trigger = screen.getByLabelText(/^Model$/i);
    trigger.focus();
    expect(trigger).toHaveFocus();
    rerender(<Host options={["a", "b", "c"]} />);
    expect(trigger).toHaveFocus();
    expect(screen.getByRole("listbox")).toHaveAttribute(
      "aria-activedescendant",
      before,
    );
  });

  it("closes when focus leaves the control", async () => {
    const user = userEvent.setup();
    render(
      <>
        <SoftSelect
          id="model"
          label="Model"
          value="a"
          options={["a", "b"]}
          onChange={() => undefined}
        />
        <button type="button">Outside</button>
      </>,
    );

    await user.click(screen.getByLabelText(/^Model$/i));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Outside" }));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("jumps to matching options via typeahead", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SoftSelect
        id="model"
        label="Model"
        value="anthropic/claude"
        options={[
          "anthropic/claude",
          "google/gemini-2.5-flash",
          "openai/gpt-4o-mini",
          "openai/gpt-4o",
        ]}
        onChange={onChange}
      />,
    );

    await user.click(screen.getByLabelText(/^Model$/i));
    await user.keyboard("gpt");
    expect(screen.getByRole("listbox")).toHaveAttribute(
      "aria-activedescendant",
      expect.stringMatching(/-2$/),
    );

    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith("openai/gpt-4o-mini");
  });

  it("keeps options out of the tab order", async () => {
    const user = userEvent.setup();
    render(
      <>
        <SoftSelect
          id="model"
          label="Model"
          value="a"
          options={["a", "b", "c"]}
          onChange={() => undefined}
        />
        <button type="button">Next</button>
      </>,
    );

    await user.click(screen.getByLabelText(/^Model$/i));
    expect(screen.getAllByRole("option")).toHaveLength(3);
    await user.tab();
    expect(screen.getByRole("button", { name: "Next" })).toHaveFocus();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
