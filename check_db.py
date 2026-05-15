"""
Simple diagnostic script to check what's in the database and vector store
Run this on EC2 to see what documents are loaded
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from rag_chatbot.database import document_manager

print("\n" + "="*80)
print("📊 DOCUMENT DATABASE DIAGNOSTIC")
print("="*80)

# Check database
docs = document_manager.get_all_documents()

print(f"\n📁 Documents in database: {len(docs)}")
print("-" * 80)

for doc in docs:
    print(f"\nID: {doc['id']}")
    print(f"  Filename: {doc['filename']}")
    print(f"  Type: {doc['file_type']}")
    print(f"  Size: {doc['file_size']} bytes")
    print(f"  Uploaded: {doc['upload_date']}")
    print(f"  By: {doc['uploaded_by']}")
    
    # Check if file exists on disk
    file_path = os.path.join('data/data', doc['filename'])
    exists = os.path.exists(file_path)
    print(f"  File on disk: {'✓ YES' if exists else '✗ NO'}")

print("\n" + "="*80)

# Check what files are physically in data/data
print("\n📂 Files in data/data directory:")
print("-" * 80)

data_dir = 'data/data'
if os.path.exists(data_dir):
    files = os.listdir(data_dir)
    print(f"\nTotal files: {len(files)}")
    for f in files:
        file_path = os.path.join(data_dir, f)
        size = os.path.getsize(file_path)
        print(f"  - {f} ({size:,} bytes)")
else:
    print("  Directory does not exist!")

print("\n" + "="*80)
