"""
Tree-sitter AST-Aware Diff Chunking & Call-Graph Query Engine.

Parses source code into Abstract Syntax Trees (ASTs) using language-specific
grammars (Python, JavaScript). Extracts declared symbols and outbound function
calls via Tree-sitter S-expression queries, enabling Cross-File Call-Graph RAG.
"""

import logging
import re
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Initialize Tree-sitter parsers and queries dynamically
PARSERS: Dict[str, Any] = {}
LANGUAGES: Dict[str, Any] = {}
CALL_QUERIES: Dict[str, Any] = {}

try:
    from tree_sitter import Language, Parser, Query, QueryCursor
    import tree_sitter_python as tspython
    import tree_sitter_javascript as tsjs

    py_lang = Language(tspython.language())
    js_lang = Language(tsjs.language())

    LANGUAGES["python"] = py_lang
    LANGUAGES["javascript"] = js_lang

    PARSERS["python"] = Parser(py_lang)
    PARSERS["javascript"] = Parser(js_lang)

    # Tree-sitter S-expression queries to extract outbound function & method calls
    CALL_QUERIES["javascript"] = Query(js_lang, """
    (call_expression
      function: [
        (identifier) @callee
        (member_expression property: (property_identifier) @callee)
      ]
    )
    """)

    CALL_QUERIES["python"] = Query(py_lang, """
    (call
      function: [
        (identifier) @callee
        (attribute attribute: (identifier) @callee)
      ]
    )
    """)

    logger.info("[Tree-sitter] Successfully initialized Python and JavaScript AST parsers and call queries.")
except Exception as e:
    logger.warning(f"[Tree-sitter] Failed to initialize native tree-sitter grammars: {e}. Utilizing fallback parsers.")

class CodeChunk:
    """Represents a syntactically coherent code block (function, class, method)."""
    def __init__(
        self,
        file_path: str,
        name: str,
        node_type: str,
        start_line: int,
        end_line: int,
        code: str,
        declared_symbols: List[str],
        called_symbols: List[str]
    ):
        self.file_path = file_path
        self.name = name
        self.node_type = node_type
        self.start_line = start_line
        self.end_line = end_line
        self.code = code
        self.declared_symbols = declared_symbols
        self.called_symbols = called_symbols

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "name": self.name,
            "node_type": self.node_type,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "code": self.code,
            "declared_symbols": self.declared_symbols,
            "called_symbols": self.called_symbols,
        }

def get_language_from_path(file_path: str) -> Optional[str]:
    ext = file_path.lower().split(".")[-1] if "." in file_path else ""
    if ext in ["py", "pyw"]:
        return "python"
    elif ext in ["js", "jsx", "mjs", "cjs", "ts", "tsx"]:
        return "javascript"
    return None

def extract_called_symbols_from_node(node: Any, code_bytes: bytes, language: str) -> List[str]:
    """
    Executes Tree-sitter S-expression query to extract outbound function/method calls
    within a specific AST node.
    """
    query = CALL_QUERIES.get(language)
    if not query:
        # Fallback regex extraction if query is unavailable
        text = code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        matches = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", text)
        return list(dict.fromkeys(matches))

    try:
        from tree_sitter import QueryCursor
        cursor = QueryCursor(query)
        captures = cursor.captures(node)

        called: List[str] = []
        for cap_name, nodes in captures.items():
            for n in nodes:
                callee_name = code_bytes[n.start_byte:n.end_byte].decode("utf-8", errors="replace")
                if callee_name and callee_name not in called:
                    called.append(callee_name)
        return called
    except Exception as e:
        logger.debug(f"[Tree-sitter Query] Error executing query cursor on {language}: {e}")
        text = code_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        matches = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", text)
        return list(dict.fromkeys(matches))

def chunk_file_by_ast(file_path: str, code_content: str) -> List[CodeChunk]:
    """
    Chunks an entire source file by semantic AST boundaries (functions, classes, methods),
    extracting declared identifiers and outbound called symbols for each chunk.
    """
    language = get_language_from_path(file_path)
    lines = code_content.splitlines()

    if not language or language not in PARSERS:
        # Fallback chunk for unsupported files
        called = list(dict.fromkeys(re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", code_content)))
        return [
            CodeChunk(
                file_path=file_path,
                name="module_root",
                node_type="module",
                start_line=1,
                end_line=len(lines) or 1,
                code=code_content,
                declared_symbols=[],
                called_symbols=called
            )
        ]

    parser = PARSERS[language]
    code_bytes = code_content.encode("utf-8")
    try:
        tree = parser.parse(code_bytes)
    except Exception as e:
        logger.warning(f"[Tree-sitter] Failed to parse AST for {file_path}: {e}")
        return []

    chunks: List[CodeChunk] = []

    def get_node_snippet(node: Any) -> str:
        node_lines = lines[node.start_point.row:node.end_point.row + 1]
        return "\n".join(node_lines)

    def extract_symbols_and_chunk(node: Any, name: str, node_type: str):
        start_row = node.start_point.row + 1
        end_row = node.end_point.row + 1
        snippet = get_node_snippet(node)

        # Extract outbound calls
        outbound_calls = extract_called_symbols_from_node(node, code_bytes, language)
        called_filtered = [c for c in outbound_calls if c != name]

        chunks.append(CodeChunk(
            file_path=file_path,
            name=name,
            node_type=node_type,
            start_line=start_row,
            end_line=end_row,
            code=snippet,
            declared_symbols=[name] if name and name != "anonymous" else [],
            called_symbols=called_filtered
        ))

    def visit(node: Any):
        if language == "javascript":
            if node.type in {"function_declaration", "method_definition", "class_declaration"}:
                id_node = node.child_by_field_name("name")
                name = code_bytes[id_node.start_byte:id_node.end_byte].decode("utf-8", errors="replace") if id_node else "anonymous"
                extract_symbols_and_chunk(node, name, node.type)
                return  # Sub-functions or nested expressions handled within chunk

            elif node.type in {"lexical_declaration", "variable_declaration"}:
                for decl in node.children:
                    if decl.type == "variable_declarator":
                        val = decl.child_by_field_name("value")
                        if val and val.type in {"arrow_function", "function_expression"}:
                            name_node = decl.child_by_field_name("name")
                            name = code_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace") if name_node else "anonymous"
                            extract_symbols_and_chunk(node, name, val.type)
                            return

        elif language == "python":
            if node.type in {"function_definition", "async_function_definition", "class_definition"}:
                id_node = node.child_by_field_name("name")
                name = code_bytes[id_node.start_byte:id_node.end_byte].decode("utf-8", errors="replace") if id_node else "anonymous"
                extract_symbols_and_chunk(node, name, node.type)
                return

        for child in node.children:
            visit(child)

    visit(tree.root_node)

    # Fallback to module-level chunk if no top-level functions were defined
    if not chunks and code_content.strip():
        all_calls = extract_called_symbols_from_node(tree.root_node, code_bytes, language)
        chunks.append(CodeChunk(
            file_path=file_path,
            name="module_root",
            node_type="module",
            start_line=1,
            end_line=len(lines) or 1,
            code=code_content,
            declared_symbols=[],
            called_symbols=all_calls
        ))

    return chunks

def map_diff_to_ast_scopes(file_path: str, diff_content: str, full_file_content: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Maps modified diff lines to AST scopes with both declared and called symbols.
    """
    code_to_parse = full_file_content
    if not code_to_parse:
        reconstructed_lines = []
        for line in diff_content.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                reconstructed_lines.append(line[1:])
            elif line.startswith(" ") or not (line.startswith("-") or line.startswith("@")):
                reconstructed_lines.append(line[1:] if line.startswith(" ") else line)
        code_to_parse = "\n".join(reconstructed_lines)

    if not code_to_parse.strip():
        return []

    chunks = chunk_file_by_ast(file_path, code_to_parse)
    return [c.to_dict() for c in chunks]
