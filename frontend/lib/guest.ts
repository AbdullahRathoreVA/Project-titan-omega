// Is this browser session the PUBLIC read-only demo (not the founder)?
// Set by AuthGate the moment a demo session starts. Used to (a) hide controls
// that the backend would refuse anyway, and (b) drop the founder-personalised
// copy — a visitor should never be greeted as "Abdullah".

export function isGuest(): boolean {
  return (
    typeof window !== "undefined" &&
    (window as unknown as { __TITAN_GUEST?: boolean }).__TITAN_GUEST === true
  );
}
