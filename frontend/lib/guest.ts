// Is this browser session the public read-only demo (not the founder)?
// Set by AuthGate when a demo session starts. Used to hide controls the backend
// would refuse anyway, and to drop founder-specific copy so a visitor isn't
// greeted by the founder's name.

export function isGuest(): boolean {
  return (
    typeof window !== "undefined" &&
    (window as unknown as { __TITAN_GUEST?: boolean }).__TITAN_GUEST === true
  );
}
