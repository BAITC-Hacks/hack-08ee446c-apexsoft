import { describe, expect, it } from "vitest";
import { quantityError, safeUrl } from "../api";
import { product } from "./fixtures";

describe("untrusted data boundaries", () => {
  it("allows only HTTPS links without credentials, and explicit local paths when requested", () => {
    for (const url of [
      "javascript:alert(1)",
      "data:text/html,a",
      "//evil.example",
      "https://user:password@ekt.kz",
      "http://ekt.kz",
      "/\\evil.example",
      "/\n/evil.example",
    ])
      expect(safeUrl(url, true)).toBeUndefined();
    expect(safeUrl("https://ekt.kz/catalog/")).toBe("https://ekt.kz/catalog/");
    expect(safeUrl("/cart", true)).toBe("/cart");
    expect(safeUrl("/cart")).toBeUndefined();
  });
  it("checks existing cart quantity, minimums, decimal steps, and missing stock", () => {
    expect(quantityError(product, 3, 10)).toBeTruthy();
    expect(quantityError(product, NaN)).toBeTruthy();
    expect(quantityError({ ...product, min_quantity: 3 }, 2)).toBeTruthy();
    expect(
      quantityError({ ...product, min_quantity: 0.1, quantity_step: 0.1 }, 0.3),
    ).toBeNull();
    expect(quantityError({ ...product, quantity_step: 2 }, 3)).toBeTruthy();
    expect(quantityError({ ...product, stock: null }, 1)).toBeTruthy();
  });
});
