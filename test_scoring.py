#!/usr/bin/env python3
"""
Demonstration of how multi-field search scoring works
"""

import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient

# Load environment variables
load_dotenv()

# Configuration
MONGODB_URI = os.getenv('MONGODB_URI')
DB_NAME = os.getenv('DB_NAME', 'dedup_demo')
COLLECTION_NAME = os.getenv('COLLECTION_NAME', 'consumers')

def calculate_similarity_score(doc1, doc2):
    """Calculate similarity score between two documents"""
    score = 0
    print(f"\n--- Calculating similarity between:")
    print(f"Input: {doc1.get('first_name')} {doc1.get('last_name')} | {doc1.get('email')}")
    print(f"Found: {doc2.get('first_name')} {doc2.get('last_name')} | {doc2.get('email')}")
    
    # Name similarity (higher weight)
    if doc1.get("first_name", "").lower() == doc2.get("first_name", "").lower():
        score += 40
        print(f"✅ First name exact match: +40 points")
    elif doc1.get("first_name", "").lower() in doc2.get("first_name", "").lower():
        score += 20
        print(f"⚠️  First name partial match: +20 points")
    else:
        print(f"❌ First name no match: +0 points")
        
    if doc1.get("last_name", "").lower() == doc2.get("last_name", "").lower():
        score += 40
        print(f"✅ Last name exact match: +40 points")
    elif doc1.get("last_name", "").lower() in doc2.get("last_name", "").lower():
        score += 20
        print(f"⚠️  Last name partial match: +20 points")
    else:
        print(f"❌ Last name no match: +0 points")
    
    # Email similarity (very high weight)
    if doc1.get("email", "").lower() == doc2.get("email", "").lower():
        score += 60
        print(f"✅ Email exact match: +60 points")
    elif doc1.get("email", "").split("@")[0].lower() == doc2.get("email", "").split("@")[0].lower():
        score += 30
        print(f"⚠️  Email username match: +30 points")
    else:
        print(f"❌ Email no match: +0 points")
    
    # Phone similarity
    phone1 = ''.join(filter(str.isdigit, doc1.get("phone", "")))
    phone2 = ''.join(filter(str.isdigit, doc2.get("phone", "")))
    if phone1 and phone2 and phone1 == phone2:
        score += 20
        print(f"✅ Phone exact match: +20 points")
    else:
        print(f"❌ Phone no match: +0 points")
    
    print(f"🎯 Total Similarity Score: {score}/160 points ({score/160*100:.1f}%)")
    return score

def demonstrate_multi_field_search():
    """Demonstrate how multi-field search combines scores"""
    
    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]
        
        # Test customer data
        test_customer = {
            "first_name": "John",
            "last_name": "Smith", 
            "email": "john.smith@email.com",
            "phone": "(555) 123-4567"
        }
        
        print("="*80)
        print("🔍 MULTI-FIELD SEARCH SCORING DEMONSTRATION")
        print("="*80)
        print(f"Searching for: {test_customer['first_name']} {test_customer['last_name']}")
        print(f"Email: {test_customer['email']}")
        print(f"Phone: {test_customer['phone']}")
        
        # Create search conditions (same as in app.py)
        should_conditions = []
        
        # Each field gets weighted differently in Atlas Search
        should_conditions.append({
            "text": {
                "query": test_customer["first_name"],
                "path": "first_name",
                "fuzzy": {"maxEdits": 2},
                "score": {"boost": {"value": 3}}  # 3x boost
            }
        })
        
        should_conditions.append({
            "text": {
                "query": test_customer["last_name"],
                "path": "last_name", 
                "fuzzy": {"maxEdits": 2},
                "score": {"boost": {"value": 3}}  # 3x boost
            }
        })
        
        should_conditions.append({
            "text": {
                "query": test_customer["email"],
                "path": "email",
                "fuzzy": {"maxEdits": 1},
                "score": {"boost": {"value": 5}}  # 5x boost (highest)
            }
        })
        
        should_conditions.append({
            "text": {
                "query": test_customer["phone"],
                "path": "phone",
                "fuzzy": {"maxEdits": 1},
                "score": {"boost": {"value": 2}}  # 2x boost
            }
        })
        
        # Build the compound query
        query = {
            "$search": {
                "compound": {
                    "should": should_conditions,
                    "minimumShouldMatch": 1
                }
            }
        }
        
        print("\n" + "="*80)
        print("📊 ATLAS SEARCH QUERY STRUCTURE")
        print("="*80)
        print("MongoDB Atlas Search combines these fields automatically:")
        print("• First Name: fuzzy matching (2 edits), 3x boost")
        print("• Last Name:  fuzzy matching (2 edits), 3x boost") 
        print("• Email:      fuzzy matching (1 edit),  5x boost ⭐ HIGHEST")
        print("• Phone:      fuzzy matching (1 edit),  2x boost")
        print("• Query Type: 'should' with minimumShouldMatch=1")
        print("• Result:     Atlas automatically combines all field scores")
        
        # Execute search
        pipeline = [
            query,
            {
                "$addFields": {
                    "search_score": {"$meta": "searchScore"}
                }
            },
            {"$limit": 5},
            {"$sort": {"search_score": -1}}
        ]
        
        results = list(collection.aggregate(pipeline))
        
        print(f"\n" + "="*80) 
        print("🎯 SEARCH RESULTS WITH DUAL SCORING")
        print("="*80)
        print(f"Found {len(results)} potential matches:\n")
        
        for i, result in enumerate(results, 1):
            atlas_score = result.get('search_score', 0)
            similarity_score = calculate_similarity_score(test_customer, result)
            
            confidence = "🚨 HIGH" if similarity_score > 70 else "⚠️ MEDIUM" if similarity_score > 40 else "❓ LOW"
            
            print(f"\n{'='*50}")
            print(f"Match #{i}: {confidence} CONFIDENCE")
            print(f"Atlas Search Score: {atlas_score:.4f}")
            print(f"Custom Similarity: {similarity_score}/160 ({similarity_score/160*100:.1f}%)")
            print(f"Record Type: {result.get('record_type', 'unknown')}")
            
        print("\n" + "="*80)
        print("📈 SCORING SUMMARY")
        print("="*80)
        print("The system uses TWO complementary scoring methods:")
        print("1. 🔍 Atlas Search Score: AI-powered relevance from MongoDB")
        print("   - Combines fuzzy matching across all fields")
        print("   - Applies different boosts (Email=5x, Names=3x, Phone=2x)")
        print("   - Returns results ranked by combined relevance")
        print()
        print("2. 🎯 Custom Similarity Score: Business logic scoring")
        print("   - Exact matches get higher points than fuzzy matches")
        print("   - Email gets highest weight (60 pts) as most unique")
        print("   - Names get medium weight (40 pts each)")
        print("   - Phone gets lower weight (20 pts)")
        print("   - Final confidence: High >70%, Medium 40-70%, Low <40%")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    demonstrate_multi_field_search()
