// 界面偏好 store（规格 §7）：桌面皮肤「圆桌 / 卡牌」，记在 localStorage["agenthowl.tableStyle"]。
// 读写都 try/catch（隐私模式等场景 localStorage 不可用）：读失败 / 坏值 → "round"，写失败只记在内存里。
// 零过滤：偏好只影响桌子区怎么画，不改任何数据流。

import { create } from "zustand";

export type TableStyle = "round" | "cards";

export const TABLE_STYLE_KEY = "agenthowl.tableStyle";

function isTableStyle(v: unknown): v is TableStyle {
  return v === "round" || v === "cards";
}

/** 读偏好；缺省 / 坏值 / 读不到 → "round"。 */
export function readTableStyle(): TableStyle {
  try {
    const v = localStorage.getItem(TABLE_STYLE_KEY);
    return isTableStyle(v) ? v : "round";
  } catch {
    return "round";
  }
}

interface PrefsState {
  tableStyle: TableStyle;
  setTableStyle(v: TableStyle): void;
}

export const usePrefs = create<PrefsState>((set) => ({
  tableStyle: readTableStyle(),
  setTableStyle(v) {
    try {
      localStorage.setItem(TABLE_STYLE_KEY, v);
    } catch {
      // 写不进去就只在本次会话里生效
    }
    set({ tableStyle: v });
  },
}));
