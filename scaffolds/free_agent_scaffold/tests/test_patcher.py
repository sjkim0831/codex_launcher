import json

from free_agent.config.presets import reset_ui_preset_catalog_cache
from free_agent.models import SymbolReference
from free_agent.editing.patcher import infer_replacement, propose_edit


def test_infer_replacement_from_goal() -> None:
    rule = infer_replacement("500 대신 401")
    assert rule is not None
    assert rule.before == "500"
    assert rule.after == "401"


def test_propose_edit_builds_diff() -> None:
    proposal = propose_edit(
        goal="500 대신 401",
        path="app.py",
        original_text="return 500\n",
    )
    assert proposal is not None
    assert "return 401" in proposal.updated_text
    assert "--- app.py" in proposal.diff


def test_propose_edit_respects_numeric_boundaries() -> None:
    proposal = propose_edit(
        goal="500 대신 401",
        path="app.py",
        original_text="return 5000\nreturn 500\n",
    )
    assert proposal is not None
    assert proposal.updated_text == "return 5000\nreturn 401\n"


def test_propose_edit_can_scope_to_named_symbol() -> None:
    source = (
        "def login():\n"
        "    return 500\n\n"
        "def logout():\n"
        "    return 500\n"
    )
    proposal = propose_edit(
        goal="login 함수에서 500 대신 401",
        path="app.py",
        original_text=source,
        available_symbols=[
            SymbolReference(name="login", kind="function", path="app.py", start_line=1, end_line=2),
            SymbolReference(name="logout", kind="function", path="app.py", start_line=4, end_line=5),
        ],
    )

    assert proposal is not None
    assert proposal.target_symbol == "login"
    assert proposal.updated_text == (
        "def login():\n"
        "    return 401\n\n"
        "def logout():\n"
        "    return 500\n"
    )


def test_propose_edit_can_insert_after_anchor() -> None:
    proposal = propose_edit(
        goal="\"return 500\" 다음 줄에 \"log_error()\" 추가",
        path="app.py",
        original_text="def login():\n    return 500\n",
    )

    assert proposal is not None
    assert proposal.updated_text == "def login():\n    return 500\n    log_error()\n"


def test_propose_edit_can_insert_after_all_matching_anchors() -> None:
    proposal = propose_edit(
        goal="모든 \"return 500\" 다음 줄에 \"log_error()\" 추가",
        path="app.py",
        original_text="def a():\n    return 500\n\ndef b():\n    return 500\n",
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "def a():\n"
        "    return 500\n"
        "    log_error()\n"
        "\n"
        "def b():\n"
        "    return 500\n"
        "    log_error()\n"
    )


def test_propose_edit_can_delete_matching_line() -> None:
    proposal = propose_edit(
        goal="\"debug = True\" 삭제",
        path="settings.py",
        original_text="debug = True\nmode = 'prod'\n",
    )

    assert proposal is not None
    assert proposal.updated_text == "mode = 'prod'\n"


def test_propose_edit_can_add_import_line() -> None:
    proposal = propose_edit(
        goal="\"import logging\" import 추가",
        path="service.py",
        original_text="import os\n\n\ndef login():\n    return 500\n",
    )

    assert proposal is not None
    assert proposal.updated_text == "import os\nimport logging\n\n\ndef login():\n    return 500\n"


def test_propose_edit_can_insert_before_return() -> None:
    proposal = propose_edit(
        goal="login 함수에서 \"audit()\" return 앞에 추가",
        path="service.py",
        original_text="def login():\n    x = 1\n    return x\n",
        available_symbols=[
            SymbolReference(name="login", kind="function", path="service.py", start_line=1, end_line=3),
        ],
    )

    assert proposal is not None
    assert proposal.updated_text == "def login():\n    x = 1\n    audit()\n    return x\n"


def test_propose_edit_can_insert_at_function_start() -> None:
    proposal = propose_edit(
        goal="login 함수 맨 앞에 \"audit_start()\" 추가",
        path="service.py",
        original_text="def login():\n    return 1\n",
        available_symbols=[
            SymbolReference(name="login", kind="function", path="service.py", start_line=1, end_line=2),
        ],
    )

    assert proposal is not None
    assert proposal.updated_text == "def login():\n    audit_start()\n    return 1\n"


def test_propose_edit_can_insert_at_function_end() -> None:
    proposal = propose_edit(
        goal="login 함수 맨 끝에 \"audit_end()\" 추가",
        path="service.py",
        original_text="def login():\n    x = 1\n    return x\n",
        available_symbols=[
            SymbolReference(name="login", kind="function", path="service.py", start_line=1, end_line=3),
        ],
    )

    assert proposal is not None
    assert proposal.updated_text == "def login():\n    x = 1\n    return x\n    audit_end()\n"


def test_propose_edit_can_add_import_from_line() -> None:
    proposal = propose_edit(
        goal="\"import { audit } from './audit'\" import 추가",
        path="service.ts",
        original_text="import fs from 'fs';\n\nconst login = () => {\n  return 1;\n};\n",
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "import fs from 'fs';\n"
        "import { audit } from './audit'\n"
        "\n"
        "const login = () => {\n"
        "  return 1;\n"
        "};\n"
    )


def test_propose_edit_avoids_duplicate_import() -> None:
    proposal = propose_edit(
        goal="\"import logging\" import 추가",
        path="service.py",
        original_text="import os\nimport logging\n",
    )

    assert proposal is None


def test_propose_edit_can_insert_before_bare_return_in_js() -> None:
    proposal = propose_edit(
        goal="login 함수에서 \"audit()\" return 앞에 추가",
        path="service.ts",
        original_text="const login = () => {\n  doThing();\n  return;\n};\n",
        available_symbols=[
            SymbolReference(name="login", kind="function", path="service.ts", start_line=1, end_line=4),
        ],
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "const login = () => {\n"
        "  doThing();\n"
        "  audit();\n"
        "  return;\n"
        "};\n"
    )


def test_propose_edit_can_insert_at_javascript_function_boundaries() -> None:
    start_proposal = propose_edit(
        goal="login 함수 맨 앞에 \"auditStart();\" 추가",
        path="service.ts",
        original_text="const login = async () => {\n  return 1;\n};\n",
        available_symbols=[
            SymbolReference(name="login", kind="function", path="service.ts", start_line=1, end_line=3),
        ],
    )
    end_proposal = propose_edit(
        goal="login 함수 맨 끝에 \"auditEnd();\" 추가",
        path="service.ts",
        original_text="const login = async () => {\n  return 1;\n};\n",
        available_symbols=[
            SymbolReference(name="login", kind="function", path="service.ts", start_line=1, end_line=3),
        ],
    )

    assert start_proposal is not None
    assert start_proposal.updated_text == (
        "const login = async () => {\n"
        "  auditStart();\n"
        "  return 1;\n"
        "};\n"
    )
    assert end_proposal is not None
    assert end_proposal.updated_text == (
        "const login = async () => {\n"
        "  return 1;\n"
        "  auditEnd();\n"
        "};\n"
    )


def test_propose_edit_preserves_semicolon_style_for_javascript_insert() -> None:
    proposal = propose_edit(
        goal="login 함수 맨 앞에 \"auditStart()\" 추가",
        path="service.ts",
        original_text="const login = async () => {\n  return 1;\n};\n",
        available_symbols=[
            SymbolReference(name="login", kind="function", path="service.ts", start_line=1, end_line=3),
        ],
    )

    assert proposal is not None
    assert "auditStart();" in proposal.updated_text


def test_propose_edit_can_insert_inside_python_if_block() -> None:
    proposal = propose_edit(
        goal="\"if is_ready:\" 다음 줄에 \"log_ready()\" 추가",
        path="service.py",
        original_text="if is_ready:\n    return 1\n",
    )

    assert proposal is not None
    assert proposal.updated_text == "if is_ready:\n    log_ready()\n    return 1\n"


def test_propose_edit_duplicate_check_is_scoped_to_target_symbol() -> None:
    source = (
        "def login():\n"
        "    return 1\n\n"
        "def logout():\n"
        "    audit()\n"
        "    return 2\n"
    )
    proposal = propose_edit(
        goal="login 함수 맨 앞에 \"audit()\" 추가",
        path="service.py",
        original_text=source,
        available_symbols=[
            SymbolReference(name="login", kind="function", path="service.py", start_line=1, end_line=2),
            SymbolReference(name="logout", kind="function", path="service.py", start_line=4, end_line=6),
        ],
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "def login():\n"
        "    audit()\n"
        "    return 1\n\n"
        "def logout():\n"
        "    audit()\n"
        "    return 2\n"
    )


def test_propose_edit_can_insert_jsx_without_semicolon() -> None:
    proposal = propose_edit(
        goal="\"<button>Save</button>\" 다음 줄에 \"<Badge />\" 추가",
        path="LoginPage.tsx",
        original_text=(
            "export function LoginPage() {\n"
            "  return (\n"
            "    <section>\n"
            "      <button>Save</button>\n"
            "    </section>\n"
            "  );\n"
            "}\n"
        ),
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "export function LoginPage() {\n"
        "  return (\n"
        "    <section>\n"
        "      <button>Save</button>\n"
        "      <Badge />\n"
        "    </section>\n"
        "  );\n"
        "}\n"
    )


def test_propose_edit_can_insert_type_declaration_after_imports() -> None:
    proposal = propose_edit(
        goal="\"type LoginProps = { disabled?: boolean }\" type 추가",
        path="LoginPage.tsx",
        original_text=(
            "import React from 'react';\n"
            "import { Button } from './Button';\n"
            "\n"
            "export function LoginPage() {\n"
            "  return <Button />;\n"
            "}\n"
        ),
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "import React from 'react';\n"
        "import { Button } from './Button';\n"
        "\n"
        "type LoginProps = { disabled?: boolean }\n"
        "\n"
        "export function LoginPage() {\n"
        "  return <Button />;\n"
        "}\n"
    )


def test_propose_edit_can_insert_jsx_attribute() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 \"disabled={isSaving}\" 속성 추가",
        path="LoginPage.tsx",
        original_text=(
            "export function LoginPage() {\n"
            "  return (\n"
            "    <section>\n"
            "      <Button variant=\"primary\">Save</Button>\n"
            "    </section>\n"
            "  );\n"
            "}\n"
        ),
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "export function LoginPage() {\n"
        "  return (\n"
        "    <section>\n"
        "      <Button variant=\"primary\" disabled={isSaving}>Save</Button>\n"
        "    </section>\n"
        "  );\n"
        "}\n"
    )


def test_propose_edit_can_connect_props_type_to_component_signature() -> None:
    proposal = propose_edit(
        goal="\"LoginPage\"에 \"LoginProps\" props 타입 연결",
        path="LoginPage.tsx",
        original_text=(
            "type LoginProps = { disabled?: boolean }\n"
            "\n"
            "export function LoginPage() {\n"
            "  return <Button />;\n"
            "}\n"
        ),
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "type LoginProps = { disabled?: boolean }\n"
        "\n"
        "export function LoginPage(props: LoginProps) {\n"
        "  return <Button />;\n"
        "}\n"
    )


def test_propose_edit_can_insert_attribute_into_multiline_jsx_tag() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 \"disabled={isSaving}\" 속성 추가",
        path="LoginPage.tsx",
        original_text=(
            "export function LoginPage() {\n"
            "  return (\n"
            "    <Button\n"
            "      variant=\"primary\"\n"
            "    >\n"
            "      Save\n"
            "    </Button>\n"
            "  );\n"
            "}\n"
        ),
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "export function LoginPage() {\n"
        "  return (\n"
        "    <Button\n"
        "      variant=\"primary\"\n"
        "      disabled={isSaving}\n"
        "    >\n"
        "      Save\n"
        "    </Button>\n"
        "  );\n"
        "}\n"
    )


def test_propose_edit_can_insert_attribute_into_self_closing_jsx_tag() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 \"disabled={isSaving}\" 속성 추가",
        path="LoginPage.tsx",
        original_text="<Button variant=\"primary\" />\n",
    )

    assert proposal is not None
    assert proposal.updated_text == "<Button variant=\"primary\" disabled={isSaving} />\n"


def test_propose_edit_can_connect_destructured_props_type_to_component_signature() -> None:
    proposal = propose_edit(
        goal="\"LoginPage\"에 \"{ disabled }\" 구조분해 \"LoginProps\" props 타입 연결",
        path="LoginPage.tsx",
        original_text=(
            "type LoginProps = { disabled?: boolean }\n"
            "\n"
            "export function LoginPage() {\n"
            "  return <Button />;\n"
            "}\n"
        ),
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "type LoginProps = { disabled?: boolean }\n"
        "\n"
        "export function LoginPage({ disabled }: LoginProps) {\n"
        "  return <Button />;\n"
        "}\n"
    )


def test_propose_edit_can_merge_classname_attribute() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 \"className=\\\"primary\\\"\" 속성 추가",
        path="LoginPage.tsx",
        original_text="<Button className=\"btn\" />\n",
    )

    assert proposal is not None
    assert proposal.updated_text == "<Button className=\"btn primary\" />\n"


def test_propose_edit_can_connect_destructured_props_with_default_values() -> None:
    proposal = propose_edit(
        goal="\"LoginPage\"에 \"{ disabled = false }\" 구조분해 \"LoginProps\" props 타입 연결",
        path="LoginPage.tsx",
        original_text=(
            "type LoginProps = { disabled?: boolean }\n"
            "\n"
            "export function LoginPage() {\n"
            "  return <Button />;\n"
            "}\n"
        ),
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "type LoginProps = { disabled?: boolean }\n"
        "\n"
        "export function LoginPage({ disabled = false }: LoginProps) {\n"
        "  return <Button />;\n"
        "}\n"
    )


def test_propose_edit_can_merge_classname_template_literal() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 \"className=\\\"primary\\\"\" 속성 추가",
        path="LoginPage.tsx",
        original_text="<Button className={`btn ${active ? 'on' : ''}`} />\n",
    )

    assert proposal is not None
    assert proposal.updated_text == "<Button className={`btn ${active ? 'on' : ''} primary`} />\n"


def test_propose_edit_can_merge_classname_with_clsx() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 \"className=\\\"primary\\\"\" 속성 추가",
        path="LoginPage.tsx",
        original_text="<Button className={clsx(\"btn\", isActive && \"active\")} />\n",
    )

    assert proposal is not None
    assert proposal.updated_text == "<Button className={clsx(\"btn\", isActive && \"active\", \"primary\")} />\n"


def test_propose_edit_can_connect_prop_usage_to_jsx() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 \"disabled\" props 사용 연결",
        path="LoginPage.tsx",
        original_text=(
            "export function LoginPage({ disabled }: LoginProps) {\n"
            "  return <Button variant=\"primary\">Save</Button>;\n"
            "}\n"
        ),
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "export function LoginPage({ disabled }: LoginProps) {\n"
        "  return <Button variant=\"primary\" disabled={disabled}>Save</Button>;\n"
        "}\n"
    )


def test_propose_edit_can_replace_conflicting_tailwind_tokens() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 \"className=\\\"px-4 bg-red-500\\\"\" 속성 추가",
        path="LoginPage.tsx",
        original_text="<Button className=\"btn px-2 text-sm bg-blue-500\" />\n",
    )

    assert proposal is not None
    assert proposal.updated_text == "<Button className=\"btn text-sm px-4 bg-red-500\" />\n"


def test_propose_edit_can_connect_value_prop_usage_to_jsx() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 \"label\" \"label\" props 사용 연결",
        path="LoginPage.tsx",
        original_text=(
            "export function LoginPage({ label }: LoginProps) {\n"
            "  return <Button>Save</Button>;\n"
            "}\n"
        ),
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "export function LoginPage({ label }: LoginProps) {\n"
        "  return <Button label={label}>Save</Button>;\n"
        "}\n"
    )


def test_propose_edit_can_connect_event_handler_prop_usage_to_jsx() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 \"onClick\" \"handleClick\" props 사용 연결",
        path="LoginPage.tsx",
        original_text=(
            "export function LoginPage({ handleClick }: LoginProps) {\n"
            "  return <Button>Save</Button>;\n"
            "}\n"
        ),
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "export function LoginPage({ handleClick }: LoginProps) {\n"
        "  return <Button onClick={handleClick}>Save</Button>;\n"
        "}\n"
    )


def test_propose_edit_can_connect_aria_prop_usage_to_jsx() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 \"aria-label\" \"label\" props 사용 연결",
        path="LoginPage.tsx",
        original_text="<Button />\n",
    )

    assert proposal is not None
    assert proposal.updated_text == "<Button aria-label={label} />\n"


def test_propose_edit_can_connect_data_prop_usage_to_jsx() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 \"data-testid\" \"testId\" props 사용 연결",
        path="LoginPage.tsx",
        original_text="<Button />\n",
    )

    assert proposal is not None
    assert proposal.updated_text == "<Button data-testid={testId} />\n"


def test_propose_edit_can_set_design_system_prop_value() -> None:
    proposal = propose_edit(
        goal="\"Button\"의 \"variant\"를 \"secondary\"로 변경",
        path="LoginPage.tsx",
        original_text="<Button variant=\"primary\">Save</Button>\n",
    )

    assert proposal is not None
    assert proposal.updated_text == "<Button variant=\"secondary\">Save</Button>\n"


def test_propose_edit_can_apply_prop_usage_to_all_matching_tags() -> None:
    proposal = propose_edit(
        goal="모든 \"Button\"에 \"disabled\" props 사용 연결",
        path="LoginPage.tsx",
        original_text=(
            "<div>\n"
            "  <Button>Save</Button>\n"
            "  <Button variant=\"primary\">Cancel</Button>\n"
            "</div>\n"
        ),
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "<div>\n"
        "  <Button disabled={disabled}>Save</Button>\n"
        "  <Button variant=\"primary\" disabled={disabled}>Cancel</Button>\n"
        "</div>\n"
    )


def test_propose_edit_can_apply_multiple_ui_rules_in_one_goal() -> None:
    proposal = propose_edit(
        goal="\"Button\"의 \"variant\"를 \"secondary\"로 변경하고 \"Button\"에 \"className=\\\"bg-gray-100\\\"\" 속성 추가",
        path="LoginPage.tsx",
        original_text="<Button variant=\"primary\" className=\"btn bg-blue-500\">Save</Button>\n",
    )

    assert proposal is not None
    assert proposal.updated_text == "<Button variant=\"secondary\" className=\"btn bg-gray-100\">Save</Button>\n"


def test_propose_edit_can_insert_conditional_rendering_block() -> None:
    proposal = propose_edit(
        goal="\"<section>\" 다음 줄에 \"{isAdmin && <Badge />}\" 조건부 렌더링 추가",
        path="LoginPage.tsx",
        original_text=(
            "export function LoginPage() {\n"
            "  return (\n"
            "    <section>\n"
            "      <Button>Save</Button>\n"
            "    </section>\n"
            "  );\n"
            "}\n"
        ),
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "export function LoginPage() {\n"
        "  return (\n"
        "    <section>\n"
        "      {isAdmin && <Badge />}\n"
        "      <Button>Save</Button>\n"
        "    </section>\n"
        "  );\n"
        "}\n"
    )


def test_propose_edit_can_insert_conditional_rendering_for_all_matching_anchors() -> None:
    proposal = propose_edit(
        goal="모든 \"<section>\" 다음 줄에 \"{isAdmin && <Badge />}\" 조건부 렌더링 추가",
        path="LoginPage.tsx",
        original_text=(
            "<div>\n"
            "  <section>\n"
            "    <Button>Save</Button>\n"
            "  </section>\n"
            "  <section>\n"
            "    <Button>Cancel</Button>\n"
            "  </section>\n"
            "</div>\n"
        ),
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "<div>\n"
        "  <section>\n"
        "    {isAdmin && <Badge />}\n"
        "    <Button>Save</Button>\n"
        "  </section>\n"
        "  <section>\n"
        "    {isAdmin && <Badge />}\n"
        "    <Button>Cancel</Button>\n"
        "  </section>\n"
        "</div>\n"
    )


def test_propose_edit_unescapes_attribute_values_in_goal() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 \"className=\\\"bg-gray-100\\\"\" 속성 추가",
        path="LoginPage.tsx",
        original_text="<Button>Save</Button>\n",
    )

    assert proposal is not None
    assert proposal.updated_text == "<Button className=\"bg-gray-100\">Save</Button>\n"


def test_propose_edit_can_apply_variant_classname_and_prop_usage_across_clauses() -> None:
    proposal = propose_edit(
        goal=(
            "\"Button\"의 \"variant\"를 \"secondary\"로 변경하고 "
            "\"Button\"에 \"className=\\\"bg-gray-100\\\"\" 속성 추가하고 "
            "\"Button\"에 \"disabled\" props 사용 연결"
        ),
        path="LoginPage.tsx",
        original_text="<Button variant=\"primary\" className=\"btn bg-blue-500\">Save</Button>\n",
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "<Button variant=\"secondary\" className=\"btn bg-gray-100\" disabled={disabled}>Save</Button>\n"
    )


def test_propose_edit_can_apply_explicit_ui_preset_rule() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 \"variant=secondary\" \"className=bg-gray-100\" \"disabled=disabled\" UI preset 적용",
        path="LoginPage.tsx",
        original_text="<Button variant=\"primary\" className=\"btn bg-blue-500\">Save</Button>\n",
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "<Button variant=\"secondary\" className=\"btn bg-gray-100\" disabled={disabled}>Save</Button>\n"
    )


def test_propose_edit_can_apply_named_secondary_button_preset() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 secondary 버튼 스타일 preset 적용",
        path="LoginPage.tsx",
        original_text="<Button variant=\"primary\" className=\"btn bg-blue-500\">Save</Button>\n",
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "<Button variant=\"secondary\" className=\"btn bg-gray-100\">Save</Button>\n"
    )


def test_propose_edit_can_apply_named_loading_button_preset() -> None:
    proposal = propose_edit(
        goal="\"Button\"에 loading 버튼 동작 preset 적용",
        path="LoginPage.tsx",
        original_text="<Button>Save</Button>\n",
    )

    assert proposal is not None
    assert proposal.updated_text == (
        "<Button disabled={isLoading} aria-busy={isLoading}>Save</Button>\n"
    )


def test_propose_edit_can_use_overridden_ui_preset_catalog(tmp_path, monkeypatch) -> None:
    preset_path = tmp_path / "ui_presets.json"
    preset_path.write_text(
        json.dumps(
            {
                "compact 버튼 스타일": {
                    "class_name": "px-2 py-1 text-xs"
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FREE_AGENT_UI_PRESETS_PATH", str(preset_path))
    reset_ui_preset_catalog_cache()

    try:
        proposal = propose_edit(
            goal="\"Button\"에 compact 버튼 스타일 preset 적용",
            path="LoginPage.tsx",
            original_text="<Button className=\"btn px-4 text-sm\">Save</Button>\n",
        )
    finally:
        reset_ui_preset_catalog_cache()

    assert proposal is not None
    assert proposal.updated_text == "<Button className=\"btn px-2 py-1 text-xs\">Save</Button>\n"
