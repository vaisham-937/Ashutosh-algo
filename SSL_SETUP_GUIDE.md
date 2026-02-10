# SSL/HTTPS Setup Guide

This guide explains how to enable HTTPS for your trading application so that Zerodha and other services accept your webhook URLs.

## Quick Start (Testing)

For local testing or development, use self-signed certificates:

### Step 1: Generate Self-Signed Certificate

```bash
# Activate virtual environment
myvenv\Scripts\activate

# Generate SSL certificate
python generate_ssl_cert.py
```

This creates:
- `ssl_cert.pem` - SSL certificate
- `ssl_key.pem` - Private key

### Step 2: Start HTTPS Server

```bash
# Windows
start_https.bat

# Or manually
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --ssl-keyfile=ssl_key.pem --ssl-certfile=ssl_cert.pem
```

### Step 3: Access Dashboard

Open your browser to:
- `https://localhost:8000/?user_id=1`
- `https://134.195.138.91:8000/?user_id=1`

**Note**: You'll see a security warning because it's a self-signed certificate. Click "Advanced" → "Proceed to site" to continue.

### Webhook URL

Your webhook URL for Chartink/Zerodha:
```
https://134.195.138.91:8000/webhook/chartink?user_id=1
```

---

## Production Setup (Let's Encrypt - FREE)

> **⚠️ IMPORTANT**: Self-signed certificates may not work with Zerodha webhooks. For production, use Let's Encrypt (free, trusted certificates).

### Prerequisites

- Domain name pointing to your server IP (e.g., `trading.yourdomain.com`)
- SSH access to your VPS server
- Port 80 and 443 open in firewall

### Step 1: Install Certbot

SSH into your server:

```bash
ssh root@134.195.138.91
```

Install Certbot (for Ubuntu/Debian):

```bash
# Update package list
sudo apt update

# Install Certbot and required packages
sudo apt install certbot python3-certbot-nginx -y
```

For other Linux distributions, see: https://certbot.eff.org/

### Step 2: Obtain SSL Certificate

```bash
# Stop your application if running
# (Let's Encrypt needs port 80 temporarily)

# Obtain certificate
sudo certbot certonly --standalone -d trading.yourdomain.com

# Follow the prompts:
# - Enter your email address
# - Agree to terms of service
# - Choose whether to share email with EFF
```

Certificates will be saved to:
- Certificate: `/etc/letsencrypt/live/trading.yourdomain.com/fullchain.pem`
- Private Key: `/etc/letsencrypt/live/trading.yourdomain.com/privkey.pem`

### Step 3: Update Application

Edit your startup script to use Let's Encrypt certificates:

```bash
python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 443 \
  --ssl-keyfile=/etc/letsencrypt/live/trading.yourdomain.com/privkey.pem \
  --ssl-certfile=/etc/letsencrypt/live/trading.yourdomain.com/fullchain.pem
```

**Note**: Port 443 requires root/sudo access. Run with sudo:

```bash
sudo /path/to/myvenv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 443 \
  --ssl-keyfile=/etc/letsencrypt/live/trading.yourdomain.com/privkey.pem \
  --ssl-certfile=/etc/letsencrypt/live/trading.yourdomain.com/fullchain.pem
```

### Step 4: Auto-Renewal

Let's Encrypt certificates expire after 90 days. Set up auto-renewal:

```bash
# Test renewal process
sudo certbot renew --dry-run

# If successful, renewal will happen automatically via cron
# Check with:
sudo systemctl status certbot.timer
```

### Step 5: Configure Webhook

Update your Zerodha/Chartink webhook URL to:
```
https://trading.yourdomain.com/webhook/chartink?user_id=1
```

---

## Using nginx as Reverse Proxy (Recommended)

For production, it's recommended to use nginx as a reverse proxy:

### Benefits
- Handles SSL termination
- Better performance
- Easier certificate management
- Can serve multiple applications

### Setup

1. **Install nginx**:
```bash
sudo apt install nginx -y
```

2. **Configure nginx** (`/etc/nginx/sites-available/trading`):
```nginx
server {
    listen 80;
    server_name trading.yourdomain.com;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name trading.yourdomain.com;

    # SSL certificate
    ssl_certificate /etc/letsencrypt/live/trading.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/trading.yourdomain.com/privkey.pem;
    
    # SSL settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Proxy to your app
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

3. **Enable site and restart nginx**:
```bash
sudo ln -s /etc/nginx/sites-available/trading /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

4. **Start your app on HTTP** (nginx handles HTTPS):
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

---

## Troubleshooting

### Browser Shows "Not Secure" Warning

**For self-signed certificates**: This is expected. Click "Advanced" → "Proceed" for testing.

**For Let's Encrypt**: Check that:
- Certificate is valid: `sudo certbot certificates`
- Domain points to your server IP
- Firewall allows port 443

### Zerodha Rejects Webhook URL

- Self-signed certificates won't work - use Let's Encrypt
- Ensure webhook URL uses HTTPS (not HTTP)
- Test webhook manually: `curl -X POST https://yoururl.com/webhook/chartink?user_id=1 -d '{}'`

### Certificate Installation Failed

```bash
# Check Certbot logs
sudo cat /var/log/letsencrypt/letsencrypt.log

# Ensure port 80 is accessible
sudo ufw allow 80
sudo ufw allow 443
```

### Permission Denied on Port 443

Port 443 requires root privileges:
- Use `sudo` to run the application
- Or use nginx reverse proxy (recommended)
- Or use port forwarding: `sudo iptables -t nat -A PREROUTING -p tcp --dport 443 -j REDIRECT --to-port 8000`

---

## Security Best Practices

1. **Never commit SSL keys to git**
   - Add `*.pem` and `*.key` to `.gitignore`

2. **Use strong SSL settings**
   - TLS 1.2 or higher only
   - Strong cipher suites

3. **Keep certificates updated**
   - Monitor expiration dates
   - Enable auto-renewal

4. **Restrict access**
   - Use firewall rules
   - Only open necessary ports

---

## Support

- **Let's Encrypt**: https://letsencrypt.org/docs/
- **Certbot**: https://certbot.eff.org/
- **SSL Labs Test**: https://www.ssllabs.com/ssltest/

For help with this application, check the main README.md
