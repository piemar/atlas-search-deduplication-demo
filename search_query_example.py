import os
import logging
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from pprint import pprint
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from environment variables
MONGODB_URI = os.getenv('MONGODB_URI')
DB_NAME = os.getenv('DB_NAME', 'dedup_demo')
COLLECTION_NAME = os.getenv('COLLECTION_NAME', 'consumers')

# Validate required environment variables
if not MONGODB_URI:
    logger.error("MONGODB_URI environment variable is required. Please check your .env file.")
    exit(1)

try:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    # Test the connection
    client.server_info()
    logger.info("Successfully connected to MongoDB")
    
    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]
    
    # Check if collection has data
    doc_count = collection.count_documents({})
    if doc_count == 0:
        logger.error(f"Collection '{COLLECTION_NAME}' is empty. Please run data_generator.py first.")
        exit(1)
    
    logger.info(f"Collection contains {doc_count} documents")
    sample_doc = collection.find_one()
    
    if not sample_doc:
        logger.error("Could not retrieve sample document")
        exit(1)
        
except (ConnectionFailure, ServerSelectionTimeoutError) as e:
    logger.error(f"Failed to connect to MongoDB: {e}")
    exit(1)
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    exit(1)

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

def find_duplicates_for_sample(sample_doc, limit=10):
    """Find potential duplicates for a given sample document"""
    
    logger.info(f"Searching for duplicates of:")
    logger.info(f"  Name: {sample_doc.get('first_name')} {sample_doc.get('last_name')}")
    logger.info(f"  Email: {sample_doc.get('email')}")
    logger.info(f"  Phone: {sample_doc.get('phone')}")
    
    # Build the search query
    query = {
        "$search": {
            "compound": {
                "should": [
                    {
                        "text": {
                            "query": sample_doc["first_name"],
                            "path": "first_name",
                            "fuzzy": {
                                "maxEdits": 2
                            },
                            "score": {"boost": {"value": 3}}
                        }
                    },
                    {
                        "text": {
                            "query": sample_doc["last_name"],
                            "path": "last_name",
                            "fuzzy": {
                                "maxEdits": 2
                            },
                            "score": {"boost": {"value": 3}}
                        }
                    },
                    {
                        "text": {
                            "query": sample_doc["email"],
                            "path": "email",
                            "fuzzy": {
                                "maxEdits": 1
                            },
                            "score": {"boost": {"value": 5}}
                        }
                    },
                    {
                        "text": {
                            "query": sample_doc["phone"],
                            "path": "phone",
                            "fuzzy": {
                                "maxEdits": 1
                            },
                            "score": {"boost": {"value": 2}}
                        }
                    }
                ],
                "minimumShouldMatch": 1
            }
        }
    }
    
    # Execute search with scoring
    pipeline = [
        query,
        {
            "$addFields": {
                "search_score": {"$meta": "searchScore"}
            }
        },
        {
            "$match": {
                "_id": {"$ne": sample_doc["_id"]}  # Exclude the original document
            }
        },
        {"$limit": limit},
        {
            "$sort": {"search_score": -1}
        }
    ]
    
    try:
        results = list(collection.aggregate(pipeline))
        return results
    except Exception as e:
        logger.error(f"Search query failed: {e}")
        return []

# Find duplicates for the sample document
logger.info("=" * 60)
logger.info("DUPLICATE DETECTION DEMO")
logger.info("=" * 60)

duplicates = find_duplicates_for_sample(sample_doc, limit=10)

if duplicates:
    logger.info(f"\n🔍 Found {len(duplicates)} potential duplicates:")
    print("\n" + "="*80)
    
    for i, duplicate in enumerate(duplicates, 1):
        similarity_score = calculate_similarity_score(sample_doc, duplicate)
        print(f"\n#{i} POTENTIAL DUPLICATE (Search Score: {duplicate.get('search_score', 0):.3f}, Similarity: {similarity_score}%)")
        print("-" * 50)
        print(f"Original: {sample_doc.get('first_name')} {sample_doc.get('last_name')}")
        print(f"          {sample_doc.get('email')}")
        print(f"          {sample_doc.get('phone')}")
        print()
        print(f"Duplicate: {duplicate.get('first_name')} {duplicate.get('last_name')}")
        print(f"           {duplicate.get('email')}")
        print(f"           {duplicate.get('phone')}")
        
        if duplicate.get('record_type') == 'duplicate':
            print(f"           ✓ Confirmed synthetic duplicate")
        
        if similarity_score > 70:
            print(f"           🚨 HIGH CONFIDENCE DUPLICATE")
        elif similarity_score > 40:
            print(f"           ⚠️  POSSIBLE DUPLICATE")
        else:
            print(f"           ❓ LOW CONFIDENCE MATCH")
            
else:
    logger.info("No potential duplicates found")

# Statistics
try:
    total_records = collection.count_documents({})
    duplicate_records = collection.count_documents({"record_type": "duplicate"})
    original_records = collection.count_documents({"record_type": "original"})
    
    print(f"\n" + "="*80)
    print("DATABASE STATISTICS")
    print("="*80)
    print(f"Total records: {total_records:,}")
    print(f"Original records: {original_records:,}")
    print(f"Synthetic duplicates: {duplicate_records:,}")
    print(f"Duplicate percentage: {(duplicate_records/total_records)*100:.1f}%")
    
except Exception as e:
    logger.error(f"Failed to get statistics: {e}")
finally:
    client.close()
    logger.info("Database connection closed")