import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [inputPath, outputPath, previewDir] = process.argv.slice(2);
if (!inputPath || !outputPath || !previewDir) {
  throw new Error("Usage: node build_excel_report.mjs <data.json> <report.xlsx> <preview-dir>");
}

const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
const workbook = Workbook.create();
const font = "Arial";
const navy = "#16324F";
const blue = "#2F6690";
const paleBlue = "#EAF2F8";
const paleRed = "#FDECEC";
const paleGreen = "#E9F5EE";
const gray = "#667085";

const definitions = [
  ["Products", "Products", data.products, [
    ["organization", "Organization"], ["source", "Source"], ["product_id", "Product ID"],
    ["external_id", "External ID"], ["sku", "SKU"], ["name", "Product"], ["brand", "Brand"],
    ["category", "Category"], ["price", "Price"], ["currency", "Currency"],
    ["availability", "Availability"], ["quantity", "Quantity"], ["rating", "Rating"],
    ["review_count", "Reviews"], ["first_seen_at", "First seen"], ["last_seen_at", "Last seen"], ["url", "URL"],
  ]],
  ["Price Changes", "PriceChanges", data.price_changes, eventColumns()],
  ["New Products", "NewProducts", data.new_products, eventColumns()],
  ["Back in Stock", "BackInStock", data.back_in_stock, eventColumns()],
  ["Out of Stock", "OutOfStock", data.out_of_stock, eventColumns()],
  ["Missing Products", "MissingProducts", data.missing_products, eventColumns()],
  ["Scrape History", "ScrapeHistory", data.scrape_history, [
    ["run_id", "Run ID"], ["organization", "Organization"], ["source", "Source"], ["status", "Status"],
    ["started_at", "Started"], ["finished_at", "Finished"], ["duration_seconds", "Duration (sec)"],
    ["records_found", "Found"], ["records_accepted", "Accepted"], ["records_rejected", "Rejected"], ["error_count", "Errors"],
  ]],
  ["Data Quality", "DataQuality", data.data_quality, errorColumns()],
  ["Errors", "Errors", data.errors, errorColumns()],
];

const summary = workbook.worksheets.add("Summary");
summary.tabColor = navy;
summary.showGridLines = false;
summary.getRange("B2:H2").merge();
summary.getRange("B2").values = [["Product monitoring report"]];
summary.getRange("B2").format.font = { name: font, size: 16, bold: true, color: navy };
summary.getRange("B3:H3").format.borders = { bottom: { style: "thin", color: blue } };
summary.getRange("B4").values = [["Generated"]];
summary.getRange("C4").values = [[asDate(data.generated_at)]];
summary.getRange("C4").format.numberFormat = "yyyy-mm-dd hh:mm";
summary.getRange("B5").values = [["Applied filters"]];
summary.getRange("C5:H5").merge();
summary.getRange("C5").values = [[filterText(data.filters)]];
summary.getRange("B4:B5").format.font = { name: font, size: 10, bold: true, color: gray };
summary.getRange("C4:H5").format.font = { name: font, size: 10, color: "#1D2939" };

summary.getRange("B8:G8").values = [["Products", "Price changes", "New products", "Back in stock", "Out of stock", "Errors"]];
summary.getRange("B9:G9").formulas = [[
  "=COUNT(Products!C5:C10000)", "=COUNT('Price Changes'!D5:D10000)", "=COUNT('New Products'!D5:D10000)",
  "=COUNT('Back in Stock'!D5:D10000)", "=COUNT('Out of Stock'!D5:D10000)", "=COUNT(Errors!B5:B10000)",
]];
summary.getRange("B8:G8").format = { fill: navy, font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center" };
summary.getRange("B9:G9").format = { fill: paleBlue, font: { name: font, size: 14, bold: true, color: navy }, horizontalAlignment: "center", verticalAlignment: "center", numberFormat: "#,##0" };
summary.getRange("B8:G9").format.borders = { preset: "outside", style: "thin", color: "#B8C4CE" };
summary.getRange("B8:G8").format.rowHeight = 28;
summary.getRange("B9:G9").format.rowHeight = 32;
summary.getRange("B2:H12").format.font.name = font;
summary.getRange("B:B").format.columnWidth = 18;
summary.getRange("C:H").format.columnWidth = 17;

for (const [sheetName, tableName, rows, columns] of definitions) {
  const sheet = workbook.worksheets.add(sheetName);
  sheet.showGridLines = false;
  sheet.getRange("A2:H2").merge();
  sheet.getRange("A2").values = [[sheetName]];
  sheet.getRange("A2").format.font = { name: font, size: 14, bold: true, color: navy };
  sheet.getRange("A3:H3").format.borders = { bottom: { style: "thin", color: blue } };
  const headers = columns.map(([, label]) => label);
  const values = rows.map((row) => columns.map(([key]) => cellValue(row[key], key)));
  const matrix = [headers, ...values];
  const endColumn = columnName(headers.length);
  sheet.getRange(`A4:${endColumn}${4 + values.length}`).values = matrix;
  const header = sheet.getRange(`A4:${endColumn}4`);
  header.format = { fill: navy, font: { name: font, size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
  header.format.rowHeight = 30;
  if (values.length) {
    const table = sheet.tables.add(`A4:${endColumn}${4 + values.length}`, true, `${tableName}Table`);
    table.style = "TableStyleMedium2";
    table.showFilterButton = true;
    const body = sheet.getRange(`A5:${endColumn}${4 + values.length}`);
    body.format.font = { name: font, size: 10, color: "#1D2939" };
    body.format.verticalAlignment = "center";
    applyFormats(sheet, columns, values.length);
  } else {
    sheet.getRange("A5").values = [["No records for the selected filters"]];
    sheet.getRange("A5").format = { fill: "#F7F9FC", font: { name: font, size: 10, italic: true, color: gray } };
  }
  sheet.freezePanes.freezeRows(4);
  sheet.getUsedRange().format.autofitColumns();
  for (let col = 0; col < headers.length; col += 1) {
    const range = sheet.getRange(`${columnName(col + 1)}1:${columnName(col + 1)}${Math.max(5, 4 + values.length)}`);
    const current = range.format.columnWidth;
    range.format.columnWidth = Math.min(Math.max(current || 12, 11), columns[col][0] === "url" ? 42 : 28);
  }
  if (["Errors", "Data Quality"].includes(sheetName) && values.length) {
    sheet.getRange(`A5:${endColumn}${4 + values.length}`).conditionalFormats.addCustom("=LEN($H5)>0", { fill: paleRed });
  }
  if (sheetName === "Scrape History" && values.length) {
    sheet.getRange(`D5:D${4 + values.length}`).conditionalFormats.add("containsText", { text: "success", format: { fill: paleGreen } });
    sheet.getRange(`D5:D${4 + values.length}`).conditionalFormats.add("containsText", { text: "failed", format: { fill: paleRed, font: { color: "#B42318", bold: true } } });
  }
}

workbook.recalculate();
const summaryCheck = await workbook.inspect({ kind: "table", range: "Summary!B2:G9", include: "values,formulas", tableMaxRows: 12, tableMaxCols: 8 });
console.log(summaryCheck.ndjson);
const errorCheck = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 300 }, summary: "final formula error scan" });
console.log(errorCheck.ndjson);

await fs.mkdir(previewDir, { recursive: true });
for (const sheet of ["Summary", ...definitions.map(([name]) => name)]) {
  const preview = await workbook.render({ sheetName: sheet, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheet.replaceAll(" ", "_")}.png`), new Uint8Array(await preview.arrayBuffer()));
}
await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(outputPath);

function eventColumns() {
  return [["observed_at", "Observed"], ["organization", "Organization"], ["source", "Source"], ["product_id", "Product ID"],
    ["external_id", "External ID"], ["name", "Product"], ["brand", "Brand"], ["category", "Category"], ["currency", "Currency"],
    ["change_type", "Change type"], ["field", "Field"], ["old_value", "Old value"], ["new_value", "New value"],
    ["absolute_difference", "Difference"], ["percentage_change", "Change (%)"], ["url", "URL"]];
}

function errorColumns() {
  return [["created_at", "Created"], ["run_id", "Run ID"], ["organization", "Organization"], ["source", "Source"],
    ["external_id", "External ID"], ["stage", "Stage"], ["error_code", "Error code"], ["message", "Message"]];
}

function filterText(filters) {
  const active = Object.entries(filters).filter(([, value]) => value !== null && value !== "").map(([key, value]) => `${key}: ${value}`);
  return active.length ? active.join(", ") : "All organizations and sources";
}

function cellValue(value, key) {
  if (value === null || value === undefined) return null;
  if (key.endsWith("_at") || key === "started_at" || key === "finished_at") return asDate(value);
  return value;
}

function asDate(value) { return value ? new Date(value) : null; }

function applyFormats(sheet, columns, count) {
  columns.forEach(([key], index) => {
    const col = columnName(index + 1);
    const range = sheet.getRange(`${col}5:${col}${4 + count}`);
    if (key.endsWith("_at") || key === "started_at" || key === "finished_at") range.format.numberFormat = "yyyy-mm-dd hh:mm";
    if (["price", "absolute_difference"].includes(key)) range.format.numberFormat = "#,##0.00";
    if (key === "percentage_change") range.format.numberFormat = "0.00";
    if (["duration_seconds", "rating"].includes(key)) range.format.numberFormat = "0.00";
    if (["product_id", "run_id", "quantity", "review_count", "records_found", "records_accepted", "records_rejected", "error_count"].includes(key)) range.format.numberFormat = "#,##0";
  });
}

function columnName(index) {
  let name = "";
  while (index > 0) { index -= 1; name = String.fromCharCode(65 + (index % 26)) + name; index = Math.floor(index / 26); }
  return name;
}
