// AudioWorklet that forwards mono Float32 frames to the main thread (frontend design section 12).
class PcmRecorder extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor('pcm-recorder', PcmRecorder);
