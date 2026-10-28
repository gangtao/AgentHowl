// 右栏信息卡（规格 §4.5，设计稿 3a 右侧）：按 railCards 给出的 id 顺序渲染，每张是一块 .ah-panel。
// 零过滤：props 里没有 viewer；每张卡只看 state / events / 服务端观察给的 potions / knownRoles。

import type { NightSummaryRow } from "../../engine/select";
import type { Event, GameState, RoleType } from "../../engine/types";
import type { RailCardId } from "../../lib/railCards";
import ElectionPanel from "../ElectionPanel/ElectionPanel";
import NightSummary from "../NightSummary/NightSummary";
import PlayerStatusPanel from "../PlayerStatusPanel/PlayerStatusPanel";
import VotePanel from "../VotePanel/VotePanel";
import { Graveyard } from "./Graveyard";
import styles from "./InfoRail.module.css";
import { NightFlow } from "./NightFlow";
import { PkRecap } from "./PkRecap";
import { Potions } from "./Potions";
import { SeerLog } from "./SeerLog";
import { TownNews } from "./TownNews";

export interface InfoRailProps {
  cards: RailCardId[];
  state: GameState;
  /** 已按回放游标截断的事件流。 */
  events: readonly Event[];
  speakingSeat: number | null;
  nightRows: NightSummaryRow[];
  /** 女巫观察里的药瓶；没有则不渲染药瓶卡。 */
  potions?: { antidote: boolean; poison: boolean } | null;
  /** 服务端观察给出的角色覆盖层（墓地 / 结算用）。 */
  knownRoles?: Record<number, RoleType>;
}

export default function InfoRail({
  cards,
  state,
  events,
  speakingSeat,
  nightRows,
  potions = null,
  knownRoles = {},
}: InfoRailProps): JSX.Element {
  const render = (id: RailCardId): JSX.Element | null => {
    switch (id) {
      case "news":
        return <TownNews state={state} events={events} />;
      case "graveyard":
        return <Graveyard state={state} events={events} knownRoles={knownRoles} />;
      case "order":
        return <PlayerStatusPanel state={state} speakingSeat={speakingSeat} />;
      case "election":
        return <ElectionPanel state={state} events={[...events]} />;
      case "votes":
        return <VotePanel state={state} events={[...events]} />;
      case "nightFlow":
        return <NightFlow state={state} />;
      case "seerLog":
        return <SeerLog state={state} />;
      case "potions":
        return potions === null ? null : (
          <Potions antidote={potions.antidote} poison={potions.poison} />
        );
      case "nightActs":
        return <NightSummary rows={nightRows} round={state.round} />;
      case "pkRecap":
        return <PkRecap state={state} events={events} />;
    }
  };
  return (
    <aside className={styles.root} aria-label="信息栏">
      {cards.map((id) => {
        const node = render(id);
        return node === null ? null : (
          <div key={id} className={styles.card} data-card={id}>
            {node}
          </div>
        );
      })}
    </aside>
  );
}
