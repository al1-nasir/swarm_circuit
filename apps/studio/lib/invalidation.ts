// Fixed-window coalescing: a busy stream must never keep postponing its refresh.
export function createInvalidator(
  run: () => void,
  defer: (callback: () => void) => () => void = (callback) => {
    const timer = setTimeout(callback, 250);
    return () => clearTimeout(timer);
  },
) {
  let cancel: (() => void) | undefined;
  return {
    schedule() {
      if (cancel) return;
      cancel = defer(() => {
        cancel = undefined;
        run();
      });
    },
    cancel() {
      cancel?.();
      cancel = undefined;
    },
  };
}
