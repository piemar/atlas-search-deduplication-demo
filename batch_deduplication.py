#!/usr/bin/env python3
"""
Batch Deduplication Script
Processes all records in the collection to find and report duplicates
"""

import os
import logging
import time
from collections import defaultdict
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('deduplication.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
MONGODB_URI = os.getenv('MONGODB_URI')
DB_NAME = os.getenv('DB_NAME', 'dedup_demo')
COLLECTION_NAME = os.getenv('COLLECTION_NAME', 'consumers')
BATCH_SIZE = int(os.getenv('BATCH_SIZE', 1000))
SIMILARITY_THRESHOLD = float(os.getenv('SIMILARITY_THRESHOLD', 60.0))

def calculate_similarity_score(doc1, doc2):
    """Calculate similarity score between two documents"""
    score = 0
    
    # Name similarity (higher weight)
    if doc1.get("first_name", "").lower() == doc2.get("first_name", "").lower():
        score += 40
    elif doc1.get("first_name", "").lower() in doc2.get("first_name", "").lower():
        score += 20
        
    if doc1.get("last_name", "").lower() == doc2.get("last_name", "").lower():
        score += 40
    elif doc1.get("last_name", "").lower() in doc2.get("last_name", "").lower():
        score += 20
    
    # Email similarity (very high weight)
    if doc1.get("email", "").lower() == doc2.get("email", "").lower():
        score += 60
    elif doc1.get("email", "").split("@")[0].lower() == doc2.get("email", "").split("@")[0].lower():
        score += 30
    
    # Phone similarity
    phone1 = ''.join(filter(str.isdigit, doc1.get("phone", "")))
    phone2 = ''.join(filter(str.isdigit, doc2.get("phone", "")))
    if phone1 and phone2 and phone1 == phone2:
        score += 20
    
    return score

def find_duplicates_batch(collection, documents, processed_ids):
    """Find duplicates for a batch of documents"""
    duplicate_groups = []
    
    for doc in documents:
        if doc["_id"] in processed_ids:
            continue
            
        # Search for similar documents
        query = {
            "$search": {
                "compound": {
                    "should": [
                        {
                            "text": {
                                "query": doc["first_name"],
                                "path": "first_name",
                                "fuzzy": {"maxEdits": 2},
                                "score": {"boost": {"value": 3}}
                            }
                        },
                        {
                            "text": {
                                "query": doc["last_name"],
                                "path": "last_name",
                                "fuzzy": {"maxEdits": 2},
                                "score": {"boost": {"value": 3}}
                            }
                        },
                        {
                            "text": {
                                "query": doc["email"],
                                "path": "email",
                                "fuzzy": {"maxEdits": 1},
                                "score": {"boost": {"value": 5}}
                            }
                        }
                    ],
                    "minimumShouldMatch": 1
                }
            }
        }
        
        pipeline = [
            query,
            {
                "$addFields": {
                    "search_score": {"$meta": "searchScore"}
                }
            },
            {
                "$match": {
                    "_id": {"$ne": doc["_id"]}
                }
            },
            {"$limit": 20}
        ]
        
        try:
            candidates = list(collection.aggregate(pipeline))
            
            # Calculate similarity scores and filter
            duplicates = []
            for candidate in candidates:
                similarity = calculate_similarity_score(doc, candidate)
                if similarity >= SIMILARITY_THRESHOLD:
                    candidate["similarity_score"] = similarity
                    duplicates.append(candidate)
            
            if duplicates:
                # Create duplicate group
                group = {
                    "master": doc,
                    "duplicates": duplicates,
                    "group_size": len(duplicates) + 1,
                    "max_similarity": max(d["similarity_score"] for d in duplicates)
                }
                duplicate_groups.append(group)
                
                # Mark all documents in this group as processed
                processed_ids.add(doc["_id"])
                for dup in duplicates:
                    processed_ids.add(dup["_id"])
                    
        except Exception as e:
            logger.error(f"Error processing document {doc['_id']}: {e}")
            
    return duplicate_groups

def main():
    """Main deduplication process"""
    if not MONGODB_URI:
        logger.error("MONGODB_URI environment variable is required")
        return
    
    try:
        # Connect to MongoDB
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        client.server_info()
        logger.info("Successfully connected to MongoDB")
        
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]
        
        # Get total count
        total_docs = collection.count_documents({})
        if total_docs == 0:
            logger.error("Collection is empty. Run data_generator.py first.")
            return
            
        logger.info(f"Processing {total_docs:,} documents in batches of {BATCH_SIZE}")
        logger.info(f"Similarity threshold: {SIMILARITY_THRESHOLD}%")
        
        # Process in batches
        processed_ids = set()
        all_duplicate_groups = []
        batch_num = 0
        start_time = time.time()
        
        cursor = collection.find({})
        
        while True:
            # Get next batch
            batch = []
            for _ in range(BATCH_SIZE):
                try:
                    doc = next(cursor)
                    if doc["_id"] not in processed_ids:
                        batch.append(doc)
                except StopIteration:
                    break
            
            if not batch:
                break
                
            batch_num += 1
            logger.info(f"Processing batch {batch_num} ({len(batch)} documents)")
            
            # Find duplicates in this batch
            duplicate_groups = find_duplicates_batch(collection, batch, processed_ids)
            all_duplicate_groups.extend(duplicate_groups)
            
            if duplicate_groups:
                logger.info(f"Found {len(duplicate_groups)} duplicate groups in batch {batch_num}")
        
        # Generate report
        elapsed_time = time.time() - start_time
        
        logger.info("=" * 80)
        logger.info("DEDUPLICATION REPORT")
        logger.info("=" * 80)
        logger.info(f"Total documents processed: {total_docs:,}")
        logger.info(f"Duplicate groups found: {len(all_duplicate_groups):,}")
        logger.info(f"Total duplicates: {sum(g['group_size']-1 for g in all_duplicate_groups):,}")
        logger.info(f"Processing time: {elapsed_time:.2f} seconds")
        logger.info(f"Documents per second: {total_docs/elapsed_time:.1f}")
        
        # Save detailed report
        if all_duplicate_groups:
            report_filename = f"duplicate_report_{int(time.time())}.txt"
            with open(report_filename, 'w') as f:
                f.write("MongoDB Atlas Search Deduplication Report\n")
                f.write("=" * 50 + "\n\n")
                
                for i, group in enumerate(all_duplicate_groups, 1):
                    f.write(f"DUPLICATE GROUP #{i} (Similarity: {group['max_similarity']:.1f}%)\n")
                    f.write("-" * 30 + "\n")
                    
                    master = group['master']
                    f.write(f"MASTER RECORD:\n")
                    f.write(f"  ID: {master['_id']}\n")
                    f.write(f"  Name: {master.get('first_name')} {master.get('last_name')}\n")
                    f.write(f"  Email: {master.get('email')}\n")
                    f.write(f"  Phone: {master.get('phone')}\n")
                    f.write(f"  Type: {master.get('record_type', 'unknown')}\n\n")
                    
                    f.write(f"DUPLICATES ({len(group['duplicates'])}):\n")
                    for j, dup in enumerate(group['duplicates'], 1):
                        f.write(f"  #{j} (Similarity: {dup['similarity_score']:.1f}%)\n")
                        f.write(f"    ID: {dup['_id']}\n")
                        f.write(f"    Name: {dup.get('first_name')} {dup.get('last_name')}\n")
                        f.write(f"    Email: {dup.get('email')}\n")
                        f.write(f"    Phone: {dup.get('phone')}\n")
                        f.write(f"    Type: {dup.get('record_type', 'unknown')}\n\n")
                    
                    f.write("\n" + "="*50 + "\n\n")
            
            logger.info(f"Detailed report saved to: {report_filename}")
        
        # Clean up results for potential deletion
        high_confidence_duplicates = []
        for group in all_duplicate_groups:
            for dup in group['duplicates']:
                if dup['similarity_score'] >= 80:
                    high_confidence_duplicates.append(dup['_id'])
        
        if high_confidence_duplicates:
            logger.info(f"Found {len(high_confidence_duplicates)} high-confidence duplicates (>80% similarity)")
            logger.info("These could be safely removed in a production system")
            
            # Optionally create a collection of duplicate IDs for cleanup
            cleanup_collection = db['duplicates_to_remove']
            cleanup_collection.drop()
            cleanup_docs = [{"_id": dup_id, "identified_at": time.time()} for dup_id in high_confidence_duplicates]
            if cleanup_docs:
                cleanup_collection.insert_many(cleanup_docs)
                logger.info(f"Duplicate IDs saved to '{cleanup_collection.name}' collection for cleanup")
        
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        try:
            client.close()
            logger.info("Database connection closed")
        except:
            pass

if __name__ == "__main__":
    main()
