from pathlib import Path

from free_agent.repo.symbols import SymbolIndexer


def test_symbol_indexer_extracts_python_functions_and_classes(tmp_path: Path) -> None:
    target = tmp_path / "service.py"
    target.write_text(
        "class LoginService:\n"
        "    def create(self):\n"
        "        return 1\n\n"
        "def login():\n"
        "    return 2\n",
        encoding="utf-8",
    )

    symbols = SymbolIndexer().extract(workspace=str(tmp_path), relative_path="service.py")

    names = [symbol.name for symbol in symbols]
    assert "LoginService" in names
    assert "create" in names
    assert "login" in names


def test_symbol_indexer_extracts_javascript_symbols(tmp_path: Path) -> None:
    target = tmp_path / "service.ts"
    target.write_text(
        "export class LoginService {\n"
        "  create() {\n"
        "    return 1;\n"
        "  }\n"
        "}\n"
        "function login() {\n"
        "  return 2;\n"
        "}\n"
        "const logout = async () => {\n"
        "  return 3;\n"
        "};\n",
        encoding="utf-8",
    )

    symbols = SymbolIndexer().extract(workspace=str(tmp_path), relative_path="service.ts")

    names = [symbol.name for symbol in symbols]
    assert "LoginService" in names
    assert "login" in names
    assert "logout" in names


def test_symbol_indexer_extracts_javascript_methods(tmp_path: Path) -> None:
    target = tmp_path / "service.ts"
    target.write_text(
        "export class LoginService {\n"
        "  async create() {\n"
        "    return 1;\n"
        "  }\n"
        "}\n"
        "const handlers = {\n"
        "  login() {\n"
        "    return 2;\n"
        "  },\n"
        "  logout: async () => {\n"
        "    return 3;\n"
        "  },\n"
        "};\n",
        encoding="utf-8",
    )

    symbols = SymbolIndexer().extract(workspace=str(tmp_path), relative_path="service.ts")

    names = [symbol.name for symbol in symbols]
    assert "create" in names
    assert "login" in names
    assert "logout" in names


def test_symbol_indexer_classifies_react_components_and_hooks(tmp_path: Path) -> None:
    target = tmp_path / "LoginPage.tsx"
    target.write_text(
        "export function LoginPage() {\n"
        "  return <section />;\n"
        "}\n"
        "const ProfileCard = () => {\n"
        "  return <div />;\n"
        "};\n"
        "const useLogin = () => {\n"
        "  return { ok: true };\n"
        "};\n",
        encoding="utf-8",
    )

    symbols = SymbolIndexer().extract(workspace=str(tmp_path), relative_path="LoginPage.tsx")
    kinds = {symbol.name: symbol.kind for symbol in symbols}

    assert kinds["LoginPage"] == "component"
    assert kinds["ProfileCard"] == "component"
    assert kinds["useLogin"] == "hook"


def test_symbol_indexer_extracts_exported_and_typed_arrow_functions(tmp_path: Path) -> None:
    target = tmp_path / "LoginPage.tsx"
    target.write_text(
        "type LoginProps = { disabled?: boolean };\n"
        "export const LoginPage: React.FC<LoginProps> = ({ disabled }) => {\n"
        "  return <section data-disabled={disabled} />;\n"
        "};\n"
        "export const useLoginState = () => {\n"
        "  return { ok: true };\n"
        "};\n",
        encoding="utf-8",
    )

    symbols = SymbolIndexer().extract(workspace=str(tmp_path), relative_path="LoginPage.tsx")
    kinds = {symbol.name: symbol.kind for symbol in symbols}

    assert kinds["LoginPage"] == "component"
    assert kinds["useLoginState"] == "hook"


def test_symbol_indexer_extracts_function_expression_assignments(tmp_path: Path) -> None:
    target = tmp_path / "service.ts"
    target.write_text(
        "export const login = function () {\n"
        "  return 1;\n"
        "};\n"
        "const logout: Handler = async function () {\n"
        "  return 2;\n"
        "};\n",
        encoding="utf-8",
    )

    symbols = SymbolIndexer().extract(workspace=str(tmp_path), relative_path="service.ts")

    names = [symbol.name for symbol in symbols]
    assert "login" in names
    assert "logout" in names
