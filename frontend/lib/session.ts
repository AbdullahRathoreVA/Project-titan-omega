// Who is using the cockpit: the founder, a demo visitor, or a subscriber.
//
// A subscriber's cockpit reads /api/me/* with their account token and must
// never see the founder's name, his businesses or the sample data the founder
// cockpit falls back to. Everything that differs by audience asks this module.

const CUSTOMER_KEY = "titan_customer";
const PROFILE_KEY = "titan_customer_profile";
// /join reads this one, so a subscriber moving between the two pages is not
// asked for their password twice.
const JOIN_KEY = "titan_account";

export type CustomerProfile = {
  email: string;
  plan_name?: string;
  plan?: string;
  /** The public demo account: read-only, and says so. */
  demo?: boolean;
};

function safe<T>(fn: () => T, fallback: T): T {
  try {
    return fn();
  } catch {
    return fallback;
  }
}

export function getCustomerToken(): string | null {
  if (typeof window === "undefined") return null;
  return safe(() => window.localStorage.getItem(CUSTOMER_KEY), null);
}

export function setCustomerToken(token: string | null, mirrorToJoin = true): void {
  if (typeof window === "undefined") return;
  safe(() => {
    if (token) {
      window.localStorage.setItem(CUSTOMER_KEY, token);
      // The demo's token is not mirrored: a visitor who then signs up on
      // /join must do it as themselves, not inside the demo account.
      if (mirrorToJoin) window.sessionStorage.setItem(JOIN_KEY, token);
      else window.sessionStorage.removeItem(JOIN_KEY);
    } else {
      window.localStorage.removeItem(CUSTOMER_KEY);
      window.localStorage.removeItem(PROFILE_KEY);
      window.sessionStorage.removeItem(JOIN_KEY);
    }
  }, undefined);
}

export function isCustomer(): boolean {
  return !!getCustomerToken();
}

export function customerProfile(): CustomerProfile | null {
  if (typeof window === "undefined") return null;
  return safe(() => {
    const raw = window.localStorage.getItem(PROFILE_KEY);
    return raw ? (JSON.parse(raw) as CustomerProfile) : null;
  }, null);
}

export function setCustomerProfile(p: CustomerProfile): void {
  if (typeof window === "undefined") return;
  safe(() => window.localStorage.setItem(PROFILE_KEY, JSON.stringify(p)), undefined);
}

/** The public demo: every screen, nothing can be changed. */
export function isDemo(): boolean {
  return Boolean(customerProfile()?.demo);
}

/** "sara.khan@shop.pk" -> "Sara". Good enough to greet someone by; the
 *  cockpit never shows anyone else's name. */
export function displayName(): string {
  const email = customerProfile()?.email ?? "";
  const first = email.split("@")[0].split(/[._\-+]/)[0] ?? "";
  return first ? first.charAt(0).toUpperCase() + first.slice(1) : "there";
}
