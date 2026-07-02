// Small device helpers for tuning 3D scenes per device class.

export function isCoarsePointer(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.matchMedia?.("(pointer: coarse)").matches ?? false;
  } catch {
    return false;
  }
}
