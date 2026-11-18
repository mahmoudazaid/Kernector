/** Ambient stub so fixture JSX typechecks without installing node_modules. */
declare module "react/jsx-runtime" {
  export namespace JSX {
    interface IntrinsicElements {
      [elemName: string]: unknown;
    }
    type Element = unknown;
  }

  export function jsx(
    type: unknown,
    props: unknown,
    key?: string,
  ): JSX.Element;
  export function jsxs(
    type: unknown,
    props: unknown,
    key?: string,
  ): JSX.Element;
  export function jsxDEV(
    type: unknown,
    props: unknown,
    key?: string,
  ): JSX.Element;
  export const Fragment: unique symbol;
}
