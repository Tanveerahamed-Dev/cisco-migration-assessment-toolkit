/**
 * Match the closed ASCII semantic-identifier grammar without a backtracking
 * regular expression. Identifiers contain at least one dot or hyphen, never
 * start or end with a separator, and never contain adjacent separators.
 */
export function isSemanticIdentifier(value: string): boolean {
  let sawSeparator = false;
  let previousWasSeparator = true;

  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    const isLowerAscii = code >= 0x61 && code <= 0x7a;
    const isAsciiDigit = code >= 0x30 && code <= 0x39;
    if (isLowerAscii || isAsciiDigit) {
      previousWasSeparator = false;
      continue;
    }
    if ((code === 0x2d || code === 0x2e) && !previousWasSeparator) {
      sawSeparator = true;
      previousWasSeparator = true;
      continue;
    }
    return false;
  }

  return sawSeparator && !previousWasSeparator;
}
