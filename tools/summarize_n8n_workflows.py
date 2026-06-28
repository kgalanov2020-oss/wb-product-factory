from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def summarize_workflow(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])
    return {
        "file": str(path),
        "name": data.get("name") or path.stem,
        "active": data.get("active"),
        "nodes": [
            {
                "name": node.get("name"),
                "type": node.get("type"),
                "operation": node.get("parameters", {}).get("operation"),
                "resource": node.get("parameters", {}).get("resource"),
                "method": node.get("parameters", {}).get("method"),
                "url": node.get("parameters", {}).get("url"),
                "document_id": _pick(
                    node.get("parameters", {}),
                    "documentId",
                    "sheetId",
                    "spreadsheetId",
                ),
                "sheet_name": _pick(
                    node.get("parameters", {}),
                    "sheetName",
                    "range",
                    "worksheet",
                ),
                "code_preview": _code_preview(node.get("parameters", {})),
            }
            for node in nodes
        ],
        "connections": data.get("connections", {}),
    }


def _pick(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = data.get(key)
        if value:
            return value
    return None


def _code_preview(parameters: dict[str, Any]) -> str | None:
    code = parameters.get("jsCode") or parameters.get("functionCode")
    if not code:
        return None
    compact = " ".join(str(code).split())
    return compact[:500]


def main() -> None:
    root = Path("n8n_exports")
    files = sorted(root.glob("*.json"))
    if not files:
        print("Put exported n8n workflow JSON files into n8n_exports/")
        return
    summary = [summarize_workflow(path) for path in files]
    Path("docs").mkdir(exist_ok=True)
    output = Path("docs/n8n-workflows-summary.json")
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output} for {len(files)} workflow(s)")


if __name__ == "__main__":
    main()
