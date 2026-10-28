// SeatRing（规格 §5 第 2 步，设计稿 1d）：480px 木桌 + 篝火 + n 个 56px 座位，点座位弹木牌菜单
// （我自己 / 随机 bot / 清空 / 库内档案），或先在左栏点中档案再点座位直接分配。
//
// 受控组件：分配状态由 Lobby 持有。memory_id 已被其它座位占用的档案在菜单里禁用（后端 validate_profiles
// 也会 400）；位置复用 lib/seatModel.seatPositions（0 号顶部顺时针），与对局页圆桌同一套几何。

import { useEffect, useMemo, useRef, useState } from "react";
import type { StoredAgent } from "../../api/agents";
import { seatGlyph } from "../../lib/lobbyText";
import { seatPositions } from "../../lib/seatModel";
import { ME, memoryConflicts, type SeatSlot } from "../../lib/seats";
import RoleToken from "../RoleToken/RoleToken";
import styles from "./SeatRing.module.css";

export interface SeatRingProps {
  assignment: SeatSlot[];
  library: StoredAgent[];
  /** 「填满其余座位」的档案 id；非 null 时空位显示该档案首字。 */
  fill: string | null;
  /** 左栏当前点中的档案；非 null 时点座位直接分配（父级负责清空）。 */
  pendingAgent: string | null;
  onAssign(seat: number, agentId: string | null): void;
}

export default function SeatRing({
  assignment,
  library,
  fill,
  pendingAgent,
  onAssign,
}: SeatRingProps): JSX.Element {
  const [openSeat, setOpenSeat] = useState<number | null>(null);
  const conflicts = useMemo(() => memoryConflicts(assignment, library), [assignment, library]);
  const slots = useMemo(() => [...assignment].sort((a, b) => a.seat - b.seat), [assignment]);
  const positions = useMemo(
    () => new Map(seatPositions(slots.map((s) => s.seat)).map((p) => [p.seat, p])),
    [slots],
  );
  const meSeat = assignment.find((s) => s.agentId === ME)?.seat ?? null;
  const fillName =
    fill === null ? null : (library.find((a) => a.agent_id === fill)?.profile.name ?? null);

  const menuRef = useRef<HTMLDivElement | null>(null);
  const seatRefs = useRef(new Map<number, HTMLButtonElement>());

  // 打开：焦点进第一个可用项；Escape / 点菜单外部关闭，Escape 时焦点还给座位按钮。
  useEffect(() => {
    if (openSeat === null) return;
    const first = menuRef.current?.querySelector<HTMLButtonElement>(
      '[role="menuitem"]:not(:disabled)',
    );
    first?.focus();
    const onKey = (e: KeyboardEvent): void => {
      if (e.key !== "Escape") return;
      setOpenSeat(null);
      seatRefs.current.get(openSeat)?.focus();
    };
    const onDown = (e: MouseEvent): void => {
      const t = e.target as Node | null;
      if (t !== null && menuRef.current?.contains(t)) return;
      // 座位按钮自己的 mousedown 不算外部：由它的 click 负责切换 / 换座
      if (t !== null && seatRefs.current.get(openSeat)?.contains(t)) return;
      setOpenSeat(null);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [openSeat]);

  /** ↑ ↓ 在可用项之间循环移动焦点。 */
  function onMenuKey(e: React.KeyboardEvent<HTMLDivElement>): void {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ??
        [],
    );
    if (items.length === 0) return;
    const i = items.findIndex((el) => el === document.activeElement);
    const next =
      e.key === "ArrowDown" ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
    items[next]?.focus();
    e.preventDefault();
  }

  /** 该档案能否放到 seat：没有 memory 冲突，或冲突座位就是它自己。 */
  function allowed(agentId: string, seat: number): boolean {
    const takenAt = conflicts.get(agentId);
    return takenAt === undefined || takenAt === seat;
  }

  function pick(seat: number, agentId: string | null): void {
    onAssign(seat, agentId);
    setOpenSeat(null);
  }

  function onSeatClick(seat: number): void {
    if (pendingAgent !== null && allowed(pendingAgent, seat)) {
      pick(seat, pendingAgent);
      return;
    }
    setOpenSeat((cur) => (cur === seat ? null : seat));
  }

  return (
    <div className={styles.root} data-testid="seat-ring">
      <div className={styles.disc} />
      <div className={styles.fire} aria-hidden="true" />
      {slots.map((slot) => {
        const at = positions.get(slot.seat);
        const glyph = seatGlyph(slot.agentId, library, fillName);
        const open = openSeat === slot.seat;
        const meElsewhere = meSeat !== null && meSeat !== slot.seat;
        const pos = { left: `${at?.x ?? 50}%`, top: `${at?.y ?? 50}%` };
        return (
          <div key={slot.seat} className={styles.seatWrap}>
            <button
              ref={(el) => {
                if (el === null) seatRefs.current.delete(slot.seat);
                else seatRefs.current.set(slot.seat, el);
              }}
              type="button"
              className={styles.seat}
              aria-label={`入座 ${slot.seat}号`}
              aria-haspopup={pendingAgent === null ? "menu" : undefined}
              aria-expanded={open}
              data-kind={glyph.kind}
              style={pos}
              onClick={() => onSeatClick(slot.seat)}
            >
              <RoleToken role={null} variant="seat" size={56} initial={glyph.text} />
              <span className={styles.no}>{slot.seat}号</span>
            </button>
            {open && (
              <div
                ref={menuRef}
                role="menu"
                aria-label={`${slot.seat}号 座位菜单`}
                className={`ah-wood ${styles.menu}`}
                style={pos}
                onKeyDown={onMenuKey}
              >
                {pendingAgent !== null && allowed(pendingAgent, slot.seat) === false && (
                  <span className={styles.menuNote}>所选档案的记忆已在其它座位使用</span>
                )}
                <button
                  type="button"
                  role="menuitem"
                  className={`btn btn-ghost ${styles.item}`}
                  disabled={meElsewhere}
                  onClick={() => pick(slot.seat, ME)}
                >
                  {meElsewhere ? `我自己（已在 ${meSeat}号）` : "我自己"}
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className={`btn btn-ghost ${styles.item}`}
                  onClick={() => pick(slot.seat, null)}
                >
                  随机 bot
                </button>
                {slot.agentId !== null && (
                  <button
                    type="button"
                    role="menuitem"
                    className={`btn btn-ghost ${styles.item}`}
                    onClick={() => pick(slot.seat, null)}
                  >
                    清空
                  </button>
                )}
                {library.length > 0 && <span className={styles.menuRule} />}
                {library.map((a) => {
                  const takenAt = conflicts.get(a.agent_id);
                  const disabled = takenAt !== undefined && takenAt !== slot.seat;
                  return (
                    <button
                      key={a.agent_id}
                      type="button"
                      role="menuitem"
                      className={`btn btn-ghost ${styles.item}`}
                      disabled={disabled}
                      onClick={() => pick(slot.seat, a.agent_id)}
                    >
                      {a.profile.name}
                      {disabled ? `（记忆已在 ${takenAt}号 使用）` : ""}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
