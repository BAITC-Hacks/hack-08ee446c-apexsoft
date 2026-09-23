import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProductCard } from "../components";
import { product } from "./fixtures";
import { responseChecks } from "../responseValidation";
import { chat } from "./fixtures";

const props = { busy: false, existing: 0, onPropose: vi.fn(), onAlternatives: vi.fn() };

describe("product cards in the conversation", () => {
  it("shows a real image, description and exact product link without expanding technical details", () => {
    const item = { ...product, image_url: "https://ekt.kz/upload/test.jpg", product_url: "https://ekt.kz/catalog/test/item/" };
    render(<ProductCard {...props} product={item} />);
    expect(screen.getByRole("img", { name: item.name })).toHaveAttribute("src", item.image_url);
    expect(screen.getByText(item.description)).toBeVisible();
    const link = screen.getByRole("link", { name: "Открыть товар на ekt.kz" });
    expect(link).toBeVisible();
    expect(link).toHaveAttribute("href", item.product_url);
    expect(link.closest("details")).toBeNull();
    expect(props.onPropose).not.toHaveBeenCalled();
  });

  it("lets the reader expand a long description independently of specifications", async () => {
    const user = userEvent.setup();
    const description = "Описание товара из каталога. ".repeat(20) + "Конец описания.";
    render(<ProductCard {...props} product={{ ...product, description }} />);
    expect(screen.queryByText(/Конец описания/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Читать описание полностью" }));
    expect(screen.getByText(/Конец описания/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Свернуть описание" })).toHaveAttribute("aria-expanded", "true");
  });

  it("handles a broken image without hiding the product or its link", () => {
    render(<ProductCard {...props} product={{ ...product, image_url: "https://ekt.kz/upload/missing.jpg", product_url: "https://ekt.kz/catalog/item/" }} />);
    fireEvent.error(screen.getByRole("img"));
    expect(screen.getByText("Фото не загрузилось")).toBeVisible();
    expect(screen.getByRole("heading", { name: product.name })).toBeVisible();
    expect(screen.getByRole("link", { name: "Открыть товар на ekt.kz" })).toBeVisible();
  });

  it.each([null, "https://ekt.kz/", "https://ekt.kz/catalog/", "javascript:alert(1)"])("does not present missing or generic URLs as a product link: %s", (product_url) => {
    render(<ProductCard {...props} product={{ ...product, product_url, description: "" }} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("Описание в каталоге не указано.")).toBeVisible();
    expect(screen.getByText("Нет фото")).toBeVisible();
    expect(responseChecks.chat({ ...chat, products: [{ ...product, product_url }] })).toBe(true);
  });
});
