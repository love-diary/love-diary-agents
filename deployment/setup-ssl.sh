#!/bin/bash
# SSL Setup Script for Love Diary Agent Service
# This script sets up nginx reverse proxy and Let's Encrypt SSL

set -e  # Exit on error

DOMAIN="agents.lovediary.io"
EMAIL="your-email@example.com"  # Change this to your email

echo "======================================"
echo "Love Diary Agent Service - SSL Setup"
echo "======================================"
echo "Domain: $DOMAIN"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use sudo)"
    exit 1
fi

# Update system
echo "Step 1: Updating system..."
apt-get update
apt-get upgrade -y

# Install nginx
echo ""
echo "Step 2: Installing nginx..."
apt-get install -y nginx

# Install certbot
echo ""
echo "Step 3: Installing certbot..."
apt-get install -y certbot python3-certbot-nginx

# Create certbot webroot directory
mkdir -p /var/www/certbot

# Stop nginx temporarily
echo ""
echo "Step 4: Stopping nginx temporarily..."
systemctl stop nginx

# Obtain SSL certificate
echo ""
echo "Step 5: Obtaining SSL certificate from Let's Encrypt..."
echo "NOTE: Make sure $DOMAIN points to this server's IP!"
read -p "Press Enter to continue or Ctrl+C to abort..."

certbot certonly --standalone \
    --preferred-challenges http \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"

# Copy nginx config
echo ""
echo "Step 6: Setting up nginx configuration..."
if [ -f "nginx.conf" ]; then
    cp nginx.conf /etc/nginx/sites-available/$DOMAIN
    ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
else
    echo "ERROR: nginx.conf not found in current directory"
    exit 1
fi

# Test nginx config
echo ""
echo "Step 7: Testing nginx configuration..."
nginx -t

# Start nginx
echo ""
echo "Step 8: Starting nginx..."
systemctl start nginx
systemctl enable nginx

# Setup certbot auto-renewal
echo ""
echo "Step 9: Setting up automatic SSL renewal..."
systemctl enable certbot.timer
systemctl start certbot.timer

# Configure firewall (if ufw is installed)
if command -v ufw &> /dev/null; then
    echo ""
    echo "Step 10: Configuring firewall..."
    ufw allow 'Nginx Full'
    ufw delete allow 8000  # Remove direct access to port 8000 if exists
fi

echo ""
echo "======================================"
echo "✓ SSL Setup Complete!"
echo "======================================"
echo ""
echo "Your agent service is now available at:"
echo "  https://$DOMAIN"
echo ""
echo "SSL certificate will auto-renew via certbot.timer"
echo ""
echo "Next steps:"
echo "1. Update frontend to use https://$DOMAIN"
echo "2. Test: curl https://$DOMAIN/health"
echo "3. Check logs: sudo tail -f /var/log/nginx/agents.lovediary.io.error.log"
echo ""
