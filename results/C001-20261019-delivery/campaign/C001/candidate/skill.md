---
name: spreadsheet-workflow
description: Use for spreadsheet editing, formula construction, workbook transformation, formatting, and spreadsheet analysis tasks.
---

# Spreadsheet Workflow

Use this workflow for general spreadsheet tasks. Apply only the steps relevant to the requested change.

1. Inspect workbook sheets, dimensions, headers, existing formulas, styles, and representative rows before editing.
2. Translate the request into explicit target sheets, ranges, transformations, and preservation constraints. Keep the requested output cells separate from source data.
3. Choose a method suited to the workbook. Use formulas when the workbook should remain dynamically linked; use a script or spreadsheet library for large, repeated, or structural transformations. When a script is used, compute target values in Python and write them as literals unless the task explicitly requires a formula—this avoids fragility from array-formula syntax differences, implicit-intersection behavior, or recalculation engine variations. When deleting rows, always iterate from the bottom of the sheet upward so row indices do not shift beneath you.
4. Preserve unrelated values, formulas, formatting, merged cells, and sheet structure. Avoid broad rewrites when a bounded update is sufficient.
5. Validate the saved workbook by reopening it, checking the target range and neighboring cells, and confirming the file is valid. Recalculate formulas with an available spreadsheet engine when formula results matter.
6. Before finishing, compare the output against the original constraints and report the saved file path and any limitation that prevents validation.
