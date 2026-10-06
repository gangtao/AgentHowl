// 语音播报开关（issue #103）：放在左栏座位环之上的小 pill。没有任何配音（available=false，
// 清单没拉到或还没收到过 speech_audio 帧）时整个不渲染——没有音频也就没有开关的意义。
// 浏览器自动播放策略要求 enabled=true 只能从用户手势（这里的 onClick）里置真，不能默认开启。

import { useVoice } from "../../store/voice";
import styles from "./VoiceToggle.module.css";

export default function VoiceToggle(): JSX.Element | null {
  const available = useVoice((s) => s.available);
  const enabled = useVoice((s) => s.enabled);
  const playing = useVoice((s) => s.playing);
  const setEnabled = useVoice((s) => s.setEnabled);

  if (!available) return null;

  return (
    <div className={styles.root}>
      <button
        type="button"
        className={`${styles.toggle} ${enabled ? styles.on : ""}`}
        aria-pressed={enabled}
        onClick={() => setEnabled(!enabled)}
      >
        {enabled ? "🔊 语音 开" : "🔇 语音 关"}
        {enabled && playing !== null && <span className={styles.dot} aria-hidden="true" />}
      </button>
    </div>
  );
}
