// @vitest-environment node
// issue #166：index.html 必须声明 favicon，否则浏览器每次都去要 /favicon.ico 并在控制台记一条 404。
import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");

describe("index.html", () => {
  it("声明 <link rel=\"icon\"> 且图标文件存在于 public/", () => {
    const m = html.match(/<link rel="icon"[^>]*href="\/([^"]+)"/);
    expect(m, "缺少 <link rel=\"icon\">").not.toBeNull();
    expect(existsSync(new URL(`../public/${m![1]}`, import.meta.url))).toBe(true);
  });
});
