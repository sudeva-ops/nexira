// Calm mode (UI 3): a person can turn all motion off from the user menu; it is kept in this
// browser. It counts as reduced motion everywhere (useReducedMotion), and the page gets the class
// nx-calm so CSS animations stop too.

const KEY = "nexira.calm";
const EVENT = "nexira-calm";

export function calmNow(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "on";
  } catch {
    return false;
  }
}

function apply(calm: boolean): void {
  document.documentElement.classList.toggle("nx-calm", calm);
}

export function setCalm(calm: boolean): void {
  try {
    window.localStorage.setItem(KEY, calm ? "on" : "off");
  } catch {
    // blocked storage: the choice lasts for this page only
  }
  apply(calm);
  window.dispatchEvent(new Event(EVENT));
}

export function subscribeCalm(onChange: () => void): () => void {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange); // another tab changed it
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** On start: the class follows the stored choice. */
export function initCalm(): void {
  apply(calmNow());
}
