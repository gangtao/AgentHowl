// 药瓶（设计稿 7b 右栏）：解药 / 毒药两格。布尔来自服务端观察（private.antidote_available / poison_available）。

import styles from "./InfoRail.module.css";

export function Potions({ antidote, poison }: { antidote: boolean; poison: boolean }): JSX.Element {
  return (
    <section className="ah-panel">
      <div className="ah-panel-head">
        <h3 className={styles.title}>药瓶</h3>
      </div>
      <div className={styles.potions}>
        <div
          className={styles.potion}
          data-kind="antidote"
          data-used={antidote ? undefined : "true"}
        >
          <div className={styles.potionName}>解药</div>
          <div className={styles.muted}>{antidote ? "未使用" : "已使用"}</div>
        </div>
        <div className={styles.potion} data-kind="poison" data-used={poison ? undefined : "true"}>
          <div className={styles.potionName}>毒药</div>
          <div className={styles.muted}>{poison ? "未使用" : "已使用"}</div>
        </div>
      </div>
    </section>
  );
}
