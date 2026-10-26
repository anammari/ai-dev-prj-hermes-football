// Vitest stand-in for the `server-only` package: in the real Next build this module throws if it is
// imported from a client component, which is the guarantee the dashboard relies on. A unit test is
// neither, so it resolves to nothing.
export {};
