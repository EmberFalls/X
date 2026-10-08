import fs from "node:fs/promises";
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

const root = "E:/python_projects/EDI-1";
const outputDir = `${root}/outputs`;
const navy = "#17365D";
const blue = "#D9EAF7";
const pale = "#F4F8FC";
const gold = "#FCE4D6";
const green = "#E2F0D9";
const font = "Arial";

function parseCsv(text) {
  const rows = [];
  let row = [], value = "", quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { value += '"'; i += 1; }
      else if (c === '"') quoted = false;
      else value += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') { row.push(value); value = ""; }
    else if (c === '\n') { row.push(value.replace(/\r$/, "")); rows.push(row); row = []; value = ""; }
    else value += c;
  }
  if (value.length || row.length) { row.push(value.replace(/\r$/, "")); rows.push(row); }
  const headers = rows.shift();
  return rows.filter(r => r.length === headers.length).map(r => Object.fromEntries(headers.map((h, i) => [h, r[i]])));
}
function num(v) { const n = Number(v); return Number.isFinite(n) ? n : null; }
function yes(v) { return String(v).toLowerCase() === "true"; }
function pct(v) { return Math.round(v * 1000) / 10; }
function col(n) { let s = ""; for (n += 1; n; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s; return s; }
function mean(rows, key) { const xs = rows.map(r => num(r[key])).filter(v => v !== null); return xs.length ? xs.reduce((a,b) => a + b, 0) / xs.length : null; }
function metricRow(rows) {
  return [
    rows.length,
    pct(rows.filter(r => yes(r.schema_valid)).length / rows.length),
    pct(rows.filter(r => yes(r.backtest_completed)).length / rows.length),
    pct(rows.filter(r => yes(r.strategy_match)).length / rows.length),
    pct(rows.filter(r => yes(r.risk_profile_match)).length / rows.length),
    Math.round(mean(rows, "latency_ms") || 0),
  ];
}
function addHeading(sheet, address, text, width) {
  const cell = sheet.getRange(address);
  cell.values = [[text]];
  cell.format = { fill: navy, font: { name: font, size: 11, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
  cell.format.rowHeight = 28;
  if (width) sheet.getRange(`${address.split(":")[0]}:${col(width - 1)}${address.match(/\d+/)[0]}`).merge();
}
function styleTable(sheet, startRow, headers, data, headerFill = navy) {
  const endRow = startRow + data.length;
  const endCol = col(headers.length - 1);
  sheet.getRange(`A${startRow}:${endCol}${startRow}`).values = [headers];
  sheet.getRange(`A${startRow}:${endCol}${startRow}`).format = { fill: headerFill, font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", color: "#A6A6A6", style: "thin" } };
  sheet.getRange(`A${startRow}:${endCol}${startRow}`).format.rowHeight = 32;
  if (data.length) {
    sheet.getRange(`A${startRow + 1}:${endCol}${endRow}`).values = data;
    sheet.getRange(`A${startRow + 1}:${endCol}${endRow}`).format = { font: { name: font, size: 10 }, verticalAlignment: "center", wrapText: true, borders: { preset: "all", color: "#D9E2F3", style: "thin" } };
    for (let r = startRow + 1; r <= endRow; r += 2) sheet.getRange(`A${r}:${endCol}${r}`).format.fill = pale;
  }
  return endRow;
}

await fs.mkdir(outputDir, { recursive: true });
const [heuristicText, llmText, promptsText] = await Promise.all([
  fs.readFile(`${outputDir}/paper_eval_heuristic_500.csv`, "utf8"),
  fs.readFile(`${outputDir}/paper_eval_llm_500_final.csv`, "utf8"),
  fs.readFile(`${root}/evaluation_prompts_50.json`, "utf8"),
]);
const heuristic = parseCsv(heuristicText);
const llm = parseCsv(llmText);
const prompts = JSON.parse(promptsText);
const all = [...heuristic, ...llm];
const workbook = Workbook.create();

// Paper tables: compact, copy-ready summaries and clear provenance.
const paper = workbook.worksheets.add("Paper Tables");
paper.showGridLines = false;
paper.tabColor = navy;
paper.getRange("A1:H1").merge();
paper.getRange("A1").values = [["SimuTrade — Natural-Language Strategy Mapping Evaluation"]];
paper.getRange("A1").format = { fill: navy, font: { name: font, size: 16, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center" };
paper.getRange("A1:H1").format.rowHeight = 30;
paper.getRange("A2:H2").merge();
paper.getRange("A2").values = [["Evaluation design: 50 prompts × 5 NSE tickers × 2 repetitions = 500 rows per requested path; 1,000 rows overall. Daily OHLCV, 1 Jan 2023–31 Dec 2024."]];
paper.getRange("A2").format = { font: { name: font, size: 10, color: "#404040", italic: true }, horizontalAlignment: "left", verticalAlignment: "center", wrapText: true };
paper.getRange("A2:H2").format.rowHeight = 28;
paper.getRange("A4:H4").merge();
paper.getRange("A4").values = [["Table 1. Mapping and execution results by requested path and actual mapping source"]];
paper.getRange("A4").format = { font: { name: font, size: 12, bold: true, color: navy } };
const summaryGroups = [
  ["Deterministic fallback", "heuristic_fallback", heuristic],
  ["LLM (Groq) requested", "llm", llm.filter(r => r.actual_mapping_source === "llm")],
  ["LLM (Groq) requested", "heuristic_fallback", llm.filter(r => r.actual_mapping_source === "heuristic_fallback")],
];
const summaryData = summaryGroups.map(([requested, source, rows]) => [requested, source, ...metricRow(rows)]);
const summaryEnd = styleTable(paper, 5, ["Requested mapping path", "Actual mapping source", "Rows", "Schema valid (%)", "Backtest completed (%)", "Strategy match (%)", "Risk-profile match (%)", "Mean latency (ms)"], summaryData);
paper.getRange(`A${summaryEnd + 1}:H${summaryEnd + 1}`).merge();
paper.getRange(`A${summaryEnd + 1}`).values = [["Note: The requested LLM path is separated by actual source. Rows falling back because of provider rate limits remain explicitly labelled as heuristic_fallback; see Row Results for each fallback reason."]];
paper.getRange(`A${summaryEnd + 1}`).format = { fill: gold, font: { name: font, size: 9, color: "#7F6000", italic: true }, wrapText: true, verticalAlignment: "center" };
paper.getRange(`A${summaryEnd + 1}:H${summaryEnd + 1}`).format.rowHeight = 34;
const categoryStart = summaryEnd + 3;
paper.getRange(`A${categoryStart}:H${categoryStart}`).merge();
paper.getRange(`A${categoryStart}`).values = [["Table 2. Prompt-family outcomes by requested mapping path"]];
paper.getRange(`A${categoryStart}`).format = { font: { name: font, size: 12, bold: true, color: navy } };
const categories = [...new Set(all.map(r => r.category))];
const categoryData = [
  ...categories.map(category => ["Deterministic fallback", category, ...metricRow(heuristic.filter(r => r.category === category)).slice(0, 5)]),
  ...categories.map(category => ["LLM (Groq) requested", category, ...metricRow(llm.filter(r => r.category === category)).slice(0, 5)]),
];
const categoryEnd = styleTable(paper, categoryStart + 1, ["Requested path", "Prompt family", "Rows", "Schema valid (%)", "Backtest completed (%)", "Strategy match (%)", "Risk-profile match (%)"], categoryData);
paper.getRange(`A${categoryEnd + 2}:H${categoryEnd + 2}`).merge();
paper.getRange(`A${categoryEnd + 2}`).values = [["Tickers: RELIANCE.NS, TCS.NS, INFY.NS, HDFCBANK.NS, and ICICIBANK.NS. Strategy and risk-profile matches compare the produced configuration with the pre-specified expected label in the 50-prompt test set."]];
paper.getRange(`A${categoryEnd + 2}`).format = { fill: green, font: { name: font, size: 9, color: "#385723", italic: true }, wrapText: true, verticalAlignment: "center" };
paper.getRange(`A${categoryEnd + 2}:H${categoryEnd + 2}`).format.rowHeight = 32;
for (const [c, width] of [["A",24],["B",24],["C",10],["D",15],["E",20],["F",17],["G",20],["H",16]]) paper.getRange(`${c}:${c}`).format.columnWidth = width;
paper.freezePanes.freezeRows(5);

// Row-level data for auditability and later paper analysis.
const rowsSheet = workbook.worksheets.add("Row Results");
rowsSheet.showGridLines = false;
rowsSheet.tabColor = "#5B9BD5";
const sourceColumns = [
  ["evaluation_id", "Evaluation ID"], ["requested_mapping_path", "Requested Path"], ["actual_mapping_source", "Actual Source"], ["repeat", "Run"], ["prompt_id", "Prompt ID"], ["prompt", "Prompt"], ["category", "Prompt Family"], ["difficulty", "Difficulty"], ["ticker", "Ticker"], ["interval", "Interval"], ["expected_strategy", "Expected Strategy"], ["expected_risk_profile", "Expected Risk"], ["produced_strategy", "Produced Strategy"], ["produced_risk_profile", "Produced Risk"], ["strategy_match", "Strategy Match"], ["risk_profile_match", "Risk Match"], ["schema_valid", "Schema Valid"], ["backtest_completed", "Backtest Completed"], ["latency_ms", "Latency (ms)"], ["fallback_reason", "Fallback Reason"], ["llm_model", "LLM Model"], ["backtest_error", "Backtest Error"], ["total_return_pct", "Total Return (%)"], ["max_drawdown_pct", "Max Drawdown (%)"], ["sharpe_ratio", "Sharpe Ratio"], ["win_rate_pct", "Win Rate (%)"], ["total_trades", "Total Trades"], ["final_value", "Final Value"], ["buy_hold_value", "Buy-and-hold Value"],
];
rowsSheet.getRange(`A1:${col(sourceColumns.length - 1)}1`).values = [sourceColumns.map(([, display]) => display)];
rowsSheet.getRange(`A1:${col(sourceColumns.length - 1)}1`).format = { fill: navy, font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", color: "#A6A6A6", style: "thin" } };
rowsSheet.getRange(`A1:${col(sourceColumns.length - 1)}1`).format.rowHeight = 38;
const dataMatrix = all.map(r => sourceColumns.map(([key]) => {
  if (["strategy_match", "risk_profile_match", "schema_valid", "backtest_completed"].includes(key)) return yes(r[key]) ? "Yes" : "No";
  if (["repeat", "latency_ms", "total_trades"].includes(key)) return num(r[key]);
  if (["total_return_pct", "max_drawdown_pct", "sharpe_ratio", "win_rate_pct", "final_value", "buy_hold_value"].includes(key)) return num(r[key]);
  return r[key] ?? "";
}));
const lastRow = dataMatrix.length + 1;
rowsSheet.getRange(`A2:${col(sourceColumns.length - 1)}${lastRow}`).values = dataMatrix;
rowsSheet.getRange(`A2:${col(sourceColumns.length - 1)}${lastRow}`).format = { font: { name: font, size: 9 }, verticalAlignment: "center", borders: { preset: "all", color: "#E7E6E6", style: "thin" } };
rowsSheet.getRange(`A2:${col(sourceColumns.length - 1)}${lastRow}`).format.wrapText = true;
for (let r = 2; r <= lastRow; r += 2) rowsSheet.getRange(`A${r}:${col(sourceColumns.length - 1)}${r}`).format.fill = pale;
for (const idx of [14,15,16,17]) rowsSheet.getRange(`${col(idx)}2:${col(idx)}${lastRow}`).format.horizontalAlignment = "center";
for (const idx of [22,23,24,25]) rowsSheet.getRange(`${col(idx)}2:${col(idx)}${lastRow}`).format.numberFormat = "0.00";
for (const idx of [27,28]) rowsSheet.getRange(`${col(idx)}2:${col(idx)}${lastRow}`).format.numberFormat = "#,##0.00";
for (const [index, width] of [[0,30],[1,19],[2,18],[3,7],[4,10],[5,55],[6,18],[7,12],[8,15],[9,10],[10,20],[11,16],[12,20],[13,16],[14,14],[15,12],[16,13],[17,18],[18,13],[19,22],[20,24],[21,20],[22,16],[23,18],[24,13],[25,14],[26,13],[27,14],[28,18]]) rowsSheet.getRange(`${col(index)}:${col(index)}`).format.columnWidth = width;
rowsSheet.freezePanes.freezeRows(1);
rowsSheet.freezePanes.freezeColumns(5);

// Prompt set makes expected labels explicit and lets the tables be reproduced.
const promptSheet = workbook.worksheets.add("Prompt Set");
promptSheet.showGridLines = false;
promptSheet.tabColor = "#70AD47";
const promptHeaders = ["Prompt ID", "Prompt Family", "Difficulty", "Natural-language Prompt", "Expected Strategy", "Expected Risk Profile"];
const promptData = prompts.map(p => [p.prompt_id, p.category, p.difficulty, p.prompt, p.expected_strategy, p.expected_risk_profile]);
styleTable(promptSheet, 1, promptHeaders, promptData);
for (const [c, width] of [["A",11],["B",20],["C",12],["D",90],["E",22],["F",20]]) promptSheet.getRange(`${c}:${c}`).format.columnWidth = width;
promptSheet.getRange(`A2:F${promptData.length + 1}`).format.rowHeight = 35;
promptSheet.freezePanes.freezeRows(1);

// Method sheet documents the exact protocol and labels in a reusable form.
const method = workbook.worksheets.add("Method");
method.showGridLines = false;
method.tabColor = "#ED7D31";
method.getRange("A1:D1").merge();
method.getRange("A1").values = [["Evaluation Protocol and Field Definitions"]];
method.getRange("A1").format = { fill: navy, font: { name: font, size: 15, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center" };
method.getRange("A1:D1").format.rowHeight = 30;
const methodData = [
  ["Prompt set", "50 pre-specified natural-language prompts, with 10 prompts each for trend, mean-reversion, reversal/RSI, MACD, and breakout families."],
  ["Replication", "Five NSE tickers × two independent repetitions = 500 rows per requested mapping path."],
  ["Tickers", "RELIANCE.NS; TCS.NS; INFY.NS; HDFCBANK.NS; ICICIBANK.NS."],
  ["Market data", "Daily OHLCV data for 1 Jan 2023–31 Dec 2024; 490 observations per ticker in the completed run."],
  ["Requested paths", "Deterministic heuristic fallback and LLM (Groq) mapping."],
  ["Actual-source label", "actual_mapping_source reports whether a row was directly produced by the LLM or by the deterministic fallback. This avoids treating a provider-rate-limited fallback as a direct LLM result."],
  ["Validity", "Schema valid means the produced configuration conforms to the accepted configuration schema. Backtest completed means the deterministic backtest returned an outcome without a recorded error."],
  ["Match measures", "Strategy and risk-profile match compare each produced configuration against the expected labels specified in the Prompt Set sheet."],
  ["Source files", "paper_eval_heuristic_500.csv and paper_eval_llm_500_final.csv, combined in the Row Results sheet."],
];
styleTable(method, 3, ["Field", "Definition"], methodData);
method.getRange("A:A").format.columnWidth = 23;
method.getRange("B:B").format.columnWidth = 110;
method.getRange("A4:B12").format.rowHeight = 32;
method.freezePanes.freezeRows(3);

workbook.recalculate();
const report = await workbook.inspect({ kind: "table", range: "Paper Tables!A1:H22", include: "values" });
console.log(JSON.stringify(report, null, 2));
const preview = await workbook.render({ sheetName: "Paper Tables", autoCrop: "all", scale: 1, format: "png" });
await fs.writeFile(`${outputDir}/SimuTrade_Evaluation_Paper_Tables.png`, new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(`${outputDir}/SimuTrade_Evaluation_Results.xlsx`);
console.log(`Wrote ${outputDir}/SimuTrade_Evaluation_Results.xlsx`);
