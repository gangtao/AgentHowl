// 顶栏「桌面：圆桌 ▾ / 卡牌 ▾」（规格 §7）：读写 usePrefs.tableStyle。所有视角都显示——皮肤只是画法。

import { usePrefs, type TableStyle } from "../../store/prefs";
import styles from "./PhaseBar.module.css";

export default function TableStyleToggle(): JSX.Element {
  const tableStyle = usePrefs((s) => s.tableStyle);
  const setTableStyle = usePrefs((s) => s.setTableStyle);
  return (
    <label className={styles.skin}>
      <span className={styles.skinKey}>桌面：</span>
      <select
        className={styles.skinSelect}
        aria-label="桌面皮肤"
        value={tableStyle}
        onChange={(e) => setTableStyle(e.target.value as TableStyle)}
      >
        <option value="round">圆桌</option>
        <option value="cards">卡牌</option>
      </select>
    </label>
  );
}
