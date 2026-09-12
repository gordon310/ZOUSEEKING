#!/usr/bin/env node
import fs from "node:fs";
import { execFileSync } from "node:child_process";

const files = ["web/property-analysis.html", "web/report.html"];
const ignoredLine = /(?:<meta\b|aria-label=|data-i18n(?:-[\w-]+)?=|小象避坑|ZOUBEACON|<option value="(?:zh-CN|zh-Hant|en|ja)")/;

function findBare(source, file) {
  return source.split("\n").flatMap((line, index) => {
    if (!/[一-龥]/.test(line) || ignoredLine.test(line)) return [];
    return [{ file, line: index + 1, text: line.trim() }];
  });
}

function currentSource(file) {
  return fs.readFileSync(file, "utf8");
}

function baselineSource(file) {
  try {
    return execFileSync("git", ["show", `HEAD:${file}`], { encoding: "utf8" });
  } catch {
    return "";
  }
}

const current = files.flatMap((file) => findBare(currentSource(file), file));
const baseline = files.flatMap((file) => findBare(baselineSource(file), file));

console.log(`baseline bare Chinese lines: ${baseline.length}`);
console.log(`current bare Chinese lines: ${current.length}`);
if (current.length) {
  for (const item of current) console.log(`${item.file}:${item.line}: ${item.text}`);
  process.exitCode = 1;
} else {
  console.log("PASS: scanned C-end analysis and report pages contain no bare visible Chinese lines.");
}
