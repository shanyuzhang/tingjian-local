class PCMRecorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(4096);
    this.used = 0;
    this.port.onmessage = ({ data }) => {
      if (data === 'flush') {
        this.flush();
        this.port.postMessage({ kind: 'flushed' });
      }
    };
  }
  flush() {
    if (!this.used) return;
    const samples = this.buffer.slice(0, this.used);
    this.port.postMessage({ kind: 'samples', samples }, [samples.buffer]);
    this.used = 0;
  }
  process(inputs) {
    const samples = inputs[0]?.[0];
    if (!samples) return true;
    for (let offset = 0; offset < samples.length;) {
      const count = Math.min(samples.length - offset, this.buffer.length - this.used);
      this.buffer.set(samples.subarray(offset, offset + count), this.used);
      this.used += count;
      offset += count;
      if (this.used === this.buffer.length) this.flush();
    }
    return true;
  }
}
registerProcessor('pcm-recorder', PCMRecorder);
