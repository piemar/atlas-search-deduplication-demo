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

def get_confidence_level(score):
    """Get confidence level and styling class based on score and current settings"""
    settings = get_settings()
    high_threshold = settings['high_confidence_threshold']
    medium_threshold = settings['medium_confidence_threshold']
    
    if score > high_threshold:
        return {"level": "High Confidence", "class": "high", "icon": "🚨", "description": "Very likely duplicate"}
    elif score > medium_threshold:
        return {"level": "Possible Match", "class": "medium", "icon": "⚠️", "description": "Potential duplicate"}
    else:
        return {"level": "Worth Reviewing", "class": "low", "icon": "❓", "description": "May be duplicate - review needed"}

def find_duplicates_for_customer(customer_data, limit=None):
    """Find potential duplicates for a given customer"""
    if collection is None:
        return []
    
    # Get current settings for thresholds
    settings = get_settings()
    if limit is None:
        limit = settings['max_results']
    
    # Create search conditions based on provided data
    should_conditions = []
    
    if customer_data.get("first_name"):
        should_conditions.append({
            "text": {
                "query": customer_data["first_name"],
                "path": "first_name",
                "fuzzy": {"maxEdits": 2},
                "score": {"boost": {"value": 3}}
            }
        })
    
    if customer_data.get("last_name"):
        should_conditions.append({
            "text": {
                "query": customer_data["last_name"],
                "path": "last_name",
                "fuzzy": {"maxEdits": 2},
                "score": {"boost": {"value": 3}}
            }
        })
    
    if customer_data.get("email"):
        should_conditions.append({
            "text": {
                "query": customer_data["email"],
                "path": "email",
                "fuzzy": {"maxEdits": 1},
                "score": {"boost": {"value": 5}}
            }
        })
    
    if customer_data.get("phone"):
        should_conditions.append({
            "text": {
                "query": customer_data["phone"],
                "path": "phone",
                "fuzzy": {"maxEdits": 1},
                "score": {"boost": {"value": 2}}
            }
        })
    
    if not should_conditions:
        return []
    
    # Build the search query
    query = {
        "$search": {
            "compound": {
                "should": should_conditions,
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
        {"$limit": limit},
        {"$sort": {"search_score": -1}}
    ]
    
    try:
        results = list(collection.aggregate(pipeline))
        
        # Calculate similarity scores and add confidence levels
        # Only include results with similarity above 30% (48 points out of 160 total possible)
        enriched_results = []
        original_customer_id = customer_data.get('_id')  # Get original customer ID if available
        
        for result in results:
            # Skip if this is the same customer (same ID)
            result_id = str(result.get('_id'))
            if original_customer_id and result_id == str(original_customer_id):
                continue
                
            similarity_score = calculate_similarity_score(customer_data, result)
            
            # For manual searches without original customer ID, prevent same-person false positives
            if not original_customer_id:
                # Check if all provided fields match exactly (indicating same person)
                provided_fields = {k: v for k, v in customer_data.items() if v and k != '_id'}
                matches_all_provided = True
                
                for field, value in provided_fields.items():
                    if field in ['first_name', 'last_name', 'email']:
                        if value.lower() != result.get(field, '').lower():
                            matches_all_provided = False
                            break
                    elif field == 'phone':
                        if value != result.get(field, ''):
                            matches_all_provided = False
                            break
                
                # If all provided fields match exactly, skip (likely same person)
                if matches_all_provided and len(provided_fields) >= 2:
                    continue
            
            # Filter by similarity threshold and search score threshold from settings
            logger.debug(f"Checking thresholds: similarity={similarity_score} >= {settings['similarity_threshold']}, search_score={result.get('search_score', 0)} >= {settings['search_score_threshold']}")
            if (similarity_score >= settings['similarity_threshold'] and 
                result.get('search_score', 0) >= settings['search_score_threshold']):
                confidence = get_confidence_level(similarity_score)
                
                result["similarity_score"] = similarity_score
                result["confidence"] = confidence
                result["_id"] = result_id
                enriched_results.append(result)
        
        # Sort by similarity score descending
        enriched_results.sort(key=lambda x: x["similarity_score"], reverse=True)
        
        return enriched_results
        
    except Exception as e:
        logger.error(f"Search query failed: {e}")
        return []

@app.route('/')
def index():
    """Home page with customer lookup form"""
    templates = get_template_consumers()
    return render_template('index.html', templates=templates)

@app.route('/search', methods=['POST'])
def search_duplicates():
    """Search for customer duplicates"""
    customer_data = {
        'first_name': request.form.get('first_name', '').strip(),
        'last_name': request.form.get('last_name', '').strip(),
        'email': request.form.get('email', '').strip(),
        'phone': request.form.get('phone', '').strip()
    }
    
    # Remove empty fields
    customer_data = {k: v for k, v in customer_data.items() if v}
    
    if not customer_data:
        flash('Please provide at least one search field.', 'error')
        return render_template('index.html')
    
    # Search for duplicates
    duplicates = find_duplicates_for_customer(customer_data, limit=10)
    
    # Get collection statistics
    stats = {}
    try:
        if collection is not None:
            stats = {
                'total_records': collection.count_documents({}),
                'original_records': collection.count_documents({"record_type": "original"}),
                'duplicate_records': collection.count_documents({"record_type": "duplicate"})
            }
    except Exception as e:
        logger.error(f"Failed to get statistics: {e}")
    
    return render_template('results.html', 
                         customer_data=customer_data, 
                         duplicates=duplicates,
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
                        collection.update_one(
                            {'_id': ObjectId(existing_id)},
                            {'$set': merged_data}
                        )
                        
                        # Count merged fields
                        merged_field_count = len([f for f in mergeable_fields if f'merge_{f}' in request.form])
                        
                        flash(f'Records merged successfully! {merged_field_count} fields updated in existing customer record.', 'success')
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
