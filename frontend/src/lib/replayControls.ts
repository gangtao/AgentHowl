// 回放条控制器（issue #103 fix round 2）：把 GamePage 传给 ReplayBar 的 on* 回调抽成一个
// 纯函数，方便单测——GamePage 本身渲染太重，不值得为「暂停/拖动要不要打断配音」这一条
// 专门起一个组件级测试。
//
// 背景：游标拖动/翻页/暂停时，若当时正有一个 useVoice.playSeq() 挂在某个 seq 上等
// player.play() resolve，而用户紧接着跳到另一个 seq，旧的 playSeq 不会自己停——必须由
// 这里先调 voice.clear()（停播 + generation 自增）再去动游标，否则旧协程和新协程共享
// 同一个 <audio> 元素，互相 settle() 对方的挂起 promise，把 playing 和播放顺序搞乱。

export interface ReplayStoreControls {
  setCursor(seq: number | null): void;
  play(): void;
  pause(): void;
  setSpeed(speed: number): void;
  stepForward(): void;
  stepBack(): void;
}

export interface VoiceClearControl {
  clear(): void;
}

export interface ReplayControls {
  onCursor(seq: number): void;
  onPlay(): void;
  onPause(): void;
  onSpeed(speed: number): void;
  onStep(delta: 1 | -1): void;
  onLive(): void;
}

/** `onPlay`/`onSpeed` 不打断配音——继续播放或仅调速都不是「跳到别的 seq」；
 * 其余四个（拖动游标/暂停/单步/回到直播）都可能让回放时钟离开当前正在播的 seq，
 * 调用前必须先 `voice.clear()`。 */
export function replayControls(store: ReplayStoreControls, voice: VoiceClearControl): ReplayControls {
  return {
    onCursor(seq) {
      voice.clear();
      store.setCursor(seq);
    },
    onPlay() {
      store.play();
    },
    onPause() {
      voice.clear();
      store.pause();
    },
    onSpeed(speed) {
      store.setSpeed(speed);
    },
    onStep(delta) {
      voice.clear();
      if (delta === 1) store.stepForward();
      else store.stepBack();
    },
    onLive() {
      voice.clear();
      store.setCursor(null);
    },
  };
}
