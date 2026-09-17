import { describe, expect, it } from "vitest";
import { decodePcm16, newResampleState, resample } from "./pcm";

/** A ramp is the easiest signal to see a seam in: any step shows up as a kink. */
function ramp(from: number, count: number): Int16Array {
  return Int16Array.from({ length: count }, (_, index) => from + index);
}

describe("resample", () => {
  it("passes samples through untouched when the rates already match", () => {
    const state = newResampleState();
    const out = resample(Int16Array.from([0, 16384, -16384]), 24000, 24000, state);
    expect(Array.from(out)).toEqual([0, 0.5, -0.5]);
  });

  it("stays continuous across chunk boundaries", () => {
    // One ramp, delivered as three chunks, must resample to the same thing as
    // the whole ramp at once. Resampling each chunk on its own leaves a step at
    // every seam, which is what the browser does for us and what ticks.
    const whole = ramp(0, 240);
    const state = newResampleState();
    const together = Array.from(resample(whole, 24000, 48000, state));

    const split = newResampleState();
    const pieces = [
      resample(whole.slice(0, 37), 24000, 48000, split),
      resample(whole.slice(37, 150), 24000, 48000, split),
      resample(whole.slice(150), 24000, 48000, split)
    ];
    const streamed = pieces.flatMap((piece) => Array.from(piece));

    expect(streamed.length).toBe(together.length);
    streamed.forEach((value, index) => expect(value).toBeCloseTo(together[index], 6));
  });

  it("produces no kink at the seam of a straight ramp", () => {
    const state = newResampleState();
    const first = resample(ramp(0, 100), 24000, 48000, state);
    const second = resample(ramp(100, 100), 24000, 48000, state);
    const joined = [...Array.from(first), ...Array.from(second)];
    const steps = joined.slice(1).map((value, index) => value - joined[index]);
    const widest = Math.max(...steps);
    const narrowest = Math.min(...steps);
    // A ramp resampled continuously has one constant step everywhere.
    expect(widest - narrowest).toBeLessThan(1e-9);
  });

  it("resamples downward without drifting", () => {
    const state = newResampleState();
    const out = resample(ramp(0, 480), 48000, 24000, state);
    expect(out.length).toBeGreaterThan(238);
    expect(out.length).toBeLessThan(242);
  });
});

describe("decodePcm16", () => {
  it("reads little-endian signed samples", () => {
    const decoded = decodePcm16(Uint8Array.from([0x00, 0x80, 0xff, 0x7f]));
    expect(Array.from(decoded!)).toEqual([-32768, 32767]);
  });

  it("refuses a lone byte rather than inventing a sample", () => {
    expect(decodePcm16(Uint8Array.from([0x01]))).toBeNull();
  });

  it("reads a buffer that does not start at a two-byte offset", () => {
    // A Uint8Array can begin at an odd offset, which Int16Array refuses to view.
    const backing = new Uint8Array([0xaa, 0x00, 0x80, 0xff, 0x7f]);
    const shifted = backing.subarray(1);
    expect(Array.from(decodePcm16(shifted)!)).toEqual([-32768, 32767]);
  });
});
