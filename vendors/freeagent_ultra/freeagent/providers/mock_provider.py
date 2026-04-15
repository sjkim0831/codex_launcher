from __future__ import annotations
from .base import BaseProvider

class MockProvider(BaseProvider):
    name = "mock"
    
    def __init__(self, model: str = "mock"):
        self.model = model

    def available(self) -> bool:
        return True

    def generate(self, prompt: str, **kwargs) -> str:
        pl = prompt.lower()
        
        # 1. Routing logic
        if "classify the user request" in pl or "router for an ai agent" in pl:
            if any(k in pl for k in ("자산", "asset")):
                return "asset"
            if "research" in pl:
                return "research"
            return "coding"
            
        # 2. Planning logic
        if "break down the user's request" in pl or "planner" in pl:
            if any(k in pl for k in ("자산", "asset")):
                return "ASSET: Scan assets in carbonet\nRESEARCH: Audit drift in SENSOR-002\nCODING: Fix inventory sync logic"
            return "RESEARCH: Analysis\nCODING: Fix"
            
        # 3. Researcher analysis
        if "technical finding report" in pl or "professional researcher" in pl:
            return "RESEARCH FINDINGS: Found related asset mapping in SystemAssetInventoryMapper.xml and SensorAddMigrationPage.tsx. The schema expects 'asset_id' and 'status' fields."

        # 4. Asset Manager analysis
        if "expert asset manager" in pl:
            return "ANALYSIS: SENSOR-002 shows drift. Proposed plan:\nRESEARCH: Audit drift in SENSOR-002 source files\nCODING: Fix inventory sync logic for drifted sensors"

        # 5. Coder logic
        if "expert software engineer" in pl:
            return "ACTION: calibrate_sensor\nFILE: frontend/src/features/sensor-list/SensorListMigrationPage.tsx\nPATCH_HINT: Update sensor sync logic to handle drift."

        # 6. Explain logic
        if "explain" in pl:
            return "SUMMARY: This file appears to be a component or service related to the requested symbol."

        # 7. Legacy/Fallback fixes
        if "401" in pl and "500" in pl:
            return "ACTION: backend_status_fix\nPATCH_HINT: unauthorized->401\nTEST_HINT: pytest -q"
        if "button" in pl and ("toast" in pl or "fetch" in pl):
            return "ACTION: react_button_fetch_toast\nPATCH_HINT: add button, loading state, fetch, toast\nTEST_HINT: npm test"
            
        return "ACTION: generic_minimal_safe_change\nPATCH_HINT: minimal patch\nTEST_HINT: pytest -q"
