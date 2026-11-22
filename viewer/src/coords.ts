export interface WorldPos {
  x: number;
  z: number;
}

/** Centre of tile (tx, ty) in world units, with the map centred on the origin. */
export function tileToWorld(tx: number, ty: number, mapSize: number, tileSize = 1): WorldPos {
  const inside = (v: number): boolean => Number.isInteger(v) && v >= 0 && v < mapSize;
  if (!inside(tx) || !inside(ty)) {
    throw new RangeError(`tile (${tx}, ${ty}) is outside a ${mapSize}x${mapSize} map`);
  }
  const offset = (mapSize * tileSize) / 2;
  return {
    x: tx * tileSize + tileSize / 2 - offset,
    z: ty * tileSize + tileSize / 2 - offset,
  };
}
