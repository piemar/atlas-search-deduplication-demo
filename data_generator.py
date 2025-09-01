import os
import random
import string
import logging
from faker import Faker
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
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
NUM_RECORDS = int(os.getenv('NUM_RECORDS', 10000))
DUPLICATE_PERCENTAGE = float(os.getenv('DUPLICATE_PERCENTAGE', 0.2))

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
    fake = Faker()
    
    # Confirm before dropping collection
    if collection.count_documents({}) > 0:
        logger.warning(f"Collection '{COLLECTION_NAME}' already contains {collection.count_documents({})} documents")
        response = input("Do you want to drop the existing collection? (y/N): ")
        if response.lower() == 'y':
            collection.drop()
            logger.info("Collection dropped successfully")
        else:
            logger.info("Keeping existing collection. Exiting.")
            exit(0)
            
except (ConnectionFailure, ServerSelectionTimeoutError) as e:
    logger.error(f"Failed to connect to MongoDB: {e}")
    exit(1)
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    exit(1)

def introduce_typo(text, num_typos=1):
    """
    Introduce realistic typos into text including:
    - Character substitution
    - Character deletion
    - Character insertion
    - Character transposition
    """
    if not text or len(text) < 2:
        return text
        
    text = list(text)
    operations = ['substitute', 'delete', 'insert', 'transpose']
    
    for _ in range(num_typos):
        if len(text) < 2:
            break
            
        operation = random.choice(operations)
        idx = random.randint(0, len(text) - 1)
        
        if operation == 'substitute':
            # Replace with similar character (keyboard adjacent or phonetically similar)
            original_char = text[idx].lower()
            keyboard_adjacent = {
                'a': 'sq', 'b': 'vgn', 'c': 'xvf', 'd': 'sfre', 'e': 'wrd',
                'f': 'dgrt', 'g': 'fhty', 'h': 'gyuj', 'i': 'uko', 'j': 'hnik',
                'k': 'jmlo', 'l': 'kpo', 'm': 'njk', 'n': 'bmhj', 'o': 'ilp',
                'p': 'ol', 'q': 'wa', 'r': 'etd', 's': 'awedx', 't': 'rfgy',
                'u': 'yhi', 'v': 'cfgb', 'w': 'qase', 'x': 'zsdc', 'y': 'tghu',
                'z': 'asx'
            }
            if original_char in keyboard_adjacent:
                text[idx] = random.choice(keyboard_adjacent[original_char])
            else:
                text[idx] = random.choice(string.ascii_lowercase)
                
        elif operation == 'delete' and len(text) > 1:
            text.pop(idx)
            
        elif operation == 'insert':
            text.insert(idx, random.choice(string.ascii_lowercase))
            
        elif operation == 'transpose' and len(text) > 1 and idx < len(text) - 1:
            text[idx], text[idx + 1] = text[idx + 1], text[idx]
    
    return ''.join(text)

def validate_record(record):
    """Validate that a record has all required fields"""
    required_fields = ['first_name', 'last_name', 'email', 'phone', 'address', 'createdAt']
    return all(field in record and record[field] for field in required_fields)

# Generate original records
logger.info(f"Generating {NUM_RECORDS} records with {DUPLICATE_PERCENTAGE*100:.1f}% duplicates")
original_records = []
duplicate_records = []

num_originals = int(NUM_RECORDS * (1 - DUPLICATE_PERCENTAGE))
num_duplicates = int(NUM_RECORDS * DUPLICATE_PERCENTAGE)

logger.info(f"Creating {num_originals} original records...")
for i in range(num_originals):
    if i % 1000 == 0:
        logger.info(f"Generated {i}/{num_originals} original records")
        
    record = {
        "first_name": fake.first_name(),
        "last_name": fake.last_name(),
        "email": fake.email(),
        "phone": fake.phone_number(),
        "address": fake.address(),
        "createdAt": fake.date_time_this_year().isoformat(),
        "record_type": "original"
    }
    
    if validate_record(record):
        original_records.append(record)
    else:
        logger.warning(f"Invalid record generated: {record}")

logger.info(f"Creating {num_duplicates} duplicate records with typos...")
for i in range(num_duplicates):
    if i % 500 == 0:
        logger.info(f"Generated {i}/{num_duplicates} duplicate records")
        
    base = random.choice(original_records)
    duplicate = base.copy()
    
    # Introduce typos with varying intensity
    typo_intensity = random.choice([1, 1, 1, 2])  # More likely to have 1 typo
    
    duplicate["first_name"] = introduce_typo(duplicate["first_name"], random.randint(1, typo_intensity))
    duplicate["last_name"] = introduce_typo(duplicate["last_name"], random.randint(1, typo_intensity))
    duplicate["email"] = introduce_typo(duplicate["email"], 1)  # Be more conservative with emails
    
    # Sometimes introduce phone typos
    if random.random() < 0.7:
        duplicate["phone"] = introduce_typo(duplicate["phone"], 1)
    
    duplicate["record_type"] = "duplicate"
    duplicate["original_id"] = str(base.get("_id", "unknown"))
    duplicate_records.append(duplicate)

all_records = original_records + duplicate_records
random.shuffle(all_records)  # Mix them up

logger.info(f"Inserting {len(all_records)} records into MongoDB...")

try:
    # Insert in batches for better performance
    batch_size = 1000
    for i in range(0, len(all_records), batch_size):
        batch = all_records[i:i + batch_size]
        collection.insert_many(batch)
        logger.info(f"Inserted batch {i//batch_size + 1}/{(len(all_records)-1)//batch_size + 1}")
    
    # Create index for better search performance
    logger.info("Creating indexes...")
    collection.create_index([("first_name", "text"), ("last_name", "text"), ("email", "text")])
    
    logger.info(f"✅ Successfully inserted {len(all_records)} consumer records")
    logger.info(f"   - Original records: {len(original_records)}")
    logger.info(f"   - Duplicate records: {len(duplicate_records)}")
    logger.info(f"   - Duplicate percentage: {len(duplicate_records)/len(all_records)*100:.1f}%")

except Exception as e:
    logger.error(f"Failed to insert records: {e}")
    exit(1)
finally:
    client.close()
    logger.info("Database connection closed")