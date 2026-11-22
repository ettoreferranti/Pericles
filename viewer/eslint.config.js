import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "reports", ".stryker-tmp", "node_modules"] },
  js.configs.recommended,
  ...tseslint.configs.strict,
);
