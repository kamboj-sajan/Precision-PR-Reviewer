"""
LangChain Precision Retrieval Pipeline with Cross-File Call-Graph RAG.
Coordinates semantic retrieval from ChromaDB, Tree-sitter AST-guided context extraction,
and cross-file inbound caller resolution.
"""

import logging
from typing import Dict, Any, List
from langchain_core.prompts import PromptTemplate
from app.db.chroma_client import chroma_manager
from app.rag.chunking_stub import parse_unified_diff
from app.rag.ast_chunker import map_diff_to_ast_scopes

logger = logging.getLogger(__name__)

# Template incorporating both vector architectural rules and cross-file inbound callers
REVIEW_PROMPT_TEMPLATE = """You are a Principal Software Engineer performing a precision-based code review.

### RETRIEVED ARCHITECTURAL & SECURITY CONTEXT (from ChromaDB Vector Store):
{retrieved_context}

### CROSS-FILE INBOUND CALLERS (Call-Graph RAG Context):
{inbound_callers_context}

### SYNTACTIC & AST SCOPES IDENTIFIED (Tree-sitter):
{ast_scopes}

### TARGET PULL REQUEST METADATA:
Repository: {repository}
PR #{pr_id}: {title}
Author: {author}
Commit: {commit_sha}

### GIT DIFF UNDER REVIEW:
{diff}

### REVIEW INSTRUCTIONS:
1. Compare the diff against the retrieved architectural and security guidelines.
2. Check if modifications to declared functions break contracts, signatures, or semantics for any retrieved CROSS-FILE INBOUND CALLERS.
3. For each violation or area of improvement, point to the EXACT line number.
4. Suggest concrete, safe replacement code anchored in the identified AST function scopes.
5. Output your evaluation in structured JSON format.
"""

class PrecisionRAGPipeline:
    def __init__(self):
        self.prompt = PromptTemplate(
            template=REVIEW_PROMPT_TEMPLATE,
            input_variables=[
                "retrieved_context",
                "inbound_callers_context",
                "ast_scopes",
                "repository",
                "pr_id",
                "title",
                "author",
                "commit_sha",
                "diff"
            ]
        )

    def execute(self, pr_id: int, repository: str, commit_sha: str, title: str, author: str, diff: str) -> Dict[str, Any]:
        """
        Executes the 5-stage Call-Graph RAG data flow:
        1. Parsing: Break diff into AST hunks, files, and Tree-sitter syntax nodes.
        2. Call-Graph Analysis: Find inbound callers across the codebase for modified functions.
        3. Semantic Query Formulation: Formulate query incorporating diff and AST scopes.
        4. Vector Retrieval: Query ChromaDB for matching architectural/security rules.
        5. Prompt Assembly: Inject call graph, vector rules, and AST scopes into LangChain template.
        """
        logger.info(f"[RAG Pipeline] Starting precision review for PR #{pr_id} on {repository}")

        # --- STAGE 1: Syntax & AST Parsing (Tree-sitter) ---
        parsed_files = parse_unified_diff(diff)
        hunk_count = sum(len(f.hunks) for f in parsed_files)
        logger.info(f"[RAG Pipeline - Stage 1] Parsed {len(parsed_files)} modified files across {hunk_count} hunks.")

        all_ast_scopes = []
        modified_declared_symbols = []

        for file_diff in parsed_files:
            file_path = file_diff.new_path or file_diff.old_path
            scopes = map_diff_to_ast_scopes(file_path, diff)
            for s in scopes:
                s["file_path"] = file_path
                all_ast_scopes.append(s)
                for sym in s.get("declared_symbols", []):
                    if sym not in modified_declared_symbols:
                        modified_declared_symbols.append((sym, file_path))

        logger.info(f"[RAG Pipeline - Stage 1] Tree-sitter identified {len(all_ast_scopes)} AST scopes and {len(modified_declared_symbols)} declared functions.")

        # --- STAGE 2: Cross-File Call-Graph Inbound Caller Resolution ---
        inbound_callers = []
        for sym_name, origin_file in modified_declared_symbols:
            callers = chroma_manager.find_inbound_callers(sym_name, exclude_file=origin_file)
            for c in callers:
                if c not in inbound_callers:
                    inbound_callers.append(c)

        logger.info(f"[RAG Pipeline - Stage 2] Retrieved {len(inbound_callers)} cross-file inbound callers.")

        # Format inbound callers for prompt injection
        if inbound_callers:
            formatted_callers = []
            for c in inbound_callers:
                formatted_callers.append(
                    f"- In `{c['file_path']}`, `{c['caller_name']}` (lines {c['start_line']}-{c['end_line']}) calls modified `{c['called_symbol']}`:\n"
                    f"```\n{c['code']}\n```"
                )
            inbound_callers_str = "\n".join(formatted_callers)
        else:
            inbound_callers_str = "No cross-file inbound callers detected for modified symbols."

        # --- STAGE 3: Semantic Query Formulation from Diff & AST ---
        query_terms = [title]
        for scope in all_ast_scopes:
            query_terms.append(f"{scope.get('name', '')} {scope.get('node_type', '')}")

        for f in parsed_files:
            query_terms.append(f.new_path)
            for hunk in f.hunks:
                added_lines = [l[1:].strip() for l in hunk.content if l.startswith("+") and not l.startswith("+++")]
                query_terms.extend(added_lines[:5])

        semantic_query = " ".join(query_terms)[:500] or "code review security best practices"
        logger.info(f"[RAG Pipeline - Stage 3] Formulated semantic query with AST context: {semantic_query[:100]}...")

        # --- STAGE 4: Context Retrieval from ChromaDB ---
        retrieval_results = chroma_manager.query_similar_context(semantic_query, n_results=3)
        retrieved_docs = retrieval_results.get("documents", [[]])[0]
        retrieved_metas = retrieval_results.get("metadatas", [[]])[0]

        formatted_context_list = []
        for i, doc in enumerate(retrieved_docs):
            meta = retrieved_metas[i] if i < len(retrieved_metas) else {}
            rule_id = meta.get("rule_id", f"RULE-{i+1}")
            formatted_context_list.append(f"- [{rule_id}] {doc}")

        retrieved_context_str = "\n".join(formatted_context_list) or "No specific architectural rule triggered; apply general best practices."
        logger.info(f"[RAG Pipeline - Stage 4] Retrieved {len(retrieved_docs)} contextual rules from ChromaDB.")

        # Format AST scopes for prompt injection
        formatted_scopes = []
        for s in all_ast_scopes:
            formatted_scopes.append(f"- File: `{s['file_path']}`, Scope: `{s['name']}` ({s['node_type']}) [Lines {s['start_line']}-{s['end_line']}]")
        ast_scopes_str = "\n".join(formatted_scopes) or "No enclosing function/class scopes detected."

        # --- STAGE 5: Assemble LangChain Prompt ---
        assembled_prompt = self.prompt.format(
            retrieved_context=retrieved_context_str,
            inbound_callers_context=inbound_callers_str,
            ast_scopes=ast_scopes_str,
            repository=repository,
            pr_id=pr_id,
            title=title,
            author=author,
            commit_sha=commit_sha,
            diff=diff
        )
        logger.info("[RAG Pipeline - Stage 5] LangChain precision prompt assembled with Call-Graph RAG context.")

        return {
            "parsed_files": parsed_files,
            "ast_scopes": all_ast_scopes,
            "inbound_callers": inbound_callers,
            "inbound_callers_count": len(inbound_callers),
            "retrieved_context": retrieved_docs,
            "retrieved_context_count": len(retrieved_docs),
            "assembled_prompt": assembled_prompt
        }

rag_pipeline = PrecisionRAGPipeline()
