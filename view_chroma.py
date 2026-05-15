#!/usr/bin/env python3
"""Script to view complete Chroma vector database contents including vectors, metadata, and content"""

import chromadb
from pathlib import Path
import argparse
import sys
import numpy as np


def group_by_source(results):
    """Group documents by their source file"""
    grouped = {}
    
    for i, doc_id in enumerate(results['ids']):
        metadata = results['metadatas'][i] if results.get('metadatas') is not None and i < len(results['metadatas']) else {}
        
        # Try to get source file name from metadata
        source = metadata.get('file_name') or metadata.get('source') or metadata.get('doc_name') or 'Unknown'
        
        if source not in grouped:
            grouped[source] = []
        
        grouped[source].append({
            'id': doc_id,
            'idx': i,
            'metadata': metadata,
            'document': results['documents'][i] if results.get('documents') is not None and i < len(results['documents']) else '',
            'embedding': results['embeddings'][i] if results.get('embeddings') is not None and i < len(results['embeddings']) else None,
        })
    
    return grouped


def format_vector(vector, show_dims=True):
    """Format vector for display
    
    Args:
        vector: List or array of numbers
        show_dims: Whether to show dimension info
    """
    if not vector:
        return "No vector"
    
    vector = np.array(vector) if not isinstance(vector, np.ndarray) else vector
    dims = len(vector)
    magnitude = np.linalg.norm(vector)
    
    # Show first 5 and last 5 elements
    display_elements = list(vector[:5]) + ['...'] + list(vector[-5:])
    vector_str = ', '.join(f"{x:.4f}" if isinstance(x, (int, float)) else str(x) for x in display_elements)
    
    result = f"`[{vector_str}]`"
    if show_dims:
        result += f" (dims={dims}, magnitude={magnitude:.4f})"
    
    return result


def view_chroma_data(document_filter=None, show_vectors=True):
    """Connect to Chroma and display complete data including vectors
    
    Args:
        document_filter: Optional filter to show only a specific document source
        show_vectors: Whether to include vector information
    """
    
    # Path to Chroma database
    chroma_path = Path("data/chroma")
    
    if not chroma_path.exists():
        print(f"❌ Chroma path not found: {chroma_path}")
        return
    
    print(f"📦 Connecting to Chroma at: {chroma_path}")
    print("-" * 100)
    
    try:
        # Connect to Chroma
        client = chromadb.PersistentClient(path=str(chroma_path))
        
        # Get all collections
        collections = client.list_collections()
        print(f"✅ Connected to Chroma!")
        print(f"📊 Found {len(collections)} collection(s):\n")
        
        for collection in collections:
            print(f"🔹 Collection: {collection.name}")
            print(f"   Total documents: {collection.count()}\n")
            
            # Get all data from collection
            try:
                results = collection.get(include=['documents', 'metadatas', 'embeddings'])
                grouped = group_by_source(results)
                
                # Filter by document if specified
                if document_filter:
                    filtered_grouped = {k: v for k, v in grouped.items() if document_filter.lower() in k.lower()}
                    if not filtered_grouped:
                        print(f"   ❌ No documents found matching: '{document_filter}'")
                        print(f"   📁 Available documents:")
                        for source in sorted(grouped.keys()):
                            print(f"      - {source}")
                        return
                    grouped = filtered_grouped
                    print(f"   🔍 Filtering for: '{document_filter}'")
                
                print(f"   📁 Found {len(grouped)} source file(s):\n")
                
                # Display grouped by source - console summary
                for source_num, (source, docs) in enumerate(sorted(grouped.items()), 1):
                    print(f"   📄 [{source_num}] {source}")
                    print(f"       Chunks: {len(docs)}")
                    
                    # Show first chunk preview
                    if docs:
                        preview = docs[0]['document'][:120].replace('\n', ' ')
                        print(f"       └─ First chunk: {preview}...")
                    print()
                
                print(f"   Total chunks: {len(results.get('ids', []))}")
            
            except Exception as e:
                print(f"   ❌ Error reading collection: {e}")
                import traceback
                traceback.print_exc()
            
            print("\n" + "=" * 100 + "\n")
        
        # Save detailed summary to markdown file
        output_filename = "chroma_view.md"
        if document_filter:
            output_filename = f"chroma_view_{document_filter.replace(' ', '_').replace('/', '_')}.md"
        
        output_file = Path(output_filename)
        print(f"💾 Generating detailed markdown report...")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("# 📦 CHROMA VECTOR DATABASE - COMPLETE VIEW\n\n")
            f.write(f"**Database Path:** `{chroma_path}`\n\n")
            if document_filter:
                f.write(f"**Filter Applied:** `{document_filter}`\n\n")
            f.write("---\n\n")
            
            for collection in collections:
                f.write(f"## Collection: `{collection.name}`\n\n")
                f.write(f"- **Total Documents in Collection:** {collection.count()}\n\n")
                
                try:
                    results = collection.get(include=['documents', 'metadatas', 'embeddings'])
                    grouped = group_by_source(results)
                    
                    # Filter if needed
                    if document_filter:
                        grouped = {k: v for k, v in grouped.items() if document_filter.lower() in k.lower()}
                    
                    # Write grouped by source
                    for source_num, (source, docs) in enumerate(sorted(grouped.items()), 1):
                        f.write(f"\n## 📄 Source #{source_num}: `{source}`\n\n")
                        f.write(f"**Total Chunks:** {len(docs)}\n\n")
                        f.write("---\n\n")
                        
                        # Table of contents
                        f.write("### Quick Index\n\n")
                        f.write("| # | Preview |\n")
                        f.write("|---|----------|\n")
                        for chunk_num, doc in enumerate(docs, 1):
                            preview = doc['document'][:80].replace('\n', ' ').replace('|', '\\|')
                            f.write(f"| {chunk_num} | {preview}... |\n")
                        f.write("\n---\n\n")
                        
                        # Detailed chunks
                        f.write("### Detailed Chunks\n\n")
                        for chunk_num, doc in enumerate(docs, 1):
                            f.write(f"\n{'='*100}\n")
                            f.write(f"### 📌 Chunk {chunk_num}/{len(docs)}\n")
                            f.write(f"{'='*100}\n\n")
                            
                            # Basic info
                            f.write(f"**ID:** `{doc['id']}`\n\n")
                            
                            # Metadata section
                            if doc['metadata']:
                                f.write(f"#### 📋 Metadata\n\n")
                                f.write("```json\n")
                                import json
                                # Pretty print metadata
                                for key, value in sorted(doc['metadata'].items()):
                                    if isinstance(value, (dict, list)):
                                        f.write(f"{key}:\n")
                                        f.write(json.dumps(value, indent=2, ensure_ascii=False))
                                        f.write("\n\n")
                                    else:
                                        f.write(f"{key}: {value}\n")
                                f.write("```\n\n")
                            
                            # Vector section - FULL VECTOR
                            if show_vectors and doc['embedding'] is not None:
                                f.write(f"#### 🔢 Vector Embedding\n\n")
                                vector = np.array(doc['embedding'])
                                dims = len(vector)
                                magnitude = np.linalg.norm(vector)
                                
                                f.write(f"- **Dimensions:** {dims}\n")
                                f.write(f"- **Magnitude (L2 norm):** {magnitude:.8f}\n")
                                f.write(f"- **Min Value:** {np.min(vector):.8f}\n")
                                f.write(f"- **Max Value:** {np.max(vector):.8f}\n")
                                f.write(f"- **Mean Value:** {np.mean(vector):.8f}\n")
                                f.write(f"- **Std Dev:** {np.std(vector):.8f}\n\n")
                                
                                # Print ALL vector elements in a nice format
                                f.write(f"**All Vector Elements ({dims} dimensions):**\n\n")
                                f.write("```\n")
                                # Print in groups of 10 per line for readability
                                for i in range(0, dims, 10):
                                    elements = vector[i:i+10]
                                    f.write(f"[{i:4d}-{min(i+9, dims-1):4d}]: ")
                                    f.write("  ".join(f"{val:10.6f}" for val in elements))
                                    f.write("\n")
                                f.write("```\n\n")
                            
                            # Content section - FULL CONTENT
                            f.write(f"#### 📝 Document Content\n\n")
                            f.write("```\n")
                            f.write(doc['document'])
                            f.write("\n```\n\n")
                            
                            f.write("---\n\n")
                
                except Exception as e:
                    f.write(f"\n⚠️ **Error:** {e}\n\n")
                    import traceback
                    f.write(f"```\n{traceback.format_exc()}\n```\n\n")
        
        print(f"✅ Detailed summary saved to: {output_file}")
        print(f"📖 Open with: VS Code, GitHub, or any Markdown viewer")
    
    except Exception as e:
        print(f"❌ Error connecting to Chroma: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="View complete Chroma vector database contents (vectors, metadata, content)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python view_chroma.py                                    # View all documents with vectors
  python view_chroma.py "Chinh-sach-nghi-phep.docx"       # View specific document
  python view_chroma.py -d "FPT"                          # View documents containing "FPT"
  python view_chroma.py --document "Chinh_Sach"           # View documents containing "Chinh_Sach"
  python view_chroma.py "Chinh-sach-nghi-phep.docx" --no-vectors  # Specific doc without vectors
        """
    )
    
    parser.add_argument(
        'document',
        nargs='?',
        default=None,
        help='Specific document name to view (exact match or partial)'
    )
    
    parser.add_argument(
        '-d', '--filter',
        type=str,
        default=None,
        help='Filter by document name (case-insensitive partial match) - alternative to positional argument'
    )
    
    parser.add_argument(
        '--no-vectors',
        action='store_true',
        help='Exclude vector embedding information'
    )
    
    args = parser.parse_args()
    
    # Use positional argument if provided, otherwise use --filter option
    document_filter = args.document or args.filter
    
    try:
        view_chroma_data(document_filter=document_filter, show_vectors=not args.no_vectors)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
