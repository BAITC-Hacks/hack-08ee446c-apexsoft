// Narrow PAN/CVV detection; keep in sync with backend/privacy.py.
const cvv = /\b(?:cvv2?|cvc2?)\s*[:=№-]?\s*[0-9]{3,4}(?![0-9])|(?:код\s+безопасности|защитный\s+код|қауіпсіздік\s+коды)\s*[:=№-]?\s*[0-9]{3,4}(?![0-9])/iu;
const productCode = /(?:артикул|код\s+товара|sku|ean|gtin)\s*[:#№=-]?\s*$/iu;
const paymentContext = /(?:^|[^\p{L}\p{N}_])(?:карт[аыуые]|карточк\p{L}*|card|visa|mastercard|cvv2?|cvc2?|pan)(?![\p{L}\p{N}_])/iu;

function luhn(digits: string): boolean {
  if (new Set(digits).size === 1) return false;
  const sum = [...digits].reverse().reduce((total, digit, index) => {
    let value = Number(digit);
    if (index % 2) { value *= 2; if (value > 9) value -= 9; }
    return total + value;
  }, 0);
  return sum % 10 === 0;
}

export function containsPaymentData(text: string): boolean {
  if (cvv.test(text)) return true;
  const hasContext = paymentContext.test(text);
  const pan = /(?<![\p{L}\p{N}_-])[0-9](?:[ \t\u00a0-]*[0-9]){12,18}(?![\p{L}\p{N}_-])/gu;
  for (const match of text.matchAll(pan)) {
    const endings = [...match[0].matchAll(/[0-9](?=[ \t\u00a0-]|$)/g)].map(end => end.index + 1);
    const candidates = endings.map(end => match[0].slice(0, end).replace(/[^0-9]/g, ""));
    if (!candidates.some(digits => digits.length >= 13 && digits.length <= 19 && luhn(digits))) continue;
    if (!hasContext && productCode.test(text.slice(Math.max(0, match.index - 40), match.index))) continue;
    return true;
  }
  return false;
}

export const PAYMENT_REDACTED = "Сообщение с платёжными реквизитами не сохранено.";
