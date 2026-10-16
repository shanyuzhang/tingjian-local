export function pcm16(samples) {
  const buffer = new ArrayBuffer(samples.length * 2), view = new DataView(buffer);
  samples.forEach((sample, index) => view.setInt16(index * 2,
    Math.max(-32768, Math.min(32767, Math.round(sample * 32768))), true));
  return buffer;
}

export class RealtimeClient {
  constructor({ onSegment, onError, socketFactory = (url) => new WebSocket(url) }) {
    this.onSegment = onSegment;
    this.onError = onError;
    this.socketFactory = socketFactory;
    this.ready = false;
    this.terminal = false;
  }

  connect(url) {
    return new Promise((resolve, reject) => {
      this.rejectConnect = reject;
      this.connectTimer = setTimeout(() => this.fail('实时连接超时，请检查网络后重试。'), 22000);
      this.socket = this.socketFactory(url);
      this.socket.onmessage = ({ data }) => {
        let event;
        try { event = JSON.parse(data); }
        catch { return this.fail('实时字幕消息无效，录音备份已保留。'); }
        if (event.type === 'ready') {
          clearTimeout(this.connectTimer);
          this.ready = true;
          this.rejectConnect = null;
          resolve(event);
        } else if (event.type === 'segment') this.onSegment(event.segment);
        else if (event.type === 'error') this.fail(event.message || '实时翻译失败。');
        else if (event.type === 'finished') {
          this.terminal = true;
          this.ready = false;
          clearTimeout(this.finishTimer);
          this.resolveFinish?.();
          this.socket.close();
        }
      };
      this.socket.onerror = () => this.fail('无法连接实时翻译，请检查本地服务和网络。');
      this.socket.onclose = () => {
        if (!this.terminal) this.fail('实时连接已断开，录音备份已保留。请继续录制新的一段。');
      };
    });
  }

  send(samples) {
    if (!this.ready || this.terminal) throw new Error('实时连接不可用，请保存录音备份。');
    if (this.socket.bufferedAmount > 32000 * 3) {
      this.fail('网络发送已积压超过 3 秒，录音已停止，请保存备份后重试。');
      throw new Error('实时音频发送积压。');
    }
    this.socket.send(pcm16(samples));
  }

  finish() {
    if (this.finishPromise) return this.finishPromise;
    if (this.terminal) return Promise.reject(new Error(this.error || '实时连接已结束。'));
    this.finishPromise = new Promise((resolve, reject) => {
      this.resolveFinish = resolve;
      this.rejectFinish = reject;
      this.finishTimer = setTimeout(() => this.fail('等待剩余字幕超时，录音备份已保留。'), 35000);
      this.socket.send(JSON.stringify({ type: 'finish' }));
    });
    return this.finishPromise;
  }

  fail(message) {
    if (this.terminal) return;
    const wasReady = this.ready;
    this.terminal = true;
    this.ready = false;
    this.error = message;
    clearTimeout(this.connectTimer);
    clearTimeout(this.finishTimer);
    this.rejectConnect?.(new Error(message));
    this.rejectFinish?.(new Error(message));
    this.socket?.close();
    if (wasReady) this.onError(message);
  }

  abort() {
    this.terminal = true;
    this.ready = false;
    clearTimeout(this.connectTimer);
    clearTimeout(this.finishTimer);
    this.socket?.close();
  }
}
