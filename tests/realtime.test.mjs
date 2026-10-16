import assert from 'node:assert/strict';
import test from 'node:test';
import { pcm16, RealtimeClient } from '../web/realtime.mjs';

function setup() {
  const socket = { sent: [], bufferedAmount: 0, send(data) { this.sent.push(data); }, close() {} };
  const segments = [], errors = [];
  const client = new RealtimeClient({ socketFactory: () => socket,
    onSegment: (s) => segments.push(s), onError: (s) => errors.push(s) });
  const receive = (event) => socket.onmessage({ data: JSON.stringify(event) });
  return { client, socket, segments, errors, receive };
}

test('PCM input is clipped little-endian 16-bit mono', () => {
  const bytes = pcm16(new Float32Array([-2, -1, 0, 1, 2]));
  const view = new DataView(bytes);
  assert.deepEqual(Array.from({ length: 5 }, (_, i) => view.getInt16(i * 2, true)),
    [-32768, -32768, 0, 32767, 32767]);
});

test('streams a short audio chunk immediately and waits for final subtitles on finish', async () => {
  const { client, socket, receive, segments } = setup();
  const connected = client.connect('ws://localhost/test');
  receive({ type: 'ready', offset: 0 });
  await connected;
  client.send(new Float32Array(1600));
  assert.equal(socket.sent[0].byteLength, 3200);
  let ended = false;
  const finished = client.finish().then(() => { ended = true; });
  assert.deepEqual(JSON.parse(socket.sent[1]), { type: 'finish' });
  receive({ type: 'segment', segment: { text: 'last sentence' } });
  assert.equal(ended, false);
  assert.equal(segments[0].text, 'last sentence');
  receive({ type: 'finished' });
  await finished;
  assert.equal(ended, true);
});

test('backpressure stops the stream instead of silently falling behind', async () => {
  const { client, socket, receive, errors } = setup();
  const connected = client.connect('ws://localhost/test');
  receive({ type: 'ready' }); await connected;
  socket.bufferedAmount = 96001;
  assert.throws(() => client.send(new Float32Array(1600)), /积压/);
  assert.equal(errors.length, 1);
  assert.equal(socket.sent.length, 0);
  await assert.rejects(client.finish(), /积压/);
});

test('connection errors reject cleanly before microphone audio is sent', async () => {
  const { client, receive, errors } = setup();
  const connected = client.connect('ws://localhost/test');
  receive({ type: 'error', message: '请先设置 API Key' });
  await assert.rejects(connected, /API Key/);
  assert.equal(errors.length, 0);
});
