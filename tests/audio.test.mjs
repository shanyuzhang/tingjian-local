import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import { makeWav, wavHeader } from '../web/audio.mjs';

test('WAV encoder preserves mono PCM values, clipping, byte order and duration', async () => {
  const blob = makeWav(new Float32Array([-2, -1, 0, 1, 2]));
  const data = new DataView(await blob.arrayBuffer());
  assert.equal(data.getUint32(24, true), 16000);
  assert.equal(data.getUint16(22, true), 1);
  assert.equal(data.getUint16(34, true), 16);
  assert.equal(data.getUint32(40, true), 10);
  assert.deepEqual(Array.from({ length: 5 }, (_, i) => data.getInt16(44 + i * 2, true)),
    [-32768, -32768, 0, 32767, 32767]);
  const backup = new Blob([wavHeader(10), blob.slice(44), blob.slice(44)]);
  assert.equal(backup.size, 64);
});

test('AudioWorklet flush retains the final partial buffer exactly once', () => {
  let Processor;
  const messages = [];
  const context = vm.createContext({
    Float32Array,
    AudioWorkletProcessor: class { constructor() { this.port = { postMessage: (data) => messages.push(data) }; } },
    registerProcessor: (name, type) => { assert.equal(name, 'pcm-recorder'); Processor = type; },
  });
  vm.runInContext(readFileSync(new URL('../web/recorder-worklet.js', import.meta.url), 'utf8'), context);
  const processor = new Processor();
  for (let i = 0; i < 41; i++) processor.process([[new Float32Array(128).fill(i)]]);
  processor.port.onmessage({ data: 'flush' });
  processor.port.onmessage({ data: 'flush' });
  const samples = messages.filter((message) => message.kind === 'samples').flatMap((m) => [...m.samples]);
  assert.equal(samples.length, 41 * 128);
  for (let i = 0; i < samples.length; i++) assert.equal(samples[i], Math.floor(i / 128));
  assert.equal(messages.filter((m) => m.kind === 'flushed').length, 2);
});
