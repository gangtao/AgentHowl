import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// vitest 配置 globals: false，testing-library 无法自动注册清理钩子，这里显式注册，
// 否则同一文件内多次 render 的 DOM 会累积，导致查询命中上一条用例的残留节点。
afterEach(() => {
  cleanup();
});
