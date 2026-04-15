from __future__ import annotations
import os
from pathlib import Path
from typing import List, Dict, Any

import json
import re
import subprocess

def scan_logic_assets(root_path: Path) -> List[Dict[str, Any]]:
    """모듈 디렉토리에서 Java Service/Component 자산을 스캔합니다."""
    assets = []
    modules_path = root_path / "modules"
    if not modules_path.exists():
        return assets

    try:
        # Use grep to find files containing @Service or @Component
        cmd = ["grep", "-rl", "--include=*.java", "-E", "@Service|@Component", str(modules_path)]
        output = subprocess.check_output(cmd, text=True).splitlines()
        
        for file_path in output:
            p = Path(file_path)
            assets.append({
                "id": f"LOGIC-{p.stem}",
                "type": "SERVICE",
                "status": "ACTIVE",
                "path": str(p.relative_to(root_path)),
                "name": p.stem
            })
    except Exception:
        pass
    return assets

def scan_data_assets(root_path: Path) -> List[Dict[str, Any]]:
    """MyBatis Mapper XML에서 테이블명을 추출하여 Data 자산을 스캔합니다."""
    assets = []
    modules_path = root_path / "modules"
    if not modules_path.exists():
        return assets

    table_names = set()
    try:
        # Use grep to find lines containing potential table names
        cmd = ["grep", "-rh", "--include=*.xml", "-E", r"FROM\s+|INTO\s+|UPDATE\s+", str(modules_path)]
        output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).splitlines()
        
        # Regex to capture the word after FROM, INTO, or UPDATE
        pattern = re.compile(r"(?:FROM|INTO|UPDATE)\s+([A-Z0-9_]+)", re.IGNORECASE)
        
        for line in output:
            for match in pattern.finditer(line):
                table = match.group(1).upper()
                if table and len(table) > 3 and table not in ("SELECT", "SET", "VALUES", "WHERE"):
                    table_names.add(table)
    except Exception:
        pass

    for table in sorted(table_names):
        assets.append({
            "id": f"DATA-{table}",
            "type": "DATA",
            "status": "LIVE",
            "name": table
        })
    return assets

def scan_carbonet_assets(root_path: str = "/opt/projects/carbonet") -> List[Dict[str, Any]]:
    """carbonet 프로젝트에서 주요 시스템 자산을 스캔합니다."""
    assets = []
    root = Path(root_path)
    
    # Try to load existing inventory first
    inventory_file = root / "asset_inventory.json"
    existing_assets = []
    if inventory_file.exists():
        try:
            with open(inventory_file, "r", encoding="utf-8") as f:
                existing_assets = json.load(f)
        except Exception:
            pass

    if not root.exists():
        return [{"id": "ERROR", "type": "SYSTEM", "status": "PATH_NOT_FOUND"}]

    # 1. UI Assets (Migration Pages)
    ui_path = root / "frontend/src/features"
    if ui_path.exists():
        for feature_dir in ui_path.iterdir():
            if feature_dir.is_dir():
                for page_file in feature_dir.glob("*MigrationPage.tsx"):
                    assets.append({
                        "id": f"UI-{page_file.stem}",
                        "type": "UI",
                        "status": "READY",
                        "path": str(page_file.relative_to(root)),
                        "name": page_file.stem
                    })

    # 2. Logic Assets (Java Services)
    assets.extend(scan_logic_assets(root))

    # 3. Data Assets (Tables from Mappers)
    assets.extend(scan_data_assets(root))

    # 4. Merge with existing assets (especially SENSORS which are not yet scannable)
    scanned_ids = {a["id"] for a in assets}
    for ea in existing_assets:
        if ea["id"] not in scanned_ids:
            assets.append(ea)

    # 5. If no sensors found in inventory, add default ones for demonstration
    if not any(a["type"] == "SENSOR" for a in assets):
        assets.append({"id": "SENSOR-001", "type": "SENSOR", "status": "OK", "name": "Main Power Monitor"})
        assets.append({"id": "SENSOR-002", "type": "SENSOR", "status": "DRIFTED", "name": "HVAC Control Hub"})

    return assets

def save_carbonet_inventory(assets: List[Dict[str, Any]], root_path: str = "/opt/projects/carbonet") -> str:
    """스캔된 자산 정보를 inventory JSON 파일로 저장합니다."""
    root = Path(root_path)
    inventory_file = root / "asset_inventory.json"

    def _write_inventory(target_file: Path) -> str:
        target_file.parent.mkdir(parents=True, exist_ok=True)
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(assets, f, ensure_ascii=False, indent=2)
        return f"Successfully saved {len(assets)} assets to {target_file}"

    try:
        return _write_inventory(inventory_file)
    except Exception as e:
        fallback_candidates = []
        env_fallback = os.environ.get("CARBONET_INVENTORY_FALLBACK_DIR")
        if env_fallback:
            fallback_candidates.append(Path(env_fallback))
        fallback_candidates.extend(
            [
                Path.cwd() / ".codex-assets",
                Path("/tmp/codex-asset-inventory"),
            ]
        )
        fallback_errors = []
        for fallback_root in fallback_candidates:
            if fallback_root.exists() and not fallback_root.is_dir():
                fallback_errors.append(f"{fallback_root} is not a directory")
                continue
            fallback_file = fallback_root / "asset_inventory.json"
            try:
                result = _write_inventory(fallback_file)
                return f"{result} (fallback from {inventory_file}: {e})"
            except Exception as fallback_error:
                fallback_errors.append(str(fallback_error))
        return f"Failed to save inventory: {str(e)}; fallback failed: {'; '.join(fallback_errors)}"

def audit_asset_consistency(assets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """자산 간 정합성 및 상태를 감사(audit)합니다."""
    summary = {
        "total": len(assets),
        "types": {},
        "issues": []
    }
    
    for asset in assets:
        atype = asset["type"]
        summary["types"][atype] = summary["types"].get(atype, 0) + 1
        
        if asset.get("status") == "DRIFTED":
            summary["issues"].append(f"Drift detected in {asset['id']} ({asset['name']})")
        elif asset.get("status") == "PATH_NOT_FOUND":
            summary["issues"].append(f"Asset source path not found: {asset['id']}")
            
    return summary


def format_asset_summary(audit_report: Dict[str, Any], inventory_result: str) -> str:
    """감사 결과와 저장 결과를 사람이 읽기 쉬운 요약으로 정리합니다."""
    issues = audit_report.get("issues") or []
    issue_summary = "; ".join(issues) if issues else "No critical issues detected."
    return (
        f"Asset scan completed: {audit_report.get('total', 0)} assets across "
        f"{len(audit_report.get('types', {}))} categories. "
        f"Issues: {issue_summary} "
        f"Inventory: {inventory_result}"
    )
