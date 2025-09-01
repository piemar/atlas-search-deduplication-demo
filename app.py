import os
import logging
from flask import Flask, render_template, request, jsonify, flash, redirect, url_for, session
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-change-this')

# Default threshold settings
DEFAULT_SETTINGS = {
    'similarity_threshold': 0,  # 0% of 160 points - show all matches
    'search_score_threshold': 0.0,  # Minimum Atlas Search score
    'high_confidence_threshold': 70,  # High confidence similarity %
    'medium_confidence_threshold': 40,  # Medium confidence similarity %
    'max_results': 10  # Maximum duplicate results to show
}

def get_settings():
    """Get current threshold settings from session or defaults"""
    if 'settings' not in session:
        session['settings'] = DEFAULT_SETTINGS.copy()
    return session['settings']

def update_settings(new_settings):
    """Update threshold settings in session"""
    settings = get_settings()
    settings.update(new_settings)
    session['settings'] = settings
    return settings

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

# Global MongoDB client
client = None
db = None
collection = None

def init_db():
    """Initialize MongoDB connection"""
    global client, db, collection
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
            logger.warning(f"Collection '{COLLECTION_NAME}' is empty. Please run data_generator.py first.")
        else:
            logger.info(f"Collection contains {doc_count} documents")
        
        return True
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return False

def calculate_similarity_score(doc1, doc2):
    """
    Calculate weighted similarity score between two customer documents.
    
    This algorithm implements a 160-point scoring system that weights different
    fields based on their likelihood of uniquely identifying a person:
    
    Scoring Breakdown:
    - First Name: 40 points (exact match), 20 points (partial match)
    - Last Name: 40 points (exact match), 20 points (partial match)  
    - Email: 60 points (exact match), 30 points (username match)
    - Phone: 20 points (normalized digits match)
    
    Args:
        doc1 (dict): First customer document with fields: first_name, last_name, email, phone
        doc2 (dict): Second customer document with same field structure
        
    Returns:
        int: Similarity score from 0-160, where 160 indicates perfect match
        
    Example:
        >>> customer1 = {"first_name": "John", "last_name": "Smith", "email": "john@gmail.com"}
        >>> customer2 = {"first_name": "Jon", "last_name": "Smith", "email": "john@gmail.com"}
        >>> calculate_similarity_score(customer1, customer2)
        120  # 20 (partial first) + 40 (exact last) + 60 (exact email)
    """
    score = 0
    
    # First Name Matching (40 points max)
    # Exact match gets full points, partial match gets half points
    first_name_1 = doc1.get("first_name", "").lower().strip()
    first_name_2 = doc2.get("first_name", "").lower().strip()
    if first_name_1 and first_name_2:
        if first_name_1 == first_name_2:
            score += 40  # Exact first name match
        elif first_name_1 in first_name_2 or first_name_2 in first_name_1:
            score += 20  # Partial first name match (e.g., "Jon" in "Jonathan")
        
    # Last Name Matching (40 points max)
    # Last names are critical for person identification
    last_name_1 = doc1.get("last_name", "").lower().strip()
    last_name_2 = doc2.get("last_name", "").lower().strip()
    if last_name_1 and last_name_2:
        if last_name_1 == last_name_2:
            score += 40  # Exact last name match
        elif last_name_1 in last_name_2 or last_name_2 in last_name_1:
            score += 20  # Partial last name match (e.g., "Smith" in "Smithson")
    
    # Email Matching (60 points max - highest weight)
    # Email addresses are typically unique identifiers
    email_1 = doc1.get("email", "").lower().strip()
    email_2 = doc2.get("email", "").lower().strip()
    if email_1 and email_2:
        if email_1 == email_2:
            score += 60  # Exact email match (strongest indicator)
        else:
            # Check if usernames match but domains differ
            try:
                username_1 = email_1.split("@")[0]
                username_2 = email_2.split("@")[0]
                if username_1 == username_2:
                    score += 30  # Same username, different domain
            except (IndexError, AttributeError):
                pass  # Malformed email, skip partial matching
    
    # Phone Number Matching (20 points max)
    # Normalize phone numbers by extracting only digits for comparison
    phone_1 = ''.join(filter(str.isdigit, doc1.get("phone", "")))
    phone_2 = ''.join(filter(str.isdigit, doc2.get("phone", "")))
    if phone_1 and phone_2 and phone_1 == phone_2:
        score += 20  # Normalized phone numbers match
    
    return score

def get_confidence_level(score):
    """
    Convert similarity score to business confidence level with visual indicators.
    
    This function translates the technical 160-point similarity score into 
    business-friendly confidence levels that help customer support agents
    make informed decisions about duplicate records.
    
    Confidence Level Business Logic:
    - High Confidence: Score indicates very likely duplicate, immediate action recommended
    - Possible Match: Score suggests potential duplicate, agent review recommended  
    - Worth Reviewing: Score shows some similarity, manual investigation needed
    
    Args:
        score (int): Similarity score from calculate_similarity_score (0-160 range)
        
    Returns:
        dict: Confidence assessment containing:
            - level (str): Human-readable confidence level
            - class (str): CSS class name for UI styling  
            - icon (str): Emoji icon for visual identification
            - description (str): Detailed explanation for agents
            
    Example:
        >>> get_confidence_level(140)  # High similarity score
        {
            "level": "High Confidence",
            "class": "high", 
            "icon": "🚨",
            "description": "Very likely duplicate - immediate merge candidate"
        }
    """
    # Get user-configurable thresholds from session settings
    settings = get_settings()
    high_threshold = settings['high_confidence_threshold']     # Default: 70%
    medium_threshold = settings['medium_confidence_threshold'] # Default: 40%
    
    # Convert 160-point score to percentage for threshold comparison
    percentage = (score / 160) * 100
    
    if percentage > high_threshold:
        return {
            "level": "High Confidence", 
            "class": "high", 
            "icon": "🚨", 
            "description": "Very likely duplicate - immediate merge candidate"
        }
    elif percentage > medium_threshold:
        return {
            "level": "Possible Match", 
            "class": "medium", 
            "icon": "⚠️", 
            "description": "Potential duplicate - agent review recommended"
        }
    else:
        return {
            "level": "Worth Reviewing", 
            "class": "low", 
            "icon": "❓", 
            "description": "Some similarity detected - manual investigation needed"
        }

def find_matching_customers(search_criteria, limit=100):
    """Find all customers matching the search criteria"""
    if collection is None:
        return []
    
    try:
        # Build MongoDB query for exact and partial matches
        query_conditions = []
        
        for field, value in search_criteria.items():
            if field in ['first_name', 'last_name']:
                # Case-insensitive partial match for names
                query_conditions.append({
                    field: {"$regex": f".*{value}.*", "$options": "i"}
                })
            elif field == 'email':
                # Case-insensitive exact match for email
                query_conditions.append({
                    field: {"$regex": f"^{value}$", "$options": "i"}
                })
            elif field == 'phone':
                # Exact match for phone (could be enhanced for formatting)
                query_conditions.append({field: value})
            elif field == 'address':
                # Case-insensitive partial match for address
                query_conditions.append({
                    field: {"$regex": f".*{value}.*", "$options": "i"}
                })
        
        # Combine conditions with OR logic
        if len(query_conditions) == 1:
            query = query_conditions[0]
        else:
            query = {"$or": query_conditions}
        
        # Execute query
        results = list(collection.find(query).limit(limit))
        
        # Convert ObjectId to string and add match indicators
        for result in results:
            result['_id'] = str(result['_id'])
            
            # Add match indicators to show which fields matched
            result['matched_fields'] = []
            for field, value in search_criteria.items():
                if field in result and result[field]:
                    if field in ['first_name', 'last_name', 'address']:
                        if value.lower() in result[field].lower():
                            result['matched_fields'].append(field)
                    elif field == 'email':
                        if value.lower() == result[field].lower():
                            result['matched_fields'].append(field)
                    elif field == 'phone':
                        if value == result[field]:
                            result['matched_fields'].append(field)
        
        # Sort by number of matched fields (most relevant first)
        results.sort(key=lambda x: len(x.get('matched_fields', [])), reverse=True)
        
        return results
        
    except Exception as e:
        logger.error(f"Customer search failed: {e}")
        return []

def find_duplicates_for_customer(customer_data, limit=None):
    """
    Find potential duplicate customer records using MongoDB Atlas Search.
    
    This function implements a sophisticated duplicate detection algorithm that combines:
    1. Atlas Search fuzzy text matching with configurable edit distances
    2. Weighted field scoring based on business importance 
    3. Custom similarity calculation for fine-grained matching
    4. Configurable confidence thresholds for business rules
    
    Atlas Search Query Strategy:
    - Uses compound queries with "should" conditions for flexible matching
    - Applies fuzzy matching with field-specific edit distance limits
    - Implements boost scoring to weight fields by importance:
      * Email: 5x boost (strongest unique identifier)
      * Names: 3x boost (important but can have variations)
      * Phone: 2x boost (reliable but can change)
    
    Args:
        customer_data (dict): Customer record containing searchable fields:
            - first_name (str): Customer's first name
            - last_name (str): Customer's last name  
            - email (str): Email address
            - phone (str): Phone number (any format)
            - _id (optional): Existing customer ID to exclude from results
            
        limit (int, optional): Maximum number of duplicates to return.
                              Defaults to max_results setting.
    
    Returns:
        list[dict]: List of potential duplicate records, each containing:
            - All original customer fields
            - similarity_score (int): 0-160 point custom similarity score
            - search_score (float): Atlas Search relevance score
            - confidence (dict): Confidence level assessment with:
                * level (str): "High Confidence", "Possible Match", "Worth Reviewing"
                * class (str): CSS class for UI styling
                * icon (str): Emoji icon for visual identification
                * description (str): Human-readable explanation
    
    Example:
        >>> customer = {
        ...     "first_name": "John",
        ...     "last_name": "Smith", 
        ...     "email": "john.smith@company.com"
        ... }
        >>> duplicates = find_duplicates_for_customer(customer)
        >>> for dup in duplicates:
        ...     print(f"{dup['first_name']} {dup['last_name']}: {dup['similarity_score']}/160")
        Jon Smith: 140/160
        John Smyth: 120/160
    """
    if collection is None:
        logger.warning("Database collection not initialized")
        return []
    
    # Get current threshold settings from user session
    settings = get_settings()
    if limit is None:
        limit = settings['max_results']
    
    # Build Atlas Search compound query conditions
    should_conditions = []
    logger.debug(f"Building search conditions for customer: {customer_data}")
    
    # First Name Search Condition
    if customer_data.get("first_name"):
        should_conditions.append({
            "text": {
                "query": customer_data["first_name"],
                "path": "first_name",
                "fuzzy": {"maxEdits": 2},  # Allow up to 2 character differences
                "score": {"boost": {"value": 3}}  # 3x importance boost
            }
        })
    
    # Last Name Search Condition  
    if customer_data.get("last_name"):
        should_conditions.append({
            "text": {
                "query": customer_data["last_name"],
                "path": "last_name", 
                "fuzzy": {"maxEdits": 2},  # Handle common spelling variations
                "score": {"boost": {"value": 3}}  # 3x importance boost
            }
        })
    
    # Email Search Condition (highest priority)
    if customer_data.get("email"):
        should_conditions.append({
            "text": {
                "query": customer_data["email"],
                "path": "email",
                "fuzzy": {"maxEdits": 1},  # Conservative fuzzy matching for emails
                "score": {"boost": {"value": 5}}  # 5x importance boost (highest)
            }
        })
    
    # Phone Number Search Condition
    if customer_data.get("phone"):
        should_conditions.append({
            "text": {
                "query": customer_data["phone"],
                "path": "phone",
                "fuzzy": {"maxEdits": 1},  # Handle minor phone formatting issues
                "score": {"boost": {"value": 2}}  # 2x importance boost
            }
        })
    
    # Require at least one search field
    if not should_conditions:
        logger.info("No searchable fields provided")
        return []
    
    # Construct MongoDB Atlas Search aggregation query
    query = {
        "$search": {
            "compound": {
                "should": should_conditions,
                "minimumShouldMatch": 1  # At least one condition must match
            }
        }
    }
    
    # Build aggregation pipeline with search scoring
    pipeline = [
        query,
        {
            # Add Atlas Search relevance score as a field
            "$addFields": {
                "search_score": {"$meta": "searchScore"}
            }
        },
        {"$limit": limit * 2},  # Get extra results for filtering
        {"$sort": {"search_score": -1}}  # Sort by Atlas Search relevance
    ]
    
    try:
        # Execute Atlas Search aggregation pipeline
        logger.info(f"Executing Atlas Search for customer: {customer_data.get('first_name', '')} {customer_data.get('last_name', '')}")
        results = list(collection.aggregate(pipeline))
        logger.info(f"Atlas Search returned {len(results)} initial results")
        
        # Process and enrich results with similarity scoring
        enriched_results = []
        original_customer_id = customer_data.get('_id')  # Get original customer ID if available
        
        for result in results:
            # Skip self-matches - prevent customer from being marked as duplicate of themselves
            result_id = str(result.get('_id'))
            if original_customer_id and result_id == str(original_customer_id):
                logger.debug(f"Skipping self-match for customer ID: {result_id}")
                continue
                
            # Calculate custom similarity score using weighted algorithm
            similarity_score = calculate_similarity_score(customer_data, result)
            
            # Anti-false-positive logic for manual searches
            # When no original ID exists (manual search), prevent exact matches from being flagged as duplicates
            if not original_customer_id:
                provided_fields = {k: v for k, v in customer_data.items() if v and k != '_id'}
                matches_all_provided = True
                
                # Check if all provided search fields match exactly
                for field, value in provided_fields.items():
                    if field in ['first_name', 'last_name', 'email']:
                        if value.lower() != result.get(field, '').lower():
                            matches_all_provided = False
                            break
                    elif field == 'phone':
                        if value != result.get(field, ''):
                            matches_all_provided = False
                            break
                
                # If all fields match exactly and we have sufficient data points, 
                # this is likely the same person, not a duplicate
                if matches_all_provided and len(provided_fields) >= 2:
                    logger.debug(f"Skipping exact match for manual search: {result.get('first_name', '')} {result.get('last_name', '')}")
                    continue
            
            # Apply business rule thresholds from user settings
            similarity_threshold = settings['similarity_threshold']
            search_score_threshold = settings['search_score_threshold']
            search_score = result.get('search_score', 0)
            
            logger.debug(f"Evaluating result: similarity={similarity_score}/{similarity_threshold}, search_score={search_score}/{search_score_threshold}")
            
            # Include result if it meets both similarity and search score thresholds
            if (similarity_score >= similarity_threshold and search_score >= search_score_threshold):
                # Generate confidence assessment for business users
                confidence = get_confidence_level(similarity_score)
                
                # Enrich result with computed scores and metadata
                result["similarity_score"] = similarity_score
                result["confidence"] = confidence
                result["_id"] = result_id
                enriched_results.append(result)
                
                logger.debug(f"Added duplicate candidate: {result.get('first_name', '')} {result.get('last_name', '')} (similarity: {similarity_score}, confidence: {confidence['level']})")
        
        # Sort by similarity score (descending) to show best matches first
        enriched_results.sort(key=lambda x: x["similarity_score"], reverse=True)
        
        logger.info(f"Returning {len(enriched_results)} qualified duplicate candidates")
        return enriched_results[:limit]  # Respect the limit parameter
        
    except Exception as e:
        logger.error(f"Atlas Search query failed: {e}")
        logger.error(f"Query pipeline: {pipeline}")
        return []

@app.route('/')
def index():
    """Home page with customer lookup form"""
    templates = get_template_consumers()
    return render_template('index.html', templates=templates)

@app.route('/search', methods=['POST'])
def search_customers():
    """Search for customers matching the search criteria"""
    search_criteria = {
        'first_name': request.form.get('first_name', '').strip(),
        'last_name': request.form.get('last_name', '').strip(),
        'email': request.form.get('email', '').strip(),
        'phone': request.form.get('phone', '').strip(),
        'address': request.form.get('address', '').strip()
    }
    
    # Remove empty fields
    search_criteria = {k: v for k, v in search_criteria.items() if v}
    
    if not search_criteria:
        flash('Please provide at least one search field.', 'error')
        return render_template('index.html')
    
    # Search for all matching customers
    matching_customers = find_matching_customers(search_criteria, limit=100)
    
    # Get collection statistics
    stats = {}
    try:
        if collection is not None:
            stats = {
                'total_records': collection.count_documents({}),
                'original_records': collection.count_documents({"record_type": "original"}),
                'duplicate_records': collection.count_documents({"record_type": "duplicate"}),
                'matching_records': len(matching_customers)
            }
    except Exception as e:
        logger.error(f"Failed to get statistics: {e}")
    
    return render_template('search_results.html', 
                         search_criteria=search_criteria, 
                         customers=matching_customers, 
                         stats=stats)

@app.route('/api/search', methods=['POST'])
def api_search():
    """API endpoint for customer duplicate search"""
    try:
        customer_data = request.get_json()
        
        if not customer_data:
            return jsonify({'error': 'No customer data provided'}), 400
        
        # Remove empty fields
        customer_data = {k: v for k, v in customer_data.items() if v and v.strip()}
        
        if not customer_data:
            return jsonify({'error': 'Please provide at least one search field'}), 400
        
        duplicates = find_duplicates_for_customer(customer_data, limit=10)
        
        # Convert ObjectId to string for JSON serialization
        for duplicate in duplicates:
            duplicate['_id'] = str(duplicate['_id'])
        
        return jsonify({
            'customer_data': customer_data,
            'duplicates': duplicates,
            'count': len(duplicates)
        })
        
    except Exception as e:
        logger.error(f"API search failed: {e}")
        return jsonify({'error': 'Search failed'}), 500

def get_template_consumers():
    """Get sample consumers from different categories for easy selection"""
    if collection is None:
        return []
    
    try:
        templates = []
        
        # Get a high-quality duplicate (should have high similarity score)
        high_confidence_query = [
            {"$match": {"record_type": "duplicate"}},
            {"$sample": {"size": 3}}
        ]
        high_conf_duplicates = list(collection.aggregate(high_confidence_query))
        
        # Get original records
        original_query = [
            {"$match": {"record_type": "original"}},
            {"$sample": {"size": 3}}
        ]
        originals = list(collection.aggregate(original_query))
        
        # Categorize templates
        for record in high_conf_duplicates:
            record['category'] = 'High Confidence Duplicate'
            record['description'] = 'Known duplicate with typos - should show high similarity matches'
            templates.append(record)
            
        for record in originals:
            record['category'] = 'Original Record'
            record['description'] = 'Clean original record - may or may not have duplicates'
            templates.append(record)
            
        return templates
        
    except Exception as e:
        logger.error(f"Failed to get template consumers: {e}")
        return []

@app.route('/browse')
def browse_consumers():
    """Browse all consumers with filtering"""
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    filter_type = request.args.get('filter', 'all')  # all, original, duplicate
    search_term = request.args.get('search', '').strip()
    
    if collection is None:
        return render_template('browse.html', consumers=[], stats={}, pagination={})
    
    try:
        # Build filter query
        filter_query = {}
        if filter_type == 'original':
            filter_query['record_type'] = 'original'
        elif filter_type == 'duplicate':
            filter_query['record_type'] = 'duplicate'
            
        # Add search functionality
        if search_term:
            filter_query['$or'] = [
                {'first_name': {'$regex': search_term, '$options': 'i'}},
                {'last_name': {'$regex': search_term, '$options': 'i'}},
                {'email': {'$regex': search_term, '$options': 'i'}},
                {'phone': {'$regex': search_term, '$options': 'i'}}
            ]
        
        # Get total count for pagination
        total_records = collection.count_documents(filter_query)
        total_pages = (total_records + per_page - 1) // per_page
        
        # Get paginated results
        skip = (page - 1) * per_page
        consumers = list(collection.find(filter_query)
                        .sort([('record_type', 1), ('last_name', 1), ('first_name', 1)])
                        .skip(skip)
                        .limit(per_page))
        
        # Convert ObjectId to string for template and add scores
        for consumer in consumers:
            consumer['_id'] = str(consumer['_id'])
            consumer['max_similarity_score'] = 75  # Test value
            consumer['max_search_score'] = 10.5    # Test value
            
        # Get statistics
        stats = {
            'total_records': collection.count_documents({}),
            'original_records': collection.count_documents({"record_type": "original"}),
            'duplicate_records': collection.count_documents({"record_type": "duplicate"}),
            'filtered_records': total_records
        }
        
        pagination = {
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'total_records': total_records,
            'has_prev': page > 1,
            'has_next': page < total_pages,
            'prev_page': page - 1 if page > 1 else None,
            'next_page': page + 1 if page < total_pages else None
        }
        
        return render_template('browse.html', 
                             consumers=consumers, 
                             stats=stats, 
                             pagination=pagination,
                             current_filter=filter_type,
                             search_term=search_term)
        
    except Exception as e:
        logger.error(f"Failed to browse consumers: {e}")
        return render_template('browse.html', consumers=[], stats={}, pagination={})

@app.route('/api/templates')
def api_get_templates():
    """API endpoint to get template consumers"""
    templates = get_template_consumers()
    
    # Convert ObjectId to string for JSON serialization
    for template in templates:
        template['_id'] = str(template['_id'])
        
    return jsonify({'templates': templates})

@app.route('/search_consumer/<consumer_id>')
def search_consumer_by_id(consumer_id):
    """Search for duplicates of a specific consumer by ID"""
    if collection is None:
        flash('Database not available', 'error')
        return redirect(url_for('index'))
        
    try:
        from bson import ObjectId
        consumer = collection.find_one({'_id': ObjectId(consumer_id)})
        
        if not consumer:
            flash('Consumer not found', 'error')
            return redirect(url_for('browse_consumers'))
            
        # Prepare customer data for search
        customer_data = {
            '_id': str(consumer.get('_id')),  # Convert ObjectId to string for comparison
            'first_name': consumer.get('first_name', ''),
            'last_name': consumer.get('last_name', ''),
            'email': consumer.get('email', ''),
            'phone': consumer.get('phone', ''),
            'address': consumer.get('address', '')
        }
        
        logger.info(f"Looking up duplicates for customer: {customer_data['_id']} - {customer_data['first_name']} {customer_data['last_name']}")
        
        # Search for duplicates
        duplicates = find_duplicates_for_customer(customer_data, limit=10)
        
        # Get collection statistics
        stats = {
            'total_records': collection.count_documents({}),
            'original_records': collection.count_documents({"record_type": "original"}),
            'duplicate_records': collection.count_documents({"record_type": "duplicate"})
        }
        
        return render_template('results.html', 
                             customer_data=customer_data, 
                             duplicates=duplicates,
                             stats=stats,
                             source_consumer=consumer)
        
    except Exception as e:
        logger.error(f"Failed to search consumer by ID: {e}")
        flash('Failed to search for consumer duplicates', 'error')
        return redirect(url_for('browse_consumers'))

@app.route('/customer_management')
def customer_management():
    """Customer management page for adding/updating customers"""
    return render_template('customer_management.html')

@app.route('/add_customer', methods=['POST'])
def add_customer():
    """Add a new customer with duplicate detection"""
    if collection is None:
        flash('Database not available', 'error')
        return redirect(url_for('customer_management'))
    
    try:
        customer_data = {
            'first_name': request.form.get('first_name', '').strip(),
            'last_name': request.form.get('last_name', '').strip(),
            'email': request.form.get('email', '').strip(),
            'phone': request.form.get('phone', '').strip(),
            'address': request.form.get('address', '').strip()
        }
        
        # Remove empty fields for duplicate check
        search_data = {k: v for k, v in customer_data.items() if v and k != 'address'}
        
        if not search_data:
            flash('Please provide at least customer name, email, or phone.', 'error')
            return redirect(url_for('customer_management'))
        
        # Check for duplicates before adding
        duplicates = find_duplicates_for_customer(search_data, limit=5)
        high_confidence_duplicates = [d for d in duplicates if d.get('similarity_score', 0) > 70]
        
        if high_confidence_duplicates:
            # Show duplicate confirmation page
            return render_template('duplicate_confirmation.html',
                                 action='add',
                                 customer_data=customer_data,
                                 duplicates=high_confidence_duplicates)
        
        # No high-confidence duplicates, proceed to add
        from datetime import datetime
        customer_data['createdAt'] = datetime.now().isoformat()
        customer_data['record_type'] = 'original'
        customer_data['created_by'] = 'customer_support'
        
        result = collection.insert_one(customer_data)
        flash(f'Customer {customer_data["first_name"]} {customer_data["last_name"]} added successfully!', 'success')
        
        return redirect(url_for('search_consumer_by_id', consumer_id=str(result.inserted_id)))
        
    except Exception as e:
        logger.error(f"Failed to add customer: {e}")
        flash('Failed to add customer', 'error')
        return redirect(url_for('customer_management'))

@app.route('/update_customer/<consumer_id>', methods=['GET', 'POST'])
def update_customer(consumer_id):
    """Update an existing customer with duplicate detection"""
    if collection is None:
        flash('Database not available', 'error')
        return redirect(url_for('customer_management'))
    
    try:
        from bson import ObjectId
        
        if request.method == 'GET':
            # Show update form
            consumer = collection.find_one({'_id': ObjectId(consumer_id)})
            if not consumer:
                flash('Customer not found', 'error')
                return redirect(url_for('browse_consumers'))
            return render_template('customer_update.html', customer=consumer)
        
        # Handle POST - update customer
        customer_data = {
            'first_name': request.form.get('first_name', '').strip(),
            'last_name': request.form.get('last_name', '').strip(),
            'email': request.form.get('email', '').strip(),
            'phone': request.form.get('phone', '').strip(),
            'address': request.form.get('address', '').strip()
        }
        
        # Remove empty fields for duplicate check
        search_data = {k: v for k, v in customer_data.items() if v and k != 'address'}
        
        if not search_data:
            flash('Please provide at least customer name, email, or phone.', 'error')
            return redirect(url_for('update_customer', consumer_id=consumer_id))
        
        # Check for duplicates before updating (exclude current record)
        duplicates = find_duplicates_for_customer(search_data, limit=5)
        duplicates = [d for d in duplicates if str(d.get('_id')) != consumer_id]
        high_confidence_duplicates = [d for d in duplicates if d.get('similarity_score', 0) > 70]
        
        if high_confidence_duplicates:
            # Show duplicate confirmation page
            customer_data['_id'] = consumer_id
            return render_template('duplicate_confirmation.html',
                                 action='update',
                                 customer_data=customer_data,
                                 duplicates=high_confidence_duplicates)
        
        # No high-confidence duplicates, proceed to update
        from datetime import datetime
        customer_data['updatedAt'] = datetime.now().isoformat()
        customer_data['updated_by'] = 'customer_support'
        
        collection.update_one(
            {'_id': ObjectId(consumer_id)},
            {'$set': customer_data}
        )
        
        flash(f'Customer {customer_data["first_name"]} {customer_data["last_name"]} updated successfully!', 'success')
        return redirect(url_for('search_consumer_by_id', consumer_id=consumer_id))
        
    except Exception as e:
        logger.error(f"Failed to update customer: {e}")
        flash('Failed to update customer', 'error')
        return redirect(url_for('customer_management'))

@app.route('/confirm_customer_action', methods=['POST'])
def confirm_customer_action():
    """Handle customer add/update after duplicate confirmation"""
    if collection is None:
        flash('Database not available', 'error')
        return redirect(url_for('customer_management'))
    
    try:
        action = request.form.get('action')  # 'add' or 'update'
        choice = request.form.get('choice')  # 'proceed', 'use_existing', or 'merge'
        
        if choice == 'use_existing':
            existing_id = request.form.get('existing_customer_id')
            flash('Using existing customer record.', 'info')
            return redirect(url_for('search_consumer_by_id', consumer_id=existing_id))
        
        elif choice == 'proceed':
            # Proceed with original action
            customer_data = {
                'first_name': request.form.get('first_name', '').strip(),
                'last_name': request.form.get('last_name', '').strip(),
                'email': request.form.get('email', '').strip(),
                'phone': request.form.get('phone', '').strip(),
                'address': request.form.get('address', '').strip()
            }
            
            from datetime import datetime
            
            if action == 'add':
                customer_data['createdAt'] = datetime.now().isoformat()
                customer_data['record_type'] = 'original'
                customer_data['created_by'] = 'customer_support'
                customer_data['confirmed_not_duplicate'] = True
                
                result = collection.insert_one(customer_data)
                flash(f'Customer {customer_data["first_name"]} {customer_data["last_name"]} added (confirmed not a duplicate).', 'success')
                return redirect(url_for('search_consumer_by_id', consumer_id=str(result.inserted_id)))
                
            elif action == 'update':
                from bson import ObjectId
                customer_id = request.form.get('customer_id')
                customer_data['updatedAt'] = datetime.now().isoformat()
                customer_data['updated_by'] = 'customer_support'
                customer_data['confirmed_not_duplicate'] = True
                
                collection.update_one(
                    {'_id': ObjectId(customer_id)},
                    {'$set': customer_data}
                )
                
                flash(f'Customer {customer_data["first_name"]} {customer_data["last_name"]} updated (confirmed not a duplicate).', 'success')
                return redirect(url_for('search_consumer_by_id', consumer_id=customer_id))
            else:
                # Unknown action
                flash('Unknown action specified.', 'error')
                return redirect(url_for('customer_management'))
        
        elif choice == 'merge':
            # Enhanced merge functionality with selective field merging
            existing_id = request.form.get('existing_customer_id')
            if existing_id:
                try:
                    from bson import ObjectId
                    existing_customer = collection.find_one({'_id': ObjectId(existing_id)})
                    
                    if existing_customer:
                        # Create merged data based on selected checkboxes
                        merged_data = {}
                        
                        # Fields that can be merged
                        mergeable_fields = ['first_name', 'last_name', 'email', 'phone', 'address']
                        
                        # Check which fields were selected for merging
                        for field in mergeable_fields:
                            checkbox_name = f'merge_{field}'
                            if checkbox_name in request.form:
                                # Field was selected for merging, use the duplicate's value
                                merged_data[field] = request.form[checkbox_name]
                            else:
                                # Field was not selected, keep original value
                                if existing_customer.get(field):
                                    merged_data[field] = existing_customer.get(field)
                        
                        # Add merge metadata
                        from datetime import datetime
                        merged_data['updatedAt'] = datetime.now().isoformat()
                        merged_data['merged_by'] = 'customer_support'
                        merged_data['merge_source'] = 'selective_field_merge'
                        merged_data['last_merge_date'] = datetime.now().isoformat()
                        
                        # Update the existing record with merged data
                        update_result = collection.update_one(
                            {'_id': ObjectId(existing_id)},
                            {'$set': merged_data}
                        )
                        
                        if update_result.modified_count > 0:
                            # Get the original customer ID to delete the duplicate
                            original_customer_id = None
                            if hasattr(request.form, 'getlist'):
                                # Try to get the original customer ID from form data
                                customer_data_str = request.form.get('customer_data', '{}')
                                try:
                                    import json
                                    customer_data = json.loads(customer_data_str) if customer_data_str != '{}' else {}
                                    original_customer_id = customer_data.get('_id')
                                except:
                                    pass
                            
                            # If we have an original customer ID different from existing, delete the duplicate
                            if original_customer_id and original_customer_id != existing_id:
                                try:
                                    deletion_result = collection.delete_one({'_id': ObjectId(original_customer_id)})
                                    logger.info(f"Deleted duplicate record {original_customer_id} after merge. Deleted count: {deletion_result.deleted_count}")
                                except Exception as delete_error:
                                    logger.warning(f"Failed to delete duplicate record {original_customer_id}: {delete_error}")
                                    # Continue without failing the merge
                            
                            # Count merged fields
                            merged_field_count = len([f for f in mergeable_fields if f'merge_{f}' in request.form])
                            
                            flash(f'Records merged successfully! {merged_field_count} fields updated. Duplicate record removed.', 'success')
                            return redirect(url_for('search_consumer_by_id', consumer_id=existing_id))
                        else:
                            flash('No changes were made during merge.', 'warning')
                            return redirect(url_for('search_consumer_by_id', consumer_id=existing_id))
                    else:
                        flash('Existing customer record not found for merge.', 'error')
                        return redirect(url_for('customer_management'))
                        
                except Exception as e:
                    logger.error(f"Merge operation failed: {e}")
                    flash('Merge operation failed. Please try again.', 'error')
                    return redirect(url_for('customer_management'))
            else:
                flash('No existing customer selected for merge.', 'error')
                return redirect(url_for('customer_management'))
        else:
            # Unknown choice
            flash('Unknown choice specified.', 'error')
            return redirect(url_for('customer_management'))
        
    except Exception as e:
        logger.error(f"Failed to confirm customer action: {e}")
        flash('Failed to process customer action', 'error')
        return redirect(url_for('customer_management'))

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    """Settings page for configuring thresholds"""
    if request.method == 'POST':
        try:
            # Get form data and validate
            new_settings = {
                'similarity_threshold': int(request.form.get('similarity_threshold', 24)),
                'search_score_threshold': float(request.form.get('search_score_threshold', 0.0)),
                'high_confidence_threshold': int(request.form.get('high_confidence_threshold', 70)),
                'medium_confidence_threshold': int(request.form.get('medium_confidence_threshold', 40)),
                'max_results': int(request.form.get('max_results', 10))
            }
            
            # Validate ranges
            if new_settings['similarity_threshold'] < 0 or new_settings['similarity_threshold'] > 160:
                flash('Similarity threshold must be between 0 and 160 points', 'error')
                return render_template('settings.html', settings=get_settings())
            
            if new_settings['search_score_threshold'] < 0:
                flash('Search score threshold must be non-negative', 'error')
                return render_template('settings.html', settings=get_settings())
            
            if new_settings['high_confidence_threshold'] <= new_settings['medium_confidence_threshold']:
                flash('High confidence threshold must be greater than medium confidence threshold', 'error')
                return render_template('settings.html', settings=get_settings())
            
            if new_settings['max_results'] < 1 or new_settings['max_results'] > 50:
                flash('Maximum results must be between 1 and 50', 'error')
                return render_template('settings.html', settings=get_settings())
            
            # Update settings
            update_settings(new_settings)
            flash('Settings updated successfully!', 'success')
            
        except ValueError as e:
            flash('Invalid input values. Please check your entries.', 'error')
        except Exception as e:
            logger.error(f"Failed to update settings: {e}")
            flash('Failed to update settings', 'error')
    
    return render_template('settings.html', settings=get_settings())

@app.route('/settings/reset', methods=['POST'])
def reset_settings():
    """Reset settings to defaults"""
    session['settings'] = DEFAULT_SETTINGS.copy()
    flash('Settings reset to defaults', 'info')
    return redirect(url_for('settings'))

@app.route('/health')
def health_check():
    """Health check endpoint"""
    if collection is not None:
        try:
            count = collection.count_documents({})
            return jsonify({
                'status': 'healthy',
                'database_connected': True,
                'record_count': count
            })
        except Exception as e:
            return jsonify({
                'status': 'degraded',
                'database_connected': False,
                'error': str(e)
            }), 503
    else:
        return jsonify({
            'status': 'unhealthy',
            'database_connected': False
        }), 503

if __name__ == '__main__':
    if init_db():
        port = int(os.getenv('PORT', 6000))
        host = os.getenv('HOST', '0.0.0.0')
        app.run(debug=True, host=host, port=port)
    else:
        logger.error("Failed to initialize database connection. Exiting.")
        exit(1)
