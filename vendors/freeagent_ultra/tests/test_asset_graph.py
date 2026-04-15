import os
import sys
from pathlib import Path

VENDOR_ROOT = Path(__file__).resolve().parents[1]
if str(VENDOR_ROOT) not in sys.path:
    sys.path.insert(0, str(VENDOR_ROOT))

from freeagent.graph.nodes import asset_manager as asset_manager_module
from freeagent.graph.nodes.memory import memory_node
from freeagent.tools.asset_tools import (
    audit_asset_consistency,
    format_asset_summary,
    save_carbonet_inventory,
    scan_carbonet_assets,
)


def test_save_carbonet_inventory_creates_file(tmp_path):
    assets = [{"id": "SENSOR-001", "type": "SENSOR", "status": "OK", "name": "Main"}]

    result = save_carbonet_inventory(assets, root_path=str(tmp_path))

    inventory_file = tmp_path / "asset_inventory.json"
    assert inventory_file.exists()
    assert "Successfully saved 1 assets" in result
    assert '"SENSOR-001"' in inventory_file.read_text(encoding="utf-8")


def test_save_carbonet_inventory_falls_back_when_target_is_read_only(tmp_path, monkeypatch):
    assets = [{"id": "SENSOR-001", "type": "SENSOR", "status": "OK", "name": "Main"}]
    fallback_dir = tmp_path / "fallback"
    monkeypatch.setenv("CARBONET_INVENTORY_FALLBACK_DIR", str(fallback_dir))

    result = save_carbonet_inventory(assets, root_path="/proc/invalid-carbonet-root")

    inventory_file = fallback_dir / "asset_inventory.json"
    assert inventory_file.exists()
    assert "fallback from /proc/invalid-carbonet-root/asset_inventory.json" in result


def test_format_asset_summary_includes_issues():
    audit_report = audit_asset_consistency(
        [
            {"id": "SENSOR-001", "type": "SENSOR", "status": "OK", "name": "Main"},
            {"id": "SENSOR-002", "type": "SENSOR", "status": "DRIFTED", "name": "HVAC"},
        ]
    )

    summary = format_asset_summary(audit_report, "Successfully saved 2 assets")

    assert "2 assets" in summary
    assert "Drift detected in SENSOR-002" in summary
    assert "Successfully saved 2 assets" in summary


def test_asset_manager_persists_inventory_and_memory(monkeypatch, tmp_path):
    carbonet_root = tmp_path / "carbonet"
    feature_dir = carbonet_root / "frontend" / "src" / "features" / "sensor-list"
    feature_dir.mkdir(parents=True)
    (feature_dir / "SensorListMigrationPage.tsx").write_text("export default function SensorList() {}\n", encoding="utf-8")

    logic_dir = carbonet_root / "modules" / "carbonet-builder-observability" / "src" / "main" / "java" / "egovframework" / "com" / "common" / "trace"
    logic_dir.mkdir(parents=True)
    (logic_dir / "AssetScanProvider.java").write_text("class AssetScanProvider {}\n", encoding="utf-8")

    monkeypatch.setattr(
        asset_manager_module,
        "scan_carbonet_assets",
        lambda: scan_carbonet_assets(str(carbonet_root)),
    )
    monkeypatch.setattr(
        asset_manager_module,
        "save_carbonet_inventory",
        lambda assets: save_carbonet_inventory(assets, str(carbonet_root)),
    )

    state = {
        "user_input": "자산 관리 시스템에서 현재 가동 중인 센서 목록을 스캔하고 인벤토리에 반영해줘.",
        "task_plan": [],
        "current_task": "ASSET: Scan assets in carbonet",
        "research_data": None,
        "code_result": None,
        "final_answer": None,
        "memory": {},
        "next": None,
        "history": [],
        "assets": [],
        "asset_audit": None,
        "inventory_result": None,
    }

    asset_command = asset_manager_module.asset_manager_node(state)
    asset_updates = asset_command.update
    memory_command = memory_node({**state, **asset_updates})
    memory_updates = memory_command.update

    assert asset_updates["asset_audit"]["total"] >= 3
    assert "Successfully saved" in asset_updates["inventory_result"]
    assert os.path.exists(carbonet_root / "asset_inventory.json")
    assert "Scanned" in memory_updates["final_answer"]
