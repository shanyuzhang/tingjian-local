export function wavHeader(samples) {
  const buffer = new ArrayBuffer(44), view = new DataView(buffer);
  const ascii = (offset, text) => [...text].forEach((char, i) => view.setUint8(offset + i, char.charCodeAt(0)));
  ascii(0, 'RIFF'); view.setUint32(4, 36 + samples * 2, true); ascii(8, 'WAVE');
  ascii(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, 16000, true); view.setUint32(28, 32000, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); ascii(36, 'data');
  view.setUint32(40, samples * 2, true);
  return buffer;
}

export function makeWav(samples) {
  const pcm = new ArrayBuffer(samples.length * 2), view = new DataView(pcm);
  samples.forEach((value, i) => {
    value = Math.max(-1, Math.min(1, value));
    view.setInt16(i * 2, value < 0 ? value * 32768 : value * 32767, true);
  });
  return new Blob([wavHeader(samples.length), pcm], { type: 'audio/wav' });
}
