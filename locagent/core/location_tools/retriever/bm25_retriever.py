import os
import json
import pickle
import Stemmer
import fnmatch
import mimetypes
from typing import Dict, List, Optional

from llama_index.core import SimpleDirectoryReader
from llama_index.core import Document
from llama_index.core.node_parser import SimpleFileNodeParser
from llama_index.retrievers.bm25 import BM25Retriever
from locagent.core.repo_index.index.epic_split import EpicSplitter

from locagent.core.dependency_graph import RepoEntitySearcher
from locagent.core.dependency_graph.traverse_graph import is_test_file
from locagent.core.dependency_graph.build_graph import (
    NODE_TYPE_DIRECTORY,
    NODE_TYPE_FILE,
    NODE_TYPE_CLASS,
    NODE_TYPE_FUNCTION,
)

import warnings

warnings.simplefilter('ignore', FutureWarning)

NTYPES = [
    NODE_TYPE_DIRECTORY,
    NODE_TYPE_FILE,
    NODE_TYPE_FUNCTION,
    NODE_TYPE_CLASS,
]


def _persist_bm25_retriever_without_mmindex(retriever: BM25Retriever, persist_path: str) -> None:
    """Persist a llama-index BM25Retriever without triggering bm25s mmindex creation.

    bm25s.BM25.save() generates a `corpus.mmindex.json` via tqdm by default, which can
    create multiprocessing semaphores and has been observed to segfault on interpreter
    shutdown in our environment (Python 3.14/WSL2). We avoid that path by:
    - saving bm25 scores/vocab/params via bm25.save(corpus=None)
    - saving the corpus ourselves as `corpus.jsonl`
    - saving llama-index's retriever args as `retriever.json`

    This preserves BM25Retriever.from_persist_dir() compatibility.
    """

    persist_path = os.fspath(persist_path)
    os.makedirs(persist_path, exist_ok=True)

    # Save bm25 index arrays/vocab/params, but skip corpus to avoid mmindex generation.
    retriever.bm25.save(persist_path, corpus=None)

    corpus_path = os.path.join(persist_path, "corpus.jsonl")
    corpus = getattr(retriever, "corpus", None)
    if corpus is None:
        raise ValueError("BM25Retriever.corpus is missing; cannot persist BM25 corpus.")

    with open(corpus_path, "wt", encoding="utf-8") as f:
        for i, doc in enumerate(corpus):
            # Match bm25s.BM25.save() behavior: allow strings or mappings.
            if isinstance(doc, str):
                doc = {"id": i, "text": doc}
            elif not isinstance(doc, (dict, list, tuple)):
                # Skip unsupported docs to match bm25s' tolerant behavior.
                continue
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")

    retriever_path = os.path.join(persist_path, "retriever.json")
    with open(retriever_path, "w", encoding="utf-8") as f:
        json.dump(retriever.get_persist_args(), f, indent=2)


def build_code_retriever_from_repo(repo_path,
                                   similarity_top_k=10,
                                   min_chunk_size=100,
                                   chunk_size=500,
                                   max_chunk_size=2000,
                                   hard_token_limit=2000,
                                   max_chunks=200,
                                   persist_path=None,
                                   show_progress=False,
                                   ):
    # print(repo_path)
    # Only extract file name and type to not trigger unnecessary embedding jobs
    def file_metadata_func(file_path: str) -> Dict:
        # print(file_path)
        file_path = file_path.replace(repo_path, '')
        if file_path.startswith('/'):
            file_path = file_path[1:]

        test_patterns = [
            '**/test/**',
            '**/tests/**',
            '**/test_*.py',
            '**/*_test.py',
        ]
        category = (
            'test'
            if any(fnmatch.fnmatch(file_path, pattern) for pattern in test_patterns)
            else 'implementation'
        )

        return {
            'file_path': file_path,
            'file_name': os.path.basename(file_path),
            'file_type': mimetypes.guess_type(file_path)[0],
            'category': category,
        }

    reader = SimpleDirectoryReader(
        input_dir=repo_path,
        exclude=[
            '**/test/**',
            '**/tests/**',
            '**/test_*.py',
            '**/*_test.py',
        ],
        file_metadata=file_metadata_func,
        filename_as_id=True,
        required_exts=['.py'],
        recursive=True,
    )
    docs = reader.load_data()
    
    if not docs:
        raise ValueError(f"No Python files found in {repo_path} (excluding test directories)")

    splitter = EpicSplitter(
        min_chunk_size=min_chunk_size,
        chunk_size=chunk_size,
        max_chunk_size=max_chunk_size,
        hard_token_limit=hard_token_limit,
        max_chunks=max_chunks,
        repo_path=repo_path,
    )
    prepared_nodes = splitter.get_nodes_from_documents(docs, show_progress=show_progress)

    if not prepared_nodes:
        raise ValueError(f"Code splitter produced 0 nodes from {len(docs)} Python files - files may be empty or unparseable")

    # BM25Retriever.from_defaults uses bool(nodes) which is False for empty list,
    # causing confusing "pass exactly one of index, nodes, or docstore" error
    retriever = BM25Retriever.from_defaults(
        nodes=prepared_nodes,
        similarity_top_k=similarity_top_k,
        stemmer=Stemmer.Stemmer("english"),
        language="english",
    )
    if persist_path:
        _persist_bm25_retriever_without_mmindex(retriever, persist_path)
    return retriever
    # keyword = 'FORBIDDEN_ALIAS_PATTERN'
    # retrieved_nodes = retriever.retrieve(keyword)


def build_retriever_from_persist_dir(path: str):
    retriever = BM25Retriever.from_persist_dir(path)
    return retriever


def build_module_retriever_from_graph(graph_path: Optional[str] = None,
                                      entity_searcher: Optional[RepoEntitySearcher] = None,
                                      search_scope: str = 'all',
                                      # enum = {'function', 'class', 'file', 'all'}
                                      similarity_top_k: int = 10,

                                      ):
    assert search_scope in NTYPES or search_scope == 'all'
    assert graph_path or isinstance(entity_searcher, RepoEntitySearcher)

    if graph_path:
        G = pickle.load(open(graph_path, "rb"))
        entity_searcher = RepoEntitySearcher(G)
    else:
        G = entity_searcher.G

    selected_nodes = list()
    for nid in G:
        if is_test_file(nid): continue

        ndata = entity_searcher.get_node_data([nid])[0]
        ndata['nid'] = nid  # add `nid` property
        if search_scope == 'all':  # and ndata['type'] in NTYPES[2:]
            selected_nodes.append(ndata)
        elif ndata['type'] == search_scope:
            selected_nodes.append(ndata)

    # initialize node parser
    splitter = SimpleFileNodeParser()
    documents = [Document(text=t['nid']) for t in selected_nodes]
    nodes = splitter.get_nodes_from_documents(documents)

    # We can pass in the index, docstore, or list of nodes to create the retriever
    retriever = BM25Retriever.from_defaults(
        nodes=nodes,
        similarity_top_k=similarity_top_k,
        stemmer=Stemmer.Stemmer("english"),
        language="english",
    )

    return retriever
