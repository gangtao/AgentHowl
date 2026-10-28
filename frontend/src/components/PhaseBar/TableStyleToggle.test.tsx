import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { usePrefs } from "../../store/prefs";
import TableStyleToggle from "./TableStyleToggle";

afterEach(() => {
  localStorage.clear();
  usePrefs.setState({ tableStyle: "round" });
});

describe("TableStyleToggle（规格 §7 顶栏「桌面：圆桌 ▾」）", () => {
  it("显示当前偏好并切换、持久化", () => {
    render(<TableStyleToggle />);
    const sel = screen.getByLabelText("桌面皮肤") as HTMLSelectElement;
    expect(sel.value).toBe("round");
    expect(screen.getByText("桌面：")).toBeInTheDocument();
    fireEvent.change(sel, { target: { value: "cards" } });
    expect(usePrefs.getState().tableStyle).toBe("cards");
    expect(localStorage.getItem("agenthowl.tableStyle")).toBe("cards");
    expect(sel.value).toBe("cards");
  });
});
