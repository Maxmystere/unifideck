/**
 * Minimal stand-in for React under vitest. At runtime React is
 * peer-provided by the Steam webview (SP_REACT) and is deliberately
 * not installed in node_modules, so tests that import steam-bridge
 * modules resolve "react" to this stub via the vitest alias.
 */
/**
 * Synchronous `useMemo`: run the factory and return its value, ignoring the
 * dependency list. Enough to unit-test a hook whose body is a pure decision
 * over its inputs (`usePlaySection`), and honest about what it does not
 * cover — memoisation and re-render behaviour are not exercised here.
 */
function useMemo<T>(factory: () => T, _deps?: readonly unknown[]): T {
  return factory();
}

const React = {
  createElement: (
    type: unknown,
    props: unknown,
    ...children: unknown[]
  ): Record<string, unknown> => ({ type, props, children }),
  useMemo,
};

export { useMemo };
export default React;
