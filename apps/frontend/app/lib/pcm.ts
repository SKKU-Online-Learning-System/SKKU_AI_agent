/**
 * Turning the agent's PCM stream into buffers the output device can play.
 *
 * The stream arrives in chunks and is played as one continuous utterance, so
 * anything done per chunk has to line up at the seams. Resampling is the case
 * that does not line up on its own: handing each chunk to the browser at a rate
 * the context does not run at makes it resample them independently, and the
 * discontinuity at every boundary is audible as a tick.
 *
 * Measured against the model server's 24k->48k captures, doing it per chunk
 * leaves an error signal peaking at about a tenth of full scale, concentrated in
 * roughly 1% of frames -- inaudible on average, one click per second in practice.
 * Linear interpolation is a coarser filter than the browser's, but a little
 * high-frequency softness beats a click a second, and at the 2x ratio this
 * actually runs it is a mild low-pass rather than real distortion.
 */

/** Carries a resampler across chunk boundaries so the seams stay continuous. */
export type ResampleState = {
  /** Last input sample of the previous chunk, the left neighbour of the seam. */
  carry: number;
  /**
   * Where the next output sample falls, as an index into this chunk. Starts at
   * -1 + fraction, meaning it lies between `carry` and this chunk's first sample.
   */
  position: number;
};

export function newResampleState(): ResampleState {
  return { carry: 0, position: 0 };
}

/**
 * Linearly resample one chunk, continuing from where the previous one stopped.
 *
 * Reads across the seam rather than restarting at each chunk, which is the whole
 * point: an independent pass per chunk leaves a step at every boundary.
 */
export function resample(
  input: Int16Array,
  inputRate: number,
  outputRate: number,
  state: ResampleState
): Float32Array {
  if (input.length === 0) return new Float32Array(0);
  if (inputRate === outputRate) {
    const straight = new Float32Array(input.length);
    for (let index = 0; index < input.length; index += 1) straight[index] = input[index] / 32768;
    state.carry = input[input.length - 1];
    state.position = 0;
    return straight;
  }

  const step = inputRate / outputRate;
  const output: number[] = [];
  let position = state.position;
  // Stop once the right neighbour would be past this chunk: that sample belongs
  // to the next one, and reading it early is exactly the seam we are avoiding.
  while (position <= input.length - 1) {
    const left = Math.floor(position);
    const fraction = position - left;
    const before = left < 0 ? state.carry : input[left];
    // Only reachable with fraction 0, where the right neighbour is unused.
    const after = left + 1 < input.length ? input[left + 1] : before;
    output.push((before + (after - before) * fraction) / 32768);
    position += step;
  }
  state.carry = input[input.length - 1];
  // Re-express the position relative to the next chunk, whose left neighbour is
  // the sample just stored as the carry.
  state.position = position - input.length;
  return Float32Array.from(output);
}

/** Decode base64 PCM16 into samples, or null when there is not a whole sample. */
export function decodePcm16(bytes: Uint8Array): Int16Array | null {
  const usable = bytes.byteLength - (bytes.byteLength % 2);
  if (usable < 2) return null;
  // Copy rather than view: a Uint8Array can start at an odd byte offset, which
  // Int16Array refuses outright.
  const samples = new Int16Array(usable / 2);
  for (let index = 0; index < samples.length; index += 1) {
    samples[index] = (bytes[index * 2] | (bytes[index * 2 + 1] << 8)) << 16 >> 16;
  }
  return samples;
}
