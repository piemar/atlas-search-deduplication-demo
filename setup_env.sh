#!/bin/bash
# Setup script for secure environment configuration

set -e

echo "🔧 MongoDB Atlas Search Deduplication Demo - Environment Setup"
echo "=============================================================="

# Check if .env already exists
if [ -f ".env" ]; then
    echo "⚠️  .env file already exists!"
    read -p "Do you want to overwrite it? (y/N): " overwrite
    if [ "$overwrite" != "y" ] && [ "$overwrite" != "Y" ]; then
        echo "Setup cancelled."
        exit 0
    fi
fi

# Copy template
cp env.example .env
echo "✅ Created .env from template"

# Make sure .env is in .gitignore
if ! grep -q "^\.env$" .gitignore 2>/dev/null; then
    echo ".env" >> .gitignore
    echo "✅ Added .env to .gitignore"
fi

echo ""
echo "🔒 SECURITY REMINDERS:"
echo "======================"
echo "1. ✅ .env file is already in .gitignore"
echo "2. ✅ Pre-commit hook is installed to prevent accidental commits"
echo "3. 🔥 NEVER commit real credentials to version control"
echo "4. 🔄 Rotate credentials regularly"
echo ""

echo "📝 NEXT STEPS:"
echo "=============="
echo "1. Edit .env file with your MongoDB Atlas credentials:"
echo "   nano .env"
echo ""
echo "2. Replace these placeholders:"
echo "   - <username>: Your MongoDB Atlas username"
echo "   - <password>: Your MongoDB Atlas password"  
echo "   - <cluster-url>: Your cluster URL (e.g., cluster0.abc123.mongodb.net)"
echo "   - <app-name>: Your application name"
echo ""
echo "3. Test the setup:"
echo "   python data_generator.py"
echo ""

# Test pre-commit hook
if [ -f ".git/hooks/pre-commit" ] && [ -x ".git/hooks/pre-commit" ]; then
    echo "✅ Pre-commit hook is active"
else
    echo "⚠️  Pre-commit hook not found - manual setup required"
fi

echo ""
echo "🛡️  Your environment is now secure!"
