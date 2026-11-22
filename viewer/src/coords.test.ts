import { describe, expect, it } from "vitest";
import { tileToWorld } from "./coords";

describe("tileToWorld", () => {
  it("maps the first tile centre of a 4x4 map to the negative corner", () => {
    expect(tileToWorld(0, 0, 4)).toEqual({ x: -1.5, z: -1.5 });
  });

  it("maps the last tile centre to the positive corner", () => {
    expect(tileToWorld(3, 3, 4)).toEqual({ x: 1.5, z: 1.5 });
  });

  it("keeps x and z independent", () => {
    expect(tileToWorld(3, 0, 4)).toEqual({ x: 1.5, z: -1.5 });
  });

  it("scales with tile size", () => {
    expect(tileToWorld(0, 1, 2, 10)).toEqual({ x: -5, z: 5 });
  });

  it("scales x with tile size too", () => {
    expect(tileToWorld(1, 0, 2, 10)).toEqual({ x: 5, z: -5 });
  });

  it("names the tile and map size in the error", () => {
    expect(() => tileToWorld(4, 1, 4)).toThrow("tile (4, 1) is outside a 4x4 map");
  });

  it.each([
    [-1, 0],
    [0, -1],
    [4, 0],
    [0, 4],
    [0.5, 0],
  ])("rejects tile (%d, %d) outside a 4x4 map", (tx, ty) => {
    expect(() => tileToWorld(tx, ty, 4)).toThrow(RangeError);
  });
});
