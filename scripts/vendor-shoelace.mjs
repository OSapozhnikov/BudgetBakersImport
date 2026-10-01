import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const pkgRoot = join(root, "node_modules", "@shoelace-style", "shoelace");
const pkg = JSON.parse(readFileSync(join(pkgRoot, "package.json"), "utf8"));
const src = join(pkgRoot, "cdn");
const dest = join(root, "app", "static", "vendor", "shoelace");

rmSync(dest, { recursive: true, force: true });
mkdirSync(dest, { recursive: true });
cpSync(src, dest, { recursive: true });
writeFileSync(join(dest, "VERSION.txt"), `${pkg.version}\n`, "utf8");
console.log(`Vendored Shoelace ${pkg.version} -> ${dest}`);
