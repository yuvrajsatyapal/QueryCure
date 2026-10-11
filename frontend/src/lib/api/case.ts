import type { CamelCasedPropertiesDeep, SnakeCasedPropertiesDeep } from "type-fest";

// The wire format is snake_case (API_DESIGN §1); TypeScript code is camelCase. Conversion happens
// only in lib/api, never in components.

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== "object") return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

const snakeToCamel = (key: string) => key.replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase());
const camelToSnake = (key: string) => key.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);

function convertKeys(value: unknown, convert: (key: string) => string): unknown {
  if (Array.isArray(value)) return value.map((item) => convertKeys(item, convert));
  if (!isPlainObject(value)) return value;
  return Object.fromEntries(Object.entries(value).map(([k, v]) => [convert(k), convertKeys(v, convert)]));
}

export function toCamel<T>(value: T): CamelCasedPropertiesDeep<T> {
  return convertKeys(value, snakeToCamel) as CamelCasedPropertiesDeep<T>;
}

export function toSnake<T>(value: T): SnakeCasedPropertiesDeep<T> {
  return convertKeys(value, camelToSnake) as SnakeCasedPropertiesDeep<T>;
}
