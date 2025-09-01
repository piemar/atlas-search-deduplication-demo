# MongoDB Atlas Search Deduplication Demo

This demo shows how to use MongoDB Atlas Search to detect and handle near-duplicate consumer records with realistic typos and variations.

## 🚀 Features
- **Realistic data generation** with 10,000 consumer records
- **Intelligent duplicate creation** with 20% synthetic duplicates containing realistic typos
- **Advanced fuzzy search** using MongoDB Atlas Search
- **Similarity scoring** with confidence levels
- **Comprehensive error handling** and logging
- **Environment-based configuration** for security

## 📁 Components
- `run_webapp.py`: **Main web application launcher** - Professional customer support interface
- `app.py`: Flask web application with REST API endpoints
- `templates/`: HTML templates for the web interface
- `static/css/`: Professional styling for the customer support UI
- `data_generator.py`: Generates 10,000 sample consumer records with 20% duplicates containing realistic typos
- `search_query_example.py`: Console demo of fuzzy search with similarity scoring  
- `batch_deduplication.py`: Comprehensive batch processing script for production deduplication
- `search_index_definition.json`: Atlas Search index mapping configuration
- `env.example`: Template for environment variables
- `requirements.txt`: Python dependencies with version pinning
- `terraform/`: Infrastructure-as-Code templates for Atlas Search index

## 🛠️ Setup

### 1. Environment Configuration

**Quick Setup (Recommended):**
```bash
./setup_env.sh
```

**Manual Setup:**
Copy the environment template and configure your MongoDB connection:
```bash
cp env.example .env
```

Edit `.env` with your MongoDB Atlas credentials:
```env
MONGODB_URI=mongodb+srv://username:password@cluster-url/?retryWrites=true&w=majority&appName=your-app
DB_NAME=dedup_demo
COLLECTION_NAME=consumers
NUM_RECORDS=10000
DUPLICATE_PERCENTAGE=0.2
```

### 2. Database Setup
1. Create a new database in your Atlas cluster named `dedup_demo`
2. Create a Search Index using the contents of `search_index_definition.json`

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Generate Sample Data
```bash
python data_generator.py
```
This will create 10,000 consumer records with 8,000 originals and 2,000 duplicates containing realistic typos.

### 5. Run the Application

**Web Application (Customer Support Interface):**
```bash
python run_webapp.py
```
This launches a professional web interface designed for customer support agents to look up customers and find potential duplicates. Open your browser to `http://localhost:6000` to access the application.
Check Health: Visit http://localhost:6000/health to 
**Single Record Demo (Console):**
```bash
python search_query_example.py
```
This will demonstrate finding duplicates for a single record with similarity scoring and confidence levels.

**Batch Processing (Production):**
```bash
python batch_deduplication.py
```
This will process all records in the collection, generate a comprehensive report, and identify high-confidence duplicates for cleanup.

## 📊 What You'll See

The demo generates realistic consumer data with various types of typos:
- **Keyboard adjacent errors**: 'a' → 's', 'e' → 'r'
- **Character transposition**: 'john' → 'jhon'
- **Missing characters**: 'smith' → 'smth'
- **Extra characters**: 'jones' → 'jonesa'

The search demo will show:
- **Search scores** from Atlas Search
- **Similarity percentages** from custom scoring
- **Confidence levels**: High (>70%), Possible (40-70%), Low (<40%)
- **Synthetic duplicate confirmation** for testing

## 🔧 Optional: Deploy Atlas Search Index via Terraform
If you're using Infrastructure-as-Code (IaC), you can define your index via Terraform:

1. Set up Atlas Provider and authenticate
2. Use the `terraform/search_index.tf` and `terraform/variables.tf` templates
3. Run:
```bash
cd terraform
terraform init
terraform apply -var="project_id=<your_project_id>" -var="cluster_name=<your_cluster_name>"
```

This will create the `dedup_index` on `dedup_demo.consumers` collection.

## 🎯 Use Cases
- **Customer Support Interface**: Agents can quickly search for duplicate customer records during support calls
- **Customer data deduplication** in CRM systems
- **Lead deduplication** in marketing databases  
- **User account cleanup** in authentication systems
- **Data quality assessment** before migration
- **Fraud detection** with similar identities

## 🌐 Web Application Features
The customer support web interface provides:
- **Professional UI** designed for support agents
- **Fuzzy search** with partial customer information
- **Confidence levels** (High, Possible, Low) with visual indicators
- **Side-by-side comparison** of original vs potential duplicates
- **REST API endpoints** for integration with other systems
- **Responsive design** works on desktop and mobile
- **Real-time statistics** showing database status

## 🔍 How It Works
1. **Data Generation**: Creates realistic consumer profiles with controlled duplicates
2. **Atlas Search**: Uses fuzzy matching with configurable edit distances
3. **Similarity Scoring**: Combines multiple field comparisons with weighted scoring
4. **Confidence Assessment**: Categorizes matches by likelihood of being duplicates

## 📝 Configuration Options

Customize behavior via environment variables:
- `NUM_RECORDS`: Total records to generate (default: 10,000)
- `DUPLICATE_PERCENTAGE`: Percentage of duplicates (default: 0.2 = 20%)
- `DB_NAME`: Database name (default: 'dedup_demo')
- `COLLECTION_NAME`: Collection name (default: 'consumers')

## 🛡️ Security Protection

This repository includes multiple layers of protection against accidentally committing credentials:

### **Automated Protection**
- **✅ Enhanced .gitignore**: Blocks all `.env` variations
- **✅ Pre-commit hook**: Prevents committing .env files with colored warnings
- **✅ Secret detection**: Warns about potential secrets in any files
- **✅ Setup script**: `./setup_env.sh` for secure environment creation

### **Testing Protection**
Try to commit a `.env` file and see the protection in action:
```bash
echo "SECRET=test" > .env
git add .env -f  # Force add (bypasses .gitignore)
git commit -m "test"  # This will be blocked by pre-commit hook!
```

### **Additional Security Methods**

**1. Pre-commit Package (Advanced)**
```bash
pip install pre-commit
pre-commit install
```
This uses the included `.pre-commit-config.yaml` with GitGuardian secret scanning.

**2. IDE Configuration**
- **VS Code**: Install "GitLens" extension for commit protection
- **PyCharm**: Enable "Git" > "Pre-commit hooks" in settings

**3. Repository Scanning**
```bash
# Scan for existing secrets
git log --all --full-history -- "*.env*"

# Remove from history if found
git filter-branch --force --index-filter 'git rm --cached --ignore-unmatch .env' --prune-empty --tag-name-filter cat -- --all
```

## 🚨 Security Best Practices
- **Never commit** `.env` files with real credentials
- **Rotate credentials** regularly (every 90 days)
- **Use MongoDB Atlas IP whitelist** for production deployments
- **Consider MongoDB Atlas Private Endpoints** for sensitive data
- **Monitor access logs** for unusual activity
- **Use separate credentials** for development/staging/production