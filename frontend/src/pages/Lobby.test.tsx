// 建局页「语音播报 / 旁白」联动（issue #110）：旁白依赖语音，关语音时旁白一并取消。

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Lobby from "./Lobby";

function stubFetch(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = url.endsWith("/tts/status")
        ? { enabled: true, ok: true, url: null, detail: null, supports_style: false }
        : [];
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Lobby 旁白开关", () => {
  it("语音未勾时旁白禁用；勾语音→勾旁白→取消语音后旁白取消勾选并禁用", async () => {
    stubFetch();
    render(<Lobby />);
    const voice = (await screen.findByLabelText(/语音播报/)) as HTMLInputElement;
    const narration = screen.getByLabelText(/^旁白/) as HTMLInputElement;
    expect(narration).toBeDisabled();

    fireEvent.click(voice);
    expect(narration).not.toBeDisabled();
    fireEvent.click(narration);
    expect(narration.checked).toBe(true);

    fireEvent.click(voice);
    expect(narration.checked).toBe(false);
    expect(narration).toBeDisabled();

    // 重新勾语音时旁白不能「复活」（内部状态已清掉）
    fireEvent.click(voice);
    expect(narration.checked).toBe(false);
  });
});
