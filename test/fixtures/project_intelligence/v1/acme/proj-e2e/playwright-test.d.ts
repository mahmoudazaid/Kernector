/** Ambient stub so fixture evidence typechecks without installing node_modules. */
declare module "@playwright/test" {
  type Locator = {
    click: () => Promise<void>;
    // Used via expect(...).toBeVisible()
    [key: string]: unknown;
  };

  type Page = {
    goto: (url: string) => Promise<void>;
    getByRole: (role: string, options?: { name?: string }) => Locator;
    getByText: (text: string) => Locator;
  };

  export const test: (
    title: string,
    body: (args: { page: Page }) => Promise<void>,
  ) => void;

  export const expect: (actual: unknown) => {
    toBeVisible: () => Promise<void>;
  };
}
