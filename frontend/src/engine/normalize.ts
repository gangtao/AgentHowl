// normalizeState：深拷贝后把集合字段升序排列、undefined 归一为 null，供金样对拍与调试 diff 使用。
// 纯函数、零 IO。

import type { GameState } from "./types";

function sortedNums(xs: readonly number[]): number[] {
  return [...xs].sort((a, b) => a - b);
}

/** JSON 深拷贝：把 undefined 归一为 null（JSON.stringify 本就会丢弃 undefined 属性，
 * 这里显式往返一次以保证与后端 JSON 序列化后的金样同构比较）。 */
function deepClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function normalizeState(state: GameState): GameState {
  const cloned = deepClone(state);
  return {
    ...cloned,
    acted_seats: sortedNums(cloned.acted_seats),
    sheriff_declared: sortedNums(cloned.sheriff_declared),
    sheriff_withdrawn: sortedNums(cloned.sheriff_withdrawn),
    sheriff_confirmed: sortedNums(cloned.sheriff_confirmed),
  };
}
